import logging
from functools import wraps

from django.core.cache import cache
from django.core.cache.backends.base import DEFAULT_TIMEOUT

from celery import states
from celery.exceptions import Ignore


log = logging.getLogger(__name__)


def prevent_asynchronous_task_execution(
    lock_key=None, lock_expiry=DEFAULT_TIMEOUT, retry=False, retry_countdown=15, mark_result_failed_on_lock_failure=True
):
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
                        self.update_state(state=states.FAILURE, meta="Task failed to acquire lock.")
                        # ignore the task so no other state is recorded
                        raise Ignore()
                    return

        return wrapper

    return decorator


def is_object_locked(obj):
    lock_key = obj.celery_object_lock_key()
    value = cache.get(lock_key)
    if value:
        log.info(f"{lock_key=} is locked")
    return value


def object_lock_acquire(obj, value=True, timeout=None):
    lock_key = obj.celery_object_lock_key()
    timeout = timeout or obj.celery_object_lock_timeout()

    return cache.add(lock_key, value, timeout)


def object_lock_release(obj):
    lock_key = obj.celery_object_lock_key()
    return cache.delete(lock_key)
