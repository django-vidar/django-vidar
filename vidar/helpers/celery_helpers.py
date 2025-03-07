import logging
import time
from contextlib import contextmanager
from functools import wraps

from django.core.cache import cache
from django.core.cache.backends.base import DEFAULT_TIMEOUT

from celery import current_app, states
from celery.exceptions import Ignore


log = logging.getLogger(__name__)


LOCK_EXPIRE = 60 * 30  # Lock expires in 30 minutes


@contextmanager
def celery_lock(lock_id, oid, timeout=LOCK_EXPIRE):
    """
    >>> event_id = 25
    >>> lock_id = f'stream-lock-{event_id}'
    >>> with celery_lock(lock_id, event_id, **kwargs) as acquired:
    >>>     if acquired:
    >>>         ...
    >>>         return True
    >>> print(f'{event_id}: event is already being recorded by another worker')

    """
    timeout_at = time.monotonic() + timeout - 3
    # cache.add fails if the key already exists
    status = cache.add(lock_id, oid, timeout)
    try:
        yield status
    finally:
        # memcache delete is very slow, but we have to use it to take
        # advantage of using add() for atomic locking
        if time.monotonic() < timeout_at and status:
            # don't release the lock if we exceeded the timeout
            # to lessen the chance of releasing an expired lock
            # owned by someone else
            # also don't release the lock if we didn't acquire it
            cache.delete(lock_id)


def _celery_task_is_in_system(celery_tasks, search_for_these_tasks: list, value, kwargs_key=None):

    for worker, tasks in celery_tasks.items():
        for task in tasks:

            if 'name' in task:
                task_name = task['name']
            elif 'request' in task and 'type' in task['request']:
                task_name = task['request']['type']
            else:
                log.info(f'Searching for {kwargs_key=} {value=} with task name {search_for_these_tasks=}, '
                         f'could not find task name value in {celery_tasks=}')
                continue

            if task_name in search_for_these_tasks:

                if kwargs_key:
                    if task and 'kwargs' in task and task['kwargs']:
                        kwarg_value = task['kwargs'].get(kwargs_key)
                        if kwarg_value == value:
                            return True

                    elif 'request' in task and 'kwargs' in task['request'] and task['request']['kwargs']:
                        kwarg_value = task['request']['kwargs']
                        if kwarg_value == value:
                            return True

                if task and 'args' in task and task['args']:
                    first_param = task['args'][0]

                    # first param seems to be wrapped in quotes within a string.
                    if value in first_param:
                        return True

                elif 'request' in task and 'args' in task['request'] and task['request']['args']:
                    first_param = task['request']['args'][0]

                    # first param seems to be wrapped in quotes within a string.
                    if value in first_param:
                        return True


def celery_is_task_active_or_pending(search_for_these_tasks: list, value, kwargs_key=None):

    if _celery_task_is_in_system(
            celery_tasks=current_app.control.inspect().active(),
            search_for_these_tasks=search_for_these_tasks,
            value=value,
            kwargs_key=kwargs_key
    ):
        return True

    if _celery_task_is_in_system(
            celery_tasks=current_app.control.inspect().reserved(),
            search_for_these_tasks=search_for_these_tasks,
            value=value,
            kwargs_key=kwargs_key
    ):
        return True

    if _celery_task_is_in_system(
            celery_tasks=current_app.control.inspect().scheduled(),
            search_for_these_tasks=search_for_these_tasks,
            value=value,
            kwargs_key=kwargs_key
    ):
        return True


def is_video_being_downloaded_now(video):
    # NOTE: Bad. celery doesn't always return the tasks that are actually running, use object_lock below.

    search_for_these_tasks = ['vidar.tasks.download_provider_video']
    return celery_is_task_active_or_pending(
        search_for_these_tasks=search_for_these_tasks,
        value=video.pk,
        kwargs_key='pk'
    )


def is_video_being_processed_now(video):
    # NOTE: Bad. celery doesn't always return the tasks that are actually running, use object_lock below.

    search_for_these_tasks = [
        'vidar.tasks.post_download_processing',
        'vidar.tasks.convert_video_to_mp4',
        'vidar.tasks.convert_video_to_audio',
        'vidar.tasks.write_file_to_storage',
    ]

    return celery_is_task_active_or_pending(
        search_for_these_tasks=search_for_these_tasks,
        value=video.pk,
        kwargs_key='pk'
    )


def prevent_asynchronous_task_execution(lock_key=None, lock_expiry=DEFAULT_TIMEOUT, retry=False,
                                        retry_countdown=15, mark_result_failed_on_lock_failure=True):
    """
    Decorator function to apply locking to Celery tasks; using a cache.
    If a task has already acquired a lock and is executing, then other tasks
    are made to retry after a set amount of time.
    NOTE: Tasks on which this is applied must be bound tasks (bind=True).

    Must be applied after @shared_task

    Example:

        @shared_task(bind=True)
        @prevent_asynchronous_task_execution()
        def my_task_here(pk):
            ...

    Args:
        lock_key:
            Unique value that locks this task in particular and prevents more calls to the same task from running.
            It is technically possible to supply a task parameter as a format value for the lock_key, such a
                lock_key = 'task-convert-{pk}
            However that requires you to always pass keyword arguments like .delay(pk=2) to the task
                and never use positional arguments like .delay(2)

        retry:
            Should the task keep retrying until the lock releases?

        retry_countdown:
            How many seconds to wait before retrying. Default is 15 seconds.

        mark_result_failed_on_lock_failure:
            If retry=False, should the task result be FAILURE or SUCCESS? Default is to update state to FAILURE.

        lock_expiry:
            How long in seconds do you expect the task to take, if this time is reached the lock auto-releases
                and the task can run again regardless of whether or not it is still running somehow.
            Default timeout is set to 300 seconds (5 minutes) within django settings.CACHES as per:
                https://docs.djangoproject.com/en/dev/topics/cache/#cache-arguments
            Supply lock_expiry=None to never timeout a lock. Be aware if the task is killed by the OS or by you
                restarting celery and the task doesn't get to finish, that would leave the lock in place
                forever and would require manual intervention. i.e. never use None, give it a timer.
    """

    def decorator(fun):
        @wraps(fun)
        def wrapper(self, *args, **kwargs):

            inner_lock_key = lock_key
            inner_lock_expiry = lock_expiry
            inner_retry_countdown = retry_countdown

            if not inner_lock_key:
                inner_lock_key = fun.__name__

            inner_lock_key = inner_lock_key.format(*args, **kwargs)

            log.info(f"celery lock: {fun.__name__} from running concurrently, {inner_lock_key=}")

            def acquire_lock():
                # Django cache.add returns True if the key was actually added.
                # Ensure that the cache backend has atomic add if you want really precise locking.
                return cache.add(inner_lock_key, True, inner_lock_expiry)

            def release_lock():
                # cache.delete is silent if the key does not exist
                return cache.delete(inner_lock_key)

            if acquire_lock():
                log.info(f"celery lock: {fun.__name__} lock acquired, proceeding. {inner_lock_key=}")
                try:
                    return fun(self, *args, **kwargs)
                finally:
                    release_lock()
            else:
                if retry:
                    log.info(f"{fun} {args=} {kwargs=} could not acquire lock; retrying in {inner_retry_countdown}s")
                    self.retry(countdown=inner_retry_countdown)
                else:
                    if mark_result_failed_on_lock_failure:
                        log.info(f"{fun} {args=} {kwargs=} could not acquire lock; marking result as {states.FAILURE}")
                        self.update_state(state=states.FAILURE, meta='Task failed to acquire lock.')
                        # ignore the task so no other state is recorded
                        raise Ignore()
                    return

        return wrapper
    return decorator


def is_object_locked(obj):
    lock_key = obj.celery_object_lock_key()
    value = cache.get(lock_key)
    if value:
        log.info(f'{lock_key=} is locked')
    return value


def object_lock_acquire(obj, value=True, timeout=None):
    lock_key = obj.celery_object_lock_key()
    timeout = timeout or obj.celery_object_lock_timeout()

    return cache.add(lock_key, value, timeout)


def object_lock_release(obj):
    lock_key = obj.celery_object_lock_key()
    return cache.delete(lock_key)
