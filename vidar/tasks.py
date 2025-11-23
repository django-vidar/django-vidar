import datetime
import json
import logging
import math
import os
import pathlib
import random
import requests.exceptions
import time
from functools import partial

from django.db import transaction
from django.db.models import Case, Count, F, Q, When
from django.db.utils import DataError
from django.utils import timezone

import yt_dlp
from celery import chain, shared_task, states
from celery.exceptions import Ignore
from django_celery_results.models import TaskResult

from vidar import app_settings, helpers, interactor, oneoffs, renamers, signals, utils
from vidar.exceptions import FileStorageBackendHasNoMoveError
from vidar.helpers import celery_helpers, channel_helpers, file_helpers, statistics_helpers, video_helpers
from vidar.models import Channel, Comment, Playlist, PlaylistItem, Video
from vidar.services import (
    channel_services,
    crontab_services,
    notification_services,
    playlist_services,
    redis_services,
    schema_services,
    video_services,
    ytdlp_services,
)


log = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(requests.exceptions.ConnectionError, KeyError, AttributeError),
    default_retry_delay=15,
    queue="queue-vidar",
)
def update_channel_banners(self, pk):

    channel = Channel.objects.get(pk=pk)

    log.info(f"Getting channel banners for {channel=}")

    dl_kwargs = ytdlp_services.get_ytdlp_args()

    try:
        output = interactor.channel_details(url=f"{channel.base_url}/about", instance=channel, **dl_kwargs)
    except yt_dlp.DownloadError as exc:
        if channel_services.apply_exception_status(channel=channel, exc=exc):
            self.update_state(state=states.FAILURE, meta=f"Channel status changed to {channel.status=}")
            # ignore the task so no other state is recorded
            raise Ignore()

        raise

    try:
        channel_services.set_channel_details_from_ytdlp(
            channel=channel,
            response=output,
        )
    except (TypeError, KeyError):
        log.exception("Failure to call set_channel_details_from_ytdlp")

    output["thumbnails"].reverse()

    tn_url = ytdlp_services.get_thumb_art(output["thumbnails"])
    b_url = ytdlp_services.get_banner_art(output["thumbnails"])
    tv_url = ytdlp_services.get_tv_art(output["thumbnails"])

    if not all([tn_url, b_url, tv_url]) and self.request.retries < 3:
        log.info(f"Failed to get 3 thumbnails for {channel=}")
        raise self.retry()

    if tn_url:
        channel_services.set_thumbnail(channel=channel, url=tn_url)
    if b_url:
        channel_services.set_banner(channel=channel, url=b_url)
    if tv_url:
        channel_services.set_tvart(channel=channel, url=tv_url)

    return self.request.retries


def trigger_channel_scanner_tasks(channel, limit=None, wait_period=30, countdown=0):

    channel.scan_history.create()

    if channel.index_videos:
        scan_channel_for_new_videos.apply_async(kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown)
        countdown += wait_period

    if channel.index_shorts:
        scan_channel_for_new_shorts.apply_async(kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown)
        countdown += wait_period

    if channel.index_livestreams:
        scan_channel_for_new_livestreams.apply_async(kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown)

    return countdown


def check_missed_channel_scans_since_last_ran(start=None, end=None, delta=None, force=False):
    if not end:
        end = timezone.localtime()

    if not delta:
        delta = timezone.timedelta(minutes=5)

    if not start:
        last_run = (
            TaskResult.objects.filter(
                task_name="vidar.tasks.trigger_crontab_scans",
                status="SUCCESS",
            )
            .order_by("-date_done")
            .first()
        )

        if not last_run:
            log.info("trigger_crontab_scans has never run before")
            return None, None

        if last_run:
            last_run_date_done_as_local_tz = timezone.localtime(last_run.date_done, timezone.get_default_timezone())
            start = last_run_date_done_as_local_tz.replace(second=0, microsecond=0)

    time_since_last_run = end - start

    log.info(f"check_when_crontab_last_ran {time_since_last_run=}")

    if not force:

        # crontab checker runs every X minutes, if the last one wasn't run in less than X time
        #   plus one half, then trigger the full time check since last ran.
        time_and_a_half = app_settings.CRONTAB_CHECK_INTERVAL * 1.5
        if time_since_last_run < timezone.timedelta(minutes=time_and_a_half):
            log.info(f"check crontab last ran less than {time_and_a_half} minutes, {time_since_last_run.seconds/60}")
            return None, None

        max_time_to_check = app_settings.CRONTAB_CHECK_INTERVAL_MAX_IN_DAYS
        if time_since_last_run > timezone.timedelta(days=max_time_to_check):
            log.info("Time since trigger_crontab_scans last ran is too great, not running.")
            return None, None

    processed_channels = []
    processed_playlists = []

    while start <= end:

        output = trigger_crontab_scans(
            now=start,
            processed_channels=processed_channels,
            processed_playlists=processed_playlists,
            check_if_crontab_was_missed=False,
        )
        processed_channels = output["channels"]
        processed_playlists = output["playlists"]

        start += delta

    return processed_channels, processed_playlists


@shared_task(queue="queue-vidar")
def trigger_crontab_scans(
    limit=None,
    now=None,
    processed_playlists: list = None,
    processed_channels: list = None,
    check_if_crontab_was_missed=True,
):
    # NOTE: Update forms.CrontabCatchupForm if the task name changes

    if check_if_crontab_was_missed and app_settings.AUTOMATED_CRONTAB_CATCHUP:
        processed_channels, processed_playlists = check_missed_channel_scans_since_last_ran()

    if not now:
        now = timezone.localtime()
    elif isinstance(now, float):
        now = timezone.datetime.fromtimestamp(now, datetime.timezone.utc)
        now = now.astimezone(timezone.get_default_timezone())

    processed = {
        "channels": processed_channels or [],
        "playlists": processed_playlists or [],
    }

    countdown = 0

    for channel in Channel.objects.actively_scanning():

        if channel.id in processed["channels"]:
            log.debug(f"Skipping {channel} as its already sent for processing")
            continue

        if not crontab_services.is_active_now(channel.scanner_crontab, now=now):
            continue

        if sh := channel_services.recently_scanned(channel=channel):
            log.info(f"Channel was recently scanned ({sh.inserted}) and will not be scanned again so soon. {channel=}")
            continue

        trigger_channel_scanner_tasks(channel=channel, limit=limit, countdown=countdown)

        processed["channels"].append(channel.id)
        countdown += 6

    for channel in Channel.objects.filter(scan_after_datetime__lte=timezone.now()):

        Channel.objects.filter(pk=channel.pk).update(scan_after_datetime=None)

        if channel.id in processed["channels"]:
            log.debug(f"Skipping {channel} as its already sent for processing")
            continue

        trigger_channel_scanner_tasks(channel=channel, limit=limit, countdown=countdown)

        processed["channels"].append(channel.id)
        countdown += 6

    for playlist in Playlist.objects.exclude(crontab=""):

        if playlist.id in processed["playlists"]:
            log.debug(f"Skipping {playlist=} as its already sent for processing")
            continue

        if not crontab_services.is_active_now(playlist.crontab, now):
            continue

        if sh := playlist_services.recently_scanned(playlist=playlist):
            log.info(f"Playlist recently scanned ({sh.inserted}) and will not be scanned again so soon. {playlist=}")
            continue

        sync_playlist_data.delay(pk=playlist.pk)

        processed["playlists"].append(playlist.id)

    return processed


@shared_task(bind=True, queue="queue-vidar")
@celery_helpers.prevent_asynchronous_task_execution(lock_key="full-index-channel-{pk}")
def fully_index_channel(self, pk, limit=None):
    # if limit is supplied this acts more as a "index X number of items" rather than a full indexing.

    channel = Channel.objects.get(pk=pk)

    existing_videos_count = channel.videos.count()

    targets = {}
    if channel.index_videos and (not channel.fully_indexed or limit):
        targets["Videos"] = {
            "video_field": "is_video",
            "channel_field": "fully_indexed",
            "url": channel.url,
        }
    if channel.index_shorts and (not channel.fully_indexed_shorts or limit):
        targets["Shorts"] = {
            "video_field": "is_short",
            "channel_field": "fully_indexed_shorts",
            "url": channel.shorts_url,
        }
    if channel.index_livestreams and (not channel.fully_indexed_livestreams or limit):
        targets["Livestreams"] = {
            "video_field": "is_livestream",
            "channel_field": "fully_indexed_livestreams",
            "url": channel.livestreams_url,
        }

    if not targets:
        log.info("No targets for full indexing")
        return

    dl_kwargs = ytdlp_services.get_ytdlp_args()

    msg_logger = partial(
        utils.OutputCapturer, callback_func=redis_services.channel_indexing, channel=channel, **dl_kwargs
    )

    for target_name, target_data in targets.items():
        chan = interactor.func_with_retry(url=target_data["url"], limit=limit, logger=msg_logger())

        if not chan:
            continue

        for video_data in chan["entries"]:

            # Videos premiering in the future cannot be downloaded.
            if not video_data:
                continue

            video_services.unblock(video_data["id"])

            params = {target_data["video_field"]: True}

            video, created = Video.objects.get_or_create_from_ytdlp_response(video_data, **params)

            if video.upload_date:
                video.inserted = video.inserted.replace(
                    year=video.upload_date.year,
                    month=video.upload_date.month,
                    day=video.upload_date.day,
                )
                video.save()

            video.check_and_add_video_to_playlists_based_on_title_matching()

        if target_name == "Videos":
            channel.last_scanned = timezone.now()
        elif target_name == "Shorts":
            channel.last_scanned_shorts = timezone.now()
        elif target_name == "Livestreams":
            channel.last_scanned_livestreams = timezone.now()

        if not limit:
            setattr(channel, target_data["channel_field"], True)
        channel.save()
        total_videos_count = channel.videos.count()
        new_videos_count = total_videos_count - existing_videos_count
        notification_services.full_indexing_complete(
            channel=channel,
            target=target_name,
            new_videos_count=new_videos_count,
            total_videos_count=total_videos_count,
        )

    channel_services.recalculate_video_sort_ordering(channel=channel)


def scan_channel_for_new_content(
    self, channel, url, limit=None, download_video=False, is_video=False, is_short=False, is_livestream=False
):

    dl_kwargs = ytdlp_services.get_ytdlp_args()

    msg_logger = partial(utils.OutputCapturer, callback_func=redis_services.channel_indexing, channel=channel)

    try:
        chan = interactor.func_with_retry(
            url=url, limit=limit or channel.scanner_limit, logger=msg_logger(), **dl_kwargs
        )
    except yt_dlp.DownloadError as exc:

        if channel_services.apply_exception_status(channel=channel, exc=exc):

            self.update_state(state=states.FAILURE, meta=f"Channel status changed to {channel.status=}")
            # ignore the task so no other state is recorded
            raise Ignore()

        raise

    if not chan:
        return

    if not chan.get("entries"):
        log.info(f"No videos found for {channel=}")
        return

    for video_data in chan["entries"]:

        # Videos premiering in the future cannot be downloaded.
        if not video_data:
            continue

        if not channel.uploader_id and video_data["uploader_id"]:
            channel.uploader_id = video_data["uploader_id"]
            channel.save(update_fields=["uploader_id"])

        if video_services.is_blocked(video_data["id"]):
            continue

        video, created = Video.objects.get_or_create_from_ytdlp_response(
            data=video_data,
            is_video=is_video,
            is_short=is_short,
            is_livestream=is_livestream,
        )
        log.info(f"Checking video {video=}")

        if video.file:
            log.info("Video already has file, skipping.")
            if video_services.should_download_comments(video=video):
                download_provider_video_comments.delay(pk=video.pk)
            continue

        try:
            video.check_and_add_video_to_playlists_based_on_title_matching()
        except:  # noqa: E722 ; pragma: no cover
            log.exception("Failure to check and add video to playlists based on title matching")

        if not video.permit_download:
            log.info("Not permitted, video.permit_download=False")
            continue

        if video_services.is_too_old(video=video):
            log.info(f"Skipping, video is considered too told, {video.upload_date} {video}")
            continue

        if video_services.should_force_download_based_on_requirements_requested(video=video):
            log.info(f"Forcing video to download, {video=}")
            download_provider_video.delay(pk=video.pk, task_source="scanner", requested_by="Channel Scanner")
            continue

        if not download_video:
            log.info(f"{download_video=}, skipping")
            continue

        # If the video is an existing item, and we're re-scanning,
        #   don't let it download. That'll need force downloading.
        # It means the user selected to NOT download on the add
        #   channel form and then changed it after the fact.
        if not created:
            continue

        if video_services.is_permitted_to_download_requested(video=video):
            log.info("Video download is permitted, triggering downloader")
            download_provider_video.delay(pk=video.pk, task_source="scanner", requested_by="Channel Scanner")
        else:
            log.info("Video not permitted, skipping.")

    return True


@shared_task(bind=True, queue="queue-vidar")
@celery_helpers.prevent_asynchronous_task_execution(lock_key="channel-scan-videos-{pk}")
def scan_channel_for_new_videos(self, pk, limit=None):

    channel = Channel.objects.get(pk=pk)

    output = scan_channel_for_new_content(
        self=self,
        channel=channel,
        url=channel.url,
        limit=limit or channel.scanner_limit,
        download_video=channel.download_videos,
        is_video=True,
    )

    if output:
        channel.last_scanned = timezone.now()
        channel.save(update_fields=["last_scanned"])

    return output


@shared_task(bind=True, queue="queue-vidar")
@celery_helpers.prevent_asynchronous_task_execution(lock_key="channel-scan-shorts-{pk}")
def scan_channel_for_new_shorts(self, pk, limit=None):

    channel = Channel.objects.get(pk=pk)

    try:
        output = scan_channel_for_new_content(
            self=self,
            channel=channel,
            url=channel.shorts_url,
            limit=limit or channel.scanner_limit_shorts,
            download_video=channel.download_shorts,
            is_short=True,
        )
    except yt_dlp.DownloadError as e:
        if "does not have a shorts tab" in str(e):
            channel.index_shorts = False
            channel.download_shorts = False
            channel.save(update_fields=["index_shorts", "download_shorts"])
        raise

    if output:
        channel.last_scanned_shorts = timezone.now()
        channel.save(update_fields=["last_scanned_shorts"])

    return output


@shared_task(bind=True, queue="queue-vidar")
@celery_helpers.prevent_asynchronous_task_execution(lock_key="channel-scan-livestreams-{pk}")
def scan_channel_for_new_livestreams(self, pk, limit=None):

    channel = Channel.objects.get(pk=pk)

    try:
        output = scan_channel_for_new_content(
            self=self,
            channel=channel,
            url=channel.livestreams_url,
            limit=limit or channel.scanner_limit_livestreams,
            download_video=channel.download_livestreams,
            is_livestream=True,
        )
    except yt_dlp.DownloadError as e:
        if "not currently live" in str(e):
            channel.index_livestreams = False
            channel.download_livestreams = False
            channel.save(update_fields=["index_livestreams", "download_livestreams"])
        raise

    if output:
        channel.last_scanned_livestreams = timezone.now()
        channel.save(update_fields=["last_scanned_livestreams"])

    return output


@shared_task(queue="queue-vidar")
def automated_archiver():
    # NOTE: Update logic in views.download_queue if you change it below.

    for channel in Channel.objects.active().filter(full_archive_after__lt=timezone.now()):
        channel.full_archive_after = None
        channel.full_archive = True
        channel.slow_full_archive = False
        channel.send_download_notification = False
        channel.save()
        notification_services.full_archiving_started(channel=channel)

    for channel in Channel.objects.active().filter(full_index_after__lt=timezone.now()):
        channel.full_index_after = None
        channel.save()
        fully_index_channel.delay(pk=channel.pk)

    for channel in Channel.objects.active().filter(swap_index_videos_after__lt=timezone.now()):
        channel.index_videos = not channel.index_videos
        channel.swap_index_videos_after = None
        channel.save()

    for channel in Channel.objects.active().filter(swap_index_shorts_after__lt=timezone.now()):
        channel.index_shorts = not channel.index_shorts
        channel.swap_index_shorts_after = None
        channel.save()

    for channel in Channel.objects.active().filter(swap_index_livestreams_after__lt=timezone.now()):
        channel.index_livestreams = not channel.index_livestreams
        channel.swap_index_livestreams_after = None
        channel.save()

    max_automated_downloads = app_settings.AUTOMATED_DOWNLOADS_PER_TASK_LIMIT
    total_downloads = 0
    max_daily_automated_downloads = app_settings.AUTOMATED_DOWNLOADS_DAILY_LIMIT
    todays_downloads = Video.objects.filter(date_downloaded__date=timezone.localdate()).exclude(file="").count()

    if max_daily_automated_downloads and todays_downloads >= max_daily_automated_downloads:
        log.info(f"Max daily automated downloads reached. {todays_downloads=} >= {max_daily_automated_downloads=}")
        return

    for playlist in Playlist.objects.filter(hidden=False).order_by("inserted"):

        public_playlist_videos = playlist.playlistitem_set.filter(
            video__file="",
            video__privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible,
            download=True,
        )

        for pli in public_playlist_videos:
            video = pli.video

            if total_downloads >= max_automated_downloads:
                break

            if video.download_errors.exists():
                log.info(f"Skipping {video=} as its errored while downloading and will be handled later on")
                continue

            if celery_helpers.is_object_locked(obj=video):
                continue

            if playlist.title_skips and utils.contains_one_of_many(video.title, playlist.title_skips.splitlines()):
                pli.download = False
                pli.save()
                log.info(f"Skipping video due to playlist title_skips matched. {video=}")
                continue

            if playlist.restrict_to_assigned_channel and playlist.channel and video.channel != playlist.channel:
                log.info(
                    f"Playlist set to only download videos attached to the same channel. "
                    f"Skipping. {playlist.channel=} {video.channel=} {video=}"
                )
                continue

            download_provider_video.delay(
                pk=video.pk,
                task_source=f"automated_archiver - Playlist Scanner: {playlist}",
                requested_by=f"Playlist: {playlist!r}",
            )

            total_downloads += 1

            if utils.should_halve_download_limit(duration=video.duration):
                max_automated_downloads //= 2

    for channel in Channel.objects.active().filter(full_archive=True):

        needs_indexing = (
            (channel.index_videos and not channel.fully_indexed)
            or (channel.index_shorts and not channel.fully_indexed_shorts)
            or (channel.index_livestreams and not channel.fully_indexed_livestreams)
        )

        if needs_indexing:
            fully_index_channel.delay(pk=channel.pk)
            continue

        full_archive_videos_to_process = channel.videos.filter(
            file="", privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible
        )

        if channel.full_archive_cutoff:
            log.debug(f"Full Archive Cutoff: {channel.full_archive_cutoff=}")
            full_archive_videos_to_process = full_archive_videos_to_process.filter(
                upload_date__gte=channel.full_archive_cutoff
            )

        if not full_archive_videos_to_process.exists():
            # If no videos exists then archiving is complete, and we can return to smaller checks.
            channel_services.full_archiving_completed(channel=channel)
            notification_services.full_archiving_completed(channel=channel)

        for video in full_archive_videos_to_process.order_by("upload_date"):

            if total_downloads >= max_automated_downloads:
                break

            if video.download_errors.exists():
                log.info(f"Skipping {video=} as its errored while downloading and will be handled later on")
                continue

            if celery_helpers.is_object_locked(obj=video):
                continue

            download_provider_video.delay(
                pk=video.pk,
                task_source="automated_archiver - Channel Full Archive",
                requested_by=f"Full Archive: {channel!r}",
            )

            total_downloads += 1

            if utils.should_halve_download_limit(duration=video.duration):
                max_automated_downloads //= 2

    # defaults are 5 errors a day, lets set it to 14 days worth of attempts.
    maximum_attempts_erroring_downloads = app_settings.VIDEO_DOWNLOAD_ERROR_ATTEMPTS
    minutes_to_wait_between_error_attempts = app_settings.VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD

    videos_with_download_errors = Video.objects.annotate(total_download_errors=Count("download_errors")).filter(
        permit_download=True,
        total_download_errors__lt=maximum_attempts_erroring_downloads,
        total_download_errors__gte=1,
    )

    for video in videos_with_download_errors.order_by("upload_date"):

        if total_downloads >= max_automated_downloads:
            break

        if celery_helpers.is_object_locked(obj=video):
            continue

        if video.file:
            log.error("automated_archiver just tried to process a video with download errors that already has a file.")
            video.download_errors.all().delete()
            continue

        if video.at_max_download_errors_for_period():
            log.debug(f"{video=} at max daily errors. Skipping.")
            continue

        # If its under X time since the last download error, wait.
        diff = timezone.now() - video.download_errors.latest().inserted
        if diff < timezone.timedelta(minutes=minutes_to_wait_between_error_attempts):
            log.debug(f"{video=} retried too soon, waiting longer.")
            continue

        download_provider_video.delay(pk=video.pk, task_source="automated_archiver - Video Download Errors Attempts")

        total_downloads += 1

        if utils.should_halve_download_limit(duration=video.duration):
            max_automated_downloads //= 2

    if app_settings.VIDEO_AUTO_DOWNLOAD_LIVE_AMQ_WHEN_DETECTED:

        # AMQ would change from update_video_details task.
        for video in (
            Video.objects.filter(
                requested_max_quality=True,
                at_max_quality=False,
                date_downloaded__lte=timezone.now() - timezone.timedelta(days=3),
                system_notes__max_quality_upgraded__isnull=True,
            )
            .exclude(file="")
            .order_by("upload_date")
        ):

            if total_downloads >= max_automated_downloads:
                break

            highest_format = ytdlp_services.get_highest_quality_from_video_dlp_formats(video.dlp_formats)

            if video.quality == highest_format:
                continue

            if celery_helpers.is_object_locked(obj=video):
                continue

            log.info(f"Videos live quality is better than we are expecting. Attempting an upgrade {video=}")

            video.system_notes["max_quality_upgraded"] = timezone.now().isoformat()
            video.save()

            download_provider_video.delay(
                pk=video.pk, task_source="automated_archiver - Video Quality Changed Afterwards"
            )

            total_downloads += 1

            if utils.should_halve_download_limit(duration=video.duration):
                max_automated_downloads //= 2

    hours = app_settings.VIDEO_LIVE_DOWNLOAD_RETRY_HOURS
    hours_ago = timezone.now() - timezone.timedelta(hours=hours)
    for video in Video.objects.filter(system_notes__video_was_live_at_last_attempt=True, inserted__lte=hours_ago):

        log.info(f"{video.pk=} was live when it attempted its download, trying again now {hours=} later")

        if celery_helpers.is_object_locked(obj=video):
            continue

        del video.system_notes["video_was_live_at_last_attempt"]
        video.save()

        if video.file:
            continue

        download_provider_video.apply_async(
            kwargs=dict(
                pk=video.pk,
                task_source="Live Download - Reattempt",
            ),
            countdown=10,
        )


@shared_task(
    bind=True,
    autoretry_for=(Video.DoesNotExist,),
    retry_kwargs={"max_retries": 3},
    default_retry_delay=5,
    queue="queue-vidar",
)
@celery_helpers.prevent_asynchronous_task_execution(lock_key="download-vidar-video-{pk}")
def download_provider_video(
    self, pk, quality=None, automated_quality_upgrade=False, task_source="Unknown", requested_by=None
):

    download_started = timezone.now()
    video = Video.objects.get(pk=pk)

    log.info(f"Download requested for video {video=}")

    if celery_helpers.is_object_locked(obj=video):
        log.info(f"{video.pk=} is object locked. Ending now.")
        self.update_state(state=states.FAILURE, meta="Video is currently locked.")
        raise Ignore()
    else:
        if not celery_helpers.object_lock_acquire(obj=video):
            log.info(f"Failure to acquire lock for {video.pk=}. Ending now.")
            raise SystemError(f"Failure to acquire lock for {video.celery_object_lock_key()=}.")

    cache_folder = pathlib.Path(app_settings.MEDIA_CACHE)

    if quality is None:
        selected_quality = video_services.quality_to_download(video=video)
    else:
        selected_quality = quality

    # Last ditch attempt to get any quality when errors for current quality hit maximum.
    if video.at_max_download_errors_for_period():
        selected_quality = 0
        quality = 0

    dl_kwargs = ytdlp_services.get_video_downloader_args(
        quality=selected_quality,
        cache_folder=cache_folder,
        retries=self.request.retries,
        video=video,
    )

    video.save_download_kwargs(dl_kwargs)

    signals.video_download_started.send(sender=Video, instance=video, dl_kwargs=dl_kwargs)

    try:
        info, used_dl_kwargs = interactor.video_download(
            url=video.url, local_url=video.get_absolute_url(), instance=video, **dl_kwargs
        )
    except yt_dlp.DownloadError as exc:

        celery_helpers.object_lock_release(obj=video)

        if video_services.download_exception(
            video=video,
            exception=exc,
            dl_kwargs=dl_kwargs,
            quality=quality,
            selected_quality=selected_quality,
            cache_folder=cache_folder,
            retries=self.request.retries,
        ):
            signals.video_download_failed.send(sender=Video, instance=video, dl_kwargs=dl_kwargs, exc=exc)
            return

        signals.video_download_retry.send(sender=Video, instance=video, dl_kwargs=dl_kwargs, exc=exc)

        # Retry in 1 minutes.
        raise self.retry(countdown=1 * 60)

    except Exception as exc:  # noqa: E722
        # All other exceptions needs to unlock the video.
        celery_helpers.object_lock_release(obj=video)
        signals.video_download_failed.send(sender=Video, instance=video, dl_kwargs=dl_kwargs, exc=exc)
        raise

    video.set_details_from_yt_dlp_response(info)

    try:
        video.quality = ytdlp_services.get_video_downloaded_quality_from_dlp_response(info)
        video.at_max_quality = ytdlp_services.is_video_at_highest_quality_from_dlp_response(info)
    except (TypeError, ValueError):
        log.exception("Failure to obtain video resolution data from dlp response")

        video.quality = selected_quality
        video.at_max_quality = not selected_quality

    video.quality = ytdlp_services.fix_quality_values(video.quality)
    video.requested_max_quality = not selected_quality

    if requested_by and not video.download_requested_by:
        video.download_requested_by = requested_by

    if not automated_quality_upgrade:
        video.date_downloaded = timezone.now()
    video.download_errors.all().delete()
    video.format_id = info.get("format_id", "")
    video.format_note = info.get("format_note", "")
    video.force_download = False

    # requested_downloads will have multiple entries if multiple formats are requested.
    # This system only ever requests one format.
    downloaded_file_data = info["requested_downloads"][0]
    filepath = pathlib.Path(downloaded_file_data["filepath"])

    video_services.save_infojson_file(
        video=video,
        downloaded_file_data=downloaded_file_data,
        overwrite_formats=False,
    )

    video.set_latest_download_stats(
        status="success",
        quality=video.quality,
        selected_quality=selected_quality,
        at_max_quality=video.at_max_quality,
        dl_kwargs=dl_kwargs,
        used_dl_kwargs=used_dl_kwargs,
        raw_file_path=str(filepath),
        download_started=download_started,
        download_finished=timezone.now(),
        task_source=task_source,
    )

    signals.video_download_finished.send(sender=Video, instance=video, dl_kwargs=dl_kwargs)

    post_download_processing.apply_async(
        kwargs=dict(
            pk=video.pk,
            filepath=str(filepath),
        ),
        countdown=1,
    )


@shared_task(bind=True, queue="queue-vidar")
def post_download_processing(self, pk, filepath):
    # NOTE: update celery_helpers if you change this task name

    filepath = pathlib.Path(filepath)

    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=pk)
        video.append_to_latest_download_stats(processing_started=timezone.now())

    c = chain()

    if video_services.should_convert_to_audio(video=video):
        log.info("Adding convert_video_to_audio to the chain")
        c |= convert_video_to_audio.si(pk=pk, filepath=str(filepath), return_filepath=True)
        c |= write_file_to_storage.s(pk=pk, field_name="audio")
        c |= delete_cached_file.s()

    if app_settings.SHOULD_CONVERT_FILE_TO_HTML_PLAYABLE_FORMAT(filepath=filepath):
        log.info("Adding convert_video_to_mp4 to the chain")
        c |= convert_video_to_mp4.si(pk=pk, filepath=str(filepath))
        c |= write_file_to_storage.s(pk=pk, field_name="file")
        c |= delete_cached_file.s()

        # convert_video_to_mp4 makes a copy of the video into its new format
        #   leaving the original file still existing
        c |= delete_cached_file.si(filepath=str(filepath))
    else:
        c |= write_file_to_storage.si(pk=pk, filepath=str(filepath), field_name="file")
        c |= delete_cached_file.s()

    c |= video_downloaded_successfully.si(pk=pk)

    c()
    return True


@shared_task(queue="queue-vidar")
def write_file_to_storage(filepath, pk, field_name):
    # NOTE: update celery_helpers if you change this task name

    log.info(f"write_file_to_storage {field_name=} {filepath=}")

    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=pk)

        log.debug(f"before delete {video.file}")
        log.debug(f"before delete {video.audio}")

        filepath = pathlib.Path(filepath)

        _, ext = filepath.name.rsplit(".", 1)

        try:
            if field_name == "file" and video.file:
                video.file.delete()
            elif field_name == "audio" and video.audio:
                video.audio.delete()
        except OSError:  # pragma: no cover
            log.exception(f"Failure to delete existing video.{field_name} {video.pk=}")

        log.debug(f"after delete {video.file}")
        log.debug(f"after delete {video.audio}")

        if app_settings.MEDIA_HARDLINK:

            upload_to = video_helpers.upload_to_file
            if field_name == "audio":
                upload_to = video_helpers.upload_to_audio

            new_full_filepath, new_storage_path = video_services.generate_filepaths_for_storage(
                video=video,
                ext=ext,
                ensure_new_dir_exists=True,
                upload_to=upload_to,
            )
            try:
                log.info(f'Hard linking "{filepath=}" to "{new_full_filepath=}"')
                new_full_filepath.hardlink_to(filepath)
            except FileExistsError:
                log.info("Hardlink failure FileExistsError, unlink and then retrying.")
                new_full_filepath.unlink(missing_ok=True)
                time.sleep(2)
                new_full_filepath.hardlink_to(filepath)

            if field_name == "file":
                video.file.name = str(new_storage_path)
            elif field_name == "audio":
                video.audio.name = str(new_storage_path)

        else:
            log.info(f"Saving file using ORM, {filepath}")
            final_filename = schema_services.video_file_name(video=video, ext=ext)
            with filepath.open("rb") as fo:
                if field_name == "file":
                    video.file.save(final_filename, fo, save=False)
                elif field_name == "audio":
                    video.audio.save(final_filename, fo, save=False)

        if field_name == "file" and video.file:
            try:
                video.file_size = filepath.stat().st_size
            except FileNotFoundError:  # pragma: no cover
                log.exception(f"Failure to obtain video.file.size on {video=}")

        log.debug(f"before return {video.file=}")
        log.debug(f"before return {video.audio=}")

        video.save()

    return str(filepath)


@shared_task(queue="queue-vidar")
def delete_cached_file(filepath):
    log.info(f"Deleting {filepath=}")
    if not app_settings.DELETE_DOWNLOAD_CACHE:
        log.info("System DELETE_DOWNLOAD_CACHE is False. Not deleting.")
        return
    try:
        os.unlink(filepath)
    except OSError:  # pragma: no cover
        log.exception("Failure to delete cached file.")
    return True


@shared_task(
    autoretry_for=(requests.exceptions.ConnectionError,),
    retry_kwargs={"max_retries": 3},
    default_retry_delay=15,
    queue="queue-vidar",
)
def load_video_thumbnail(pk, url):
    if not url:
        raise ValueError("Bad url supplied")
    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=pk)
        video_services.set_thumbnail(video=video, url=url)


@shared_task(bind=True, queue="queue-vidar")
def video_downloaded_successfully(self, pk):

    video = Video.objects.get(pk=pk)

    info_json_data = {}
    if video.info_json:
        with video.info_json.open() as fo:
            info_json_data = json.load(fo)

    try:
        video_services.load_chapters_from_info_json(video=video, reload=True, info_json_data=info_json_data)
    except:  # noqa: E722 ; pragma: no cover
        log.exception(f"Failure to load chapters on {video=}")

    load_video_thumbnail.apply_async(args=[pk, info_json_data.get("thumbnail")], countdown=30)

    try:
        video.search_description_for_related_videos()
    except:  # noqa: E722 ; pragma: no cover
        log.exception("Failed to search description for related videos.")

    video.log_to_scanhistory()

    signals.video_download_successful.send(
        sender=Video,
        instance=video,
    )

    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=pk)
        video.append_to_latest_download_stats(processing_finished=timezone.now())

    notification_services.video_downloaded(video=video)

    if video_services.should_download_comments(video=video):
        download_provider_video_comments.delay(pk=pk)

    if app_settings.LOAD_SPONSORBLOCK_DATA_ON_DOWNLOAD:
        load_sponsorblock_data.delay(pk=pk)

    celery_helpers.object_lock_release(obj=video)


@shared_task(
    bind=True,
    autoretry_for=(Video.DoesNotExist,),
    retry_kwargs={"max_retries": 3},
    default_retry_delay=5,
    queue="queue-vidar",
)
def download_provider_video_comments(self, pk, all_comments=False):
    video = Video.objects.get(pk=pk)

    if video.privacy_status not in Video.VideoPrivacyStatuses_Publicly_Visible:
        log.info("Video is not publicly visible, skipping.")
        return

    dl_kwargs = ytdlp_services.get_ytdlp_args(
        proxies_attempted=video.system_notes.get("proxies_attempted_comment_grabber"),
        video=video,
        retries=self.request.retries,
    )

    try:
        info = interactor.video_comments(url=video.url, all_comments=all_comments, instance=video, **dl_kwargs)
    except yt_dlp.DownloadError as exc:

        if "proxy" in dl_kwargs:
            proxies_attempted = video.system_notes.get("proxies_attempted_comment_grabber", [])
            proxies_attempted.append(dl_kwargs["proxy"])
            video.system_notes["proxies_attempted_comment_grabber"] = proxies_attempted

            video.save(update_fields=["system_notes"])

        raise self.retry(countdown=1 * 60, exc=exc)

    comments_downloaded_timestamps = video.system_notes.get("comments_downloaded", [])
    comments_downloaded_timestamps.append(timezone.now().isoformat())
    video.system_notes["comments_downloaded"] = comments_downloaded_timestamps
    video.save(update_fields=["system_notes"])

    if not info:
        log.info(f"No comments found on {video=}, either yt-dlp failed or video has comments disabled.")
        return

    for data in info["comments"]:

        comment_id = data["id"]
        parent_id = data["parent"]
        timestamp_raw = data["timestamp"]
        parent = None

        try:
            timestamp = utils.convert_timestamp_to_datetime(timestamp_raw)
        except (TypeError, KeyError):
            log.info(f"Comment {comment_id=}: timezone conversion failure {timestamp_raw=}")
            timestamp = timezone.now()

        if parent_id and parent_id != "root":
            try:
                parent = Comment.objects.get(id=parent_id)
            except Comment.DoesNotExist:
                log.info(f"Comment {comment_id=}: parent comment {parent_id=} was not found.")
                continue

        Comment.objects.update_or_create(
            video=video,
            id=comment_id,
            parent=parent,
            defaults=dict(
                author=data["author"],
                author_id=data["author_id"],
                author_is_uploader=data["author_is_uploader"],
                author_thumbnail=data["author_thumbnail"],
                is_favorited=data["is_favorited"],
                like_count=data["like_count"] or 0,
                timestamp=timestamp,
                parent_youtube_id=data["parent"],
                text=data["text"],
            ),
        )


@shared_task(
    bind=True,
    autoretry_for=(Channel.DoesNotExist,),
    retry_kwargs={"max_retries": 3},
    default_retry_delay=5,
    queue="queue-vidar",
)
def subscribe_to_channel(self, channel_id, sleep=True):

    obj = Channel.objects.get(provider_object_id=channel_id)

    dl_kwargs = ytdlp_services.get_ytdlp_args()
    output = interactor.channel_details(f"{obj.base_url}/about", instance=obj, **dl_kwargs)

    channel_services.set_channel_details_from_ytdlp(
        channel=obj,
        response=output,
    )

    update_channel_banners.delay(obj.pk)

    if sleep:  # pragma: no cover
        time.sleep(1)

    Playlist.objects.filter(channel_provider_object_id=obj.provider_object_id).update(channel=obj)
    Video.objects.filter(channel_provider_object_id=obj.provider_object_id, channel__isnull=True).update(channel=obj)

    for video in obj.videos.exclude(file=""):
        rename_video_files.delay(pk=video.pk)

    trigger_channel_scanner_tasks(obj)


@shared_task(bind=True, queue="queue-vidar-processor")
def convert_video_to_audio(self, pk, filepath=None, return_filepath=False):
    # NOTE: update celery_helpers if you change this task name

    with transaction.atomic():
        video = Video.objects.select_for_update().get(id=pk)
        video.append_to_latest_download_stats(convert_video_to_audio_started=timezone.now())

    local_filepath = filepath
    was_remote = False
    if not local_filepath:
        local_filepath, was_remote = app_settings.ENSURE_FILE_IS_LOCAL(file_field=video.file)

    output_filepath = app_settings.CONVERT_FILE_TO_AUDIO_FORMAT(filepath=local_filepath)

    if was_remote:
        os.unlink(local_filepath)

    with transaction.atomic():
        video = Video.objects.select_for_update().get(id=pk)
        video.append_to_latest_download_stats(convert_video_to_audio_finished=timezone.now())

    if return_filepath:
        return str(output_filepath)

    c = write_file_to_storage.s(
        pk=pk,
        filepath=str(output_filepath),
        field_name="audio",
    )
    c |= delete_cached_file.s()
    c()

    return True


@shared_task(bind=True, queue="queue-vidar")
@celery_helpers.prevent_asynchronous_task_execution(lock_key="sync-playlist-data-{pk}")
def sync_playlist_data(self, pk, detailed_video_data=False, initial_sync=False):

    playlist = Playlist.objects.get(pk=pk)

    playlist_scan_history = playlist.scan_history.create()

    msg_logger = partial(utils.OutputCapturer, callback_func=redis_services.playlist_indexing, playlist=playlist)

    dl_kwargs = ytdlp_services.get_ytdlp_args()

    output = interactor.playlist_details(
        playlist.url,
        logger=msg_logger(),
        detailed_video_data=detailed_video_data,
        instance=playlist,
        **dl_kwargs,
    )

    if not output:
        playlist.not_found_failures += 1

        if playlist.not_found_failures >= 5:
            playlist.crontab = ""
            notification_services.playlist_disabled_due_to_errors(playlist=playlist)
            log.critical(
                f"Playlist {playlist}: failed to be found {playlist.not_found_failures} times, "
                f"disabling it from scans."
            )
        else:
            log.info(f"Playlist {playlist}: Not found on provider")

        playlist.save()
        return

    playlist.not_found_failures = 0

    playlist.title = output["title"]
    playlist.description = output["description"]
    playlist.channel_provider_object_id = output["channel_id"]

    if not playlist.channel:
        try:
            playlist.channel = Channel.objects.get(provider_object_id=output["channel_id"])
        except Channel.DoesNotExist:
            pass

    playlist.last_scanned = timezone.now()
    playlist.save()

    videos_existing = list(playlist.videos.all())

    new_videos = 0

    comments_countdown = 0

    for index, video_data in enumerate(output["entries"]):

        if not video_data:
            log.info(f"{playlist.pk=} {index=} returned {video_data}")
            continue

        if video_data["title"].lower() in ["[private video]", "[deleted video]"]:
            log.info(f"{playlist.pk=} {index=} seen from yt-dlp: {video_data['title']}. Stopping.")
            continue

        log.info(f"{playlist.pk=} {index=} seen from yt-dlp: {video_data['title']}")

        if video_services.is_blocked(video_data["id"]):
            log.info("video is blocked.")
            continue

        try:
            video, video_created = Video.objects.get_or_create_from_ytdlp_response(video_data)
        except DataError:
            log.exception(
                f"Failure to save video {video_data['id']} to system as a DataError occurred using {video_data=}"
            )
            continue

        if video_created:
            new_videos += 1

        if video in videos_existing:
            videos_existing.remove(video)

        pli, pli_created = playlist.playlistitem_set.get_or_create(video_id=video.pk)

        if not initial_sync and pli_created:
            notification_services.video_added_to_playlist(video=video, playlist=playlist)

        if pli_created and not video.permit_download:
            log.info("Not permitted, video.permit_download=False")
            pli.download = False

        if not pli.provider_object_id:
            pli.provider_object_id = video.provider_object_id

        if pli.missing_from_playlist_on_provider or pli.manually_added:
            pli.missing_from_playlist_on_provider = False
            pli.manually_added = False
            pli.display_order = index
            notification_services.video_readded_to_playlist(video=video, playlist=playlist)

        pli.save()

        if playlist.disable_when_string_found_in_video_title and playlist.crontab:
            values = playlist.disable_when_string_found_in_video_title.lower().splitlines()
            if utils.contains_one_of_many(video.title.lower(), values, strip_matches=False):
                playlist.crontab = ""
                playlist.save()
                notification_services.playlist_disabled_due_to_string(playlist=playlist)

        try:
            video.check_and_add_video_to_playlists_based_on_title_matching()
        except:  # noqa: E722 ; pragma: no cover
            log.exception("Failure to check and add video to playlists based on title matching")

        if video_services.should_download_comments(video=video):
            download_provider_video_comments.apply_async(args=[video.pk], countdown=comments_countdown)
            comments_countdown += 26

    for video in videos_existing:
        if playlist.sync_deletions:
            PlaylistItem.objects.filter(playlist=playlist, video=video).delete()
            notification_services.video_removed_from_playlist(video=video, playlist=playlist, removed=True)
        else:
            for pli in playlist.playlistitem_set.filter(video_id=video.pk, missing_from_playlist_on_provider=False):
                pli.missing_from_playlist_on_provider = True
                pli.save()
                notification_services.video_removed_from_playlist(video=video, playlist=playlist, removed=False)

    playlist_scan_history.videos_downloaded = new_videos
    playlist_scan_history.save()

    return True


@shared_task(queue="queue-vidar")
def delete_channel(pk, keep_archived_videos=False, delete_playlists=True):
    channel = Channel.objects.get(pk=pk)
    log.info(f"Deleting {channel=}")
    deleted_videos = 0
    total_videos = channel.videos.count()

    if delete_playlists:
        for playlist in channel.playlists.all():
            playlist_services.delete_playlist(playlist=playlist, delete_videos=True)

    for video in channel.videos.all():
        if (keep_archived_videos and video.file) or video.playlists.exists():
            video.channel = None
            try:
                renamers.video_rename_all_files(video=video)
            except FileStorageBackendHasNoMoveError:
                log.error("Cannot rename video files as storage backend has no move ability")
                break
            continue
        video_services.delete_video(video=video)
        deleted_videos += 1

    channel_services.delete_files(channel=channel)

    channel.delete()
    log.info(f"Deleted {deleted_videos}/{total_videos} videos from channel along with channel itself {channel}")

    if deleted_videos and total_videos and deleted_videos == total_videos:
        channel_services.cleanup_storage(channel=channel)


@shared_task(queue="queue-vidar")
def delete_channel_videos(pk, keep_archived_videos=False):
    channel = Channel.objects.get(pk=pk)
    channel.fully_indexed = False
    channel.fully_indexed_shorts = False
    channel.fully_indexed_livestreams = False
    channel.save()

    log.info(f'Deleting videos from "{channel=}"')
    deleted_videos = 0
    total_videos = channel.videos.count()

    for video in channel.videos.all():
        if video.playlists.exists():
            continue
        if keep_archived_videos and video.file:
            continue
        video_services.delete_video(video=video)
        deleted_videos += 1
    log.info(f"Deleted {deleted_videos}/{total_videos} videos from {channel}")


@shared_task(bind=True, queue="queue-vidar")
def monthly_maintenances(self):

    log.info("Running monthly maintenances")

    signals.pre_monthly_maintenance.send(sender=self.__class__, instance=self)

    if app_settings.MONTHLY_CHANNEL_UPDATE_BANNERS:
        yt_ratelimit = app_settings.CHANNEL_BANNER_RATE_LIMIT
        countdown = 0
        for channel in Channel.objects.indexing_enabled():
            update_channel_banners.apply_async(args=[channel.pk], countdown=countdown)
            countdown += yt_ratelimit

    if app_settings.MONTHLY_CHANNEL_CRONTAB_BALANCING:
        log.info("Balancing long-term channel scans based on upload schedule seen")
        log.debug("{'channel name':>50} {'dslu':>10} {'dbr':>10} {'scanner_crontab':>20} {'new_crontab':>20}")
        for channel in Channel.objects.active().exclude(scanner_crontab=""):

            if channel.scanner_crontab.endswith("*"):
                log.debug(f"{channel.name:>50} crontab set to every day. Not changing.")
                continue

            dslu = channel.days_since_last_upload()
            if not dslu:
                continue
            dbr = channel.average_days_between_upload()

            # If they haven't uploaded in 2 months, set their crontab to twice a month
            if dslu > 2 * 30 or dbr > 30:
                base_common_week_day = statistics_helpers.most_common_date_weekday(queryset=channel.videos)
                common_week_day = helpers.convert_to_next_day_of_week(day_of_week=base_common_week_day)
                new_crontab = crontab_services.generate_weekly(day_of_week=common_week_day)

                log.debug(f"{channel.name:>50} {dslu:>10} {dbr:>10} {channel.scanner_crontab:>20} {new_crontab:>20}")

                channel.scanner_crontab = new_crontab

                channel.save()

    if app_settings.MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT:
        log.info("Checking all videos for correct file paths.")

        try:
            rename_all_archived_video_files()
        except FileStorageBackendHasNoMoveError:
            log.exception("Failure to confirm filenames are correct as File backend does not support move.")

    if app_settings.MONTHLY_CLEAR_DLP_FORMATS:
        dlp_formats_cleared = (
            Video.objects.filter(
                Q(privacy_status_checks__gt=app_settings.PRIVACY_STATUS_CHECK_MAX_CHECK_PER_VIDEO)
                | Q(file="", upload_date__lt=timezone.now().date() - timezone.timedelta(days=6 * 30))
            )
            .exclude(dlp_formats__isnull=True)
            .update(dlp_formats=None)
        )
        log.info(f"{dlp_formats_cleared=} from video.dlp_formats.")

    if app_settings.MONTHLY_ASSIGN_OLDEST_THUMBNAILS_TO_CHANNEL_YEAR_DIRECTORY:
        try:
            oneoffs.assign_oldest_thumbnail_to_channel_year_directories()
        except FileStorageBackendHasNoMoveError:
            log.error("Cannot assign channel directories cover files as storage backend has no move ability")

    signals.post_monthly_maintenance.send(sender=self.__class__, instance=self)


@shared_task(queue="queue-vidar")
def automated_video_quality_upgrades():

    downloaded = 0
    max_automated_downloads = app_settings.AUTOMATED_QUALITY_UPGRADES_PER_TASK_LIMIT

    for channel in Channel.objects.indexing_enabled().filter(allow_library_quality_upgrade=True):
        log.info(f"Scanning {channel=} for video quality upgrades at least {channel.quality=}")

        all_videos_at_selected = True
        channel_wants_best_available = channel.quality == 0

        public_channel_videos = channel.videos.filter(
            privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible
        ).exclude(file="")

        videos_potentially_needing_upgrade = public_channel_videos.exclude(
            Q(quality=channel.quality) | Q(is_short=True) | Q(is_livestream=True) | Q(at_max_quality=True)
        )

        for video in videos_potentially_needing_upgrade:

            if video.is_at_max_quality():
                continue

            if not channel_wants_best_available:
                video_is_already_at_or_above_channel_quality = video.quality >= channel.quality
                if video_is_already_at_or_above_channel_quality:
                    log.debug(f"Skipped {video=} : {video.quality=} >= {channel.quality=}")
                    continue

            log.info(f"Channel Video Upgrading {video=} : quality {video.quality=} >= {channel.quality=}")

            download_provider_video.delay(
                pk=video.pk,
                automated_quality_upgrade=True,
                task_source="Channel Quality Upgrades",
            )
            all_videos_at_selected = False

            downloaded += 1

            if downloaded >= max_automated_downloads:
                log.debug("Max downloads reached, ending.")
                return downloaded

        if all_videos_at_selected:
            # 2024-06-30: A video downloaded with an odd quality that wasn't
            #   considered max and the system downloaded it over and over again.
            channel.allow_library_quality_upgrade = False
            channel.save()

    for playlist in Playlist.objects.filter(hidden=False).exclude(quality__isnull=True):
        log.info(f"Scanning {playlist=} for video quality upgrades at least {playlist.quality=}")

        playlist_wants_best_available = playlist.quality == 0

        for video in playlist.videos.filter(at_max_quality=False).exclude(file=""):

            if video.is_at_max_quality():
                continue

            if not playlist_wants_best_available:
                video_is_already_at_or_above_wanted_quality = video.quality >= playlist.quality
                if video_is_already_at_or_above_wanted_quality:
                    log.debug(f"Skipped {video=} : {video.quality=} >= {playlist.quality=}")
                    continue

            log.info(f"Playlist Video Upgrading {video=} : quality {video.quality=} >= {playlist.quality=}")

            download_provider_video.delay(
                pk=video.pk, automated_quality_upgrade=True, task_source="Playlist Quality Upgrades"
            )

            downloaded += 1
            if downloaded >= max_automated_downloads:
                log.debug("Max downloads reached, ending.")
                return downloaded

        # Allow changing playlist quality while disabled,
        #   but once done upgrading, turn off quality to disabling quality checks.
        if not playlist.crontab:
            playlist.quality = None
            playlist.save()

    return downloaded


@shared_task(
    bind=True,
    queue="queue-vidar",
    autoretry_for=(yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError),
    retry_kwargs={"max_retries": 4},
    default_retry_delay=120,
)
def update_video_details(self, pk, download_file=False, dlp_output=None, mode="manual"):

    video = Video.objects.get(pk=pk)

    log.info(f"Checking status and details of {video=}")

    dl_kwargs = ytdlp_services.get_ytdlp_args(video=video)
    if app_settings.SAVE_INFO_JSON_FILE and video.file:
        dl_kwargs["writeinfojson"] = True

    writeinfojson = "writeinfojson" in dl_kwargs

    if not dlp_output:
        try:
            dlp_output = interactor.video_details(video.url, quiet=True, instance=video, **dl_kwargs)
        except yt_dlp.DownloadError as exc:
            # TODO: If video is blocked in country and we have other proxies, try those somehow?
            if video.apply_privacy_status_based_on_dlp_exception_message(exc):
                log.info(f"Video is {video.privacy_status}, privacy_status updated. Stopping download attempt.")
                video_services.log_update_video_details_called(
                    video=video, mode=mode, commit=True, result="Privacy Status Changed"
                )
                self.update_state(state=states.FAILURE, meta=f"Privacy Status Changed to {video.privacy_status}")
                raise Ignore()
            if "confirm" in str(exc) and "age" in str(exc):
                log.info("Video requires signin confirmation to confirm age. Stopping.")
                video_services.log_update_video_details_called(
                    video=video, mode=mode, commit=True, result="Sign in to confirm age"
                )
                self.update_state(state=states.FAILURE, meta="Sign-In Required")
                raise Ignore()
            if self.request.retries == 3:
                log.info("retrying update_video_details in one hour")
                video_services.log_update_video_details_called(
                    video=video, mode=mode, commit=True, result="4th attempt retry in 1 hour"
                )
                raise self.retry(exc=exc, countdown=60 * 60)
            raise

    if not dlp_output:
        raise ValueError("No output from yt-dlp")

    video_services.log_update_video_details_called(video=video, mode=mode, commit=True, result="Success")

    title = dlp_output["title"].lower()
    if title in ["[private video]", "[deleted video]"]:
        if title == "[private video]":
            video.privacy_status = Video.VideoPrivacyStatuses.PRIVATE
        elif title == "[deleted video]":
            video.privacy_status = Video.VideoPrivacyStatuses.DELETED
        log.info(f"Video is {video.privacy_status}, privacy_status updated.")
        video.last_privacy_status_check = timezone.now()
        video.save()
        return f"Video is {video.privacy_status}"

    video.set_details_from_yt_dlp_response(data=dlp_output)

    if video.quality == 0:
        try:
            video.quality = ytdlp_services.get_highest_quality_from_video_dlp_formats(video.dlp_formats)
            video.quality = ytdlp_services.fix_quality_values(video.quality)
        except (TypeError, ValueError):  # pragma: no cover
            log.exception("Failure to obtain video quality during status check.")

    if video.quality and video.at_max_quality:
        highest_quality = ytdlp_services.get_highest_quality_from_video_dlp_formats(video.dlp_formats)
        video.at_max_quality = video.quality >= highest_quality
        if not video.at_max_quality:
            if "uvd_max_quality_changed" not in video.system_notes:
                video.system_notes["uvd_max_quality_changed"] = []
            video.system_notes["uvd_max_quality_changed"].append(
                {
                    "old_highest": video.quality,
                    "new_highest": highest_quality,
                    "last_checked": timezone.now().isoformat(),
                }
            )

    video.save()

    if not video.file and not download_file:
        log.info("update_video_details expects the video to have its file. Stopping.")
        return "Video has no file"

    if video.privacy_status in Video.VideoPrivacyStatuses_Publicly_Visible:

        if not video.file or not video.file.storage.exists(video.file.path):
            log.info(f"{video.file=} does not exist, requesting replacement. {video=}")
            download_provider_video.delay(pk=video.pk, task_source="update_video_details missing file")

            # return because the downloader will do the remaining work.
            return "Video should have had file but does not. Downloading now."

        if writeinfojson:

            downloaded_file_data = dlp_output["requested_downloads"][0]

            video_services.save_infojson_file(
                video=video,
                downloaded_file_data=downloaded_file_data,
                overwrite_formats=False,
            )

    if not video.thumbnail:
        load_video_thumbnail.apply_async(args=[pk, dlp_output.get("thumbnail")], countdown=30)

    if video_services.should_download_comments(video=video):
        download_provider_video_comments.delay(pk=video.pk)

    try:
        video_services.load_chapters_from_info_json(video=video, info_json_data=dlp_output)
    except:  # noqa: E722 ; pragma: no cover
        log.exception(f"Failure to load chapters on {video=}")

    if app_settings.LOAD_SPONSORBLOCK_DATA_ON_UPDATE_VIDEO_DETAILS:
        age_ago = timezone.now().date() - video.upload_date
        sb_checked_enough = len(video.system_notes.get("sponsorblock-loaded", [])) > 2
        if not sb_checked_enough:
            if age_ago >= timezone.timedelta(days=1):
                load_sponsorblock_data.apply_async(args=[video.id])
        else:
            log.info(f"sponsorblock has been automatically checked more than 2 times. No longer checking. {video=}")

    # ensure files are named properly according to naming settings
    rename_video_files.apply_async(kwargs=dict(pk=video.pk), countdown=5)

    return "Success"


@shared_task(
    bind=True,
    queue="queue-vidar",
    autoretry_for=(
        requests.exceptions.HTTPError,
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    ),
    retry_kwargs={"max_retries": 3},
    retry_backoff=10 * 60,  # 10 minutes
    retry_backoff_max=6 * 60 * 60,  # 6 hours
    retry_jitter=True,
)
def load_sponsorblock_data(self, pk):
    video = Video.objects.get(id=pk)
    try:
        new_sb = video_services.load_live_sponsorblock_video_data_into_duration_skips(video=video)
        return len(new_sb)
    except requests.exceptions.HTTPError as e:
        msg = str(e)
        for code in [500, 502, 503, 504, 521, 522, 523, 524]:
            if f"{code} " in msg:
                log.info(f"{code} failure to sponsorblock")
                self.update_state(state=states.FAILURE, meta=f"{code} failure to sponsorblock")
                # ignore the task so no other state is recorded
                raise Ignore()

        raise


@shared_task(bind=True, queue="queue-vidar")
def daily_maintenances(self):

    log.info("Running daily maintenances")

    signals.pre_daily_maintenance.send(sender=self.__class__, instance=self)

    # Sometimes thumbnails can fail to download during the video download process.
    for video in Video.objects.archived().filter(
        thumbnail="",
        privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible,
    ):
        try:
            data = interactor.video_details(video.url)
            if url := data.get("thumbnail"):
                log.info(f"Setting thumbnail on {video=}")
                video_services.set_thumbnail(video=video, url=url)
        except requests.exceptions.RequestException:
            log.exception("Daily maintenance failure to set thumbnail")

    # When manually adding a video the user has an option to mark the video for deletion.
    # The purpose for this is like downloading music. I download the resulting mp3 to my
    #   phone and then delete it from this system.
    for video in Video.objects.filter(mark_for_deletion=True):
        try:
            video_services.delete_video(video=video)
            log.info(f"Video marked for deletion has been deleted: {video=} {video.mark_for_deletion=}")
        except:  # noqa: E722
            log.exception(f"Failed to delete mark_for_deletion=True {video=}")

    # Ensure channels expecting all videos to have audio, has audio.
    for channel in Channel.objects.filter(convert_videos_to_mp3=True):
        for video in channel.videos.filter(audio="").exclude(file=""):
            log.info(f"Converting channel video to mp3 {video!r}")
            convert_video_to_audio.delay(video.pk)

    # Ensure playlists expecting all videos to have audio, has audio.
    for playlist in Playlist.objects.filter(convert_to_audio=True):
        for video in playlist.videos.filter(audio="").exclude(file=""):
            log.info(f"Converting playlist video to mp3 {video!r}")
            convert_video_to_audio.delay(video.pk)

    qs = Video.objects.filter(convert_to_audio=True, audio="").exclude(file="")
    for video in qs:
        log.info(f"Converting direct video to mp3 {video!r}")
        convert_video_to_audio.delay(video.pk)

    age = timezone.now() - timezone.timedelta(days=14)
    for video in Video.objects.archived().filter(related__isnull=True, date_added_to_system__gte=age):
        video.search_description_for_related_videos()

    for channel in Channel.objects.filter(
        Q(delete_videos_after_days__gt=0) | Q(delete_shorts_after_days__gt=0) | Q(delete_livestreams_after_days__gt=0)
    ):
        if channel.delete_videos_after_days:
            dtr = timezone.now() - timezone.timedelta(days=channel.delete_videos_after_days)
            deletable_videos = channel.videos.filter(
                is_video=True, date_downloaded__lt=dtr, starred__isnull=True
            ).exclude(file="")
            for video in deletable_videos:
                try:
                    video_services.delete_video(video=video, keep_record=True)
                except ValueError:
                    log.exception("Failed to delete video")

        if channel.delete_shorts_after_days:
            dtr = timezone.now() - timezone.timedelta(days=channel.delete_shorts_after_days)
            deletable_videos = channel.videos.filter(
                is_short=True, date_downloaded__lt=dtr, starred__isnull=True
            ).exclude(file="")
            for video in deletable_videos:
                try:
                    video_services.delete_video(video=video, keep_record=True)
                except ValueError:
                    log.exception("Failed to delete video")

        if channel.delete_livestreams_after_days:
            dtr = timezone.now() - timezone.timedelta(days=channel.delete_livestreams_after_days)
            deletable_videos = channel.videos.filter(
                is_livestream=True, date_downloaded__lt=dtr, starred__isnull=True
            ).exclude(file="")
            for video in deletable_videos:
                try:
                    video_services.delete_video(video=video, keep_record=True)
                except ValueError:
                    log.exception("Failed to delete video")

    for channel in Channel.objects.all():
        channel_services.recalculate_video_sort_ordering(channel=channel)

    for channel in Channel.objects.filter(
        Q(delete_videos_after_watching=True)
        | Q(delete_shorts_after_watching=True)
        | Q(delete_livestreams_after_watching=True)
    ):
        channel_videos_base_qs = (
            channel.videos.exclude(file="")
            .annotate(percentage_of_video=F("duration") * 0.9)
            .filter(starred__isnull=True, user_playback_history__seconds__gte=F("percentage_of_video"))
        )

        if channel.delete_videos_after_watching:
            for video in channel_videos_base_qs.filter(is_video=True):
                try:
                    video_services.delete_video(video=video, keep_record=True)
                except ValueError:
                    log.exception("Failed to delete video")

        if channel.delete_shorts_after_watching:
            for short in channel_videos_base_qs.filter(is_short=True):
                try:
                    video_services.delete_video(video=short, keep_record=True)
                except ValueError:
                    log.exception("Failed to delete video")

        if channel.delete_livestreams_after_watching:
            for livestream in channel_videos_base_qs.filter(is_livestream=True):
                try:
                    video_services.delete_video(video=livestream, keep_record=True)
                except ValueError:
                    log.exception("Failed to delete video")

    signals.post_daily_maintenance.send(sender=self.__class__, instance=self)


@shared_task(queue="queue-vidar")
def update_video_statuses_and_details():
    # Check videos still exists on channel
    # NOTE: Update views.update_video_details_queue with same logic.

    log.info("Triggering Video Status Updater tasks")
    checks_video_age_days = app_settings.PRIVACY_STATUS_CHECK_MIN_AGE
    thirty_days_ago = (timezone.now() - timezone.timedelta(days=checks_video_age_days)).date()

    videos_that_are_checkable = (
        Video.objects.archived()
        .filter(
            # privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible
            Q(channel__status=channel_helpers.ChannelStatuses.ACTIVE, channel__check_videos_privacy_status=True)
            | Q(channel__isnull=True),
        )
        .annotate(
            last_checked_null_first=Case(When(last_privacy_status_check__isnull=True, then=1), default=0),
            zero_quality_first=Case(When(quality=0, then=1), default=0),
        )
        .filter(
            privacy_status_checks__lt=app_settings.PRIVACY_STATUS_CHECK_MAX_CHECK_PER_VIDEO,
            inserted__date__lte=thirty_days_ago,
        )
        .order_by("-zero_quality_first", "-last_checked_null_first", "last_privacy_status_check", "upload_date")
    )

    videos_to_check_per_day = math.ceil(videos_that_are_checkable.count() / checks_video_age_days)

    tasks_completed_today = TaskResult.objects.filter(
        task_name="vidar.tasks.update_video_details",
        date_done__date=timezone.localdate(),
    ).count()

    tasks_to_complete_today = videos_to_check_per_day - tasks_completed_today

    # Lowered to 16 hours and set task to run 5am to 9pm
    videos_to_check_per_hour = math.ceil(videos_to_check_per_day / app_settings.PRIVACY_STATUS_CHECK_HOURS_PER_DAY)
    videos_to_check_per_ten_minutes = math.ceil(videos_to_check_per_hour / 6)

    log.info(f"{videos_that_are_checkable.count()=}")
    log.info(
        f"Videos to check settings period:{checks_video_age_days} {videos_to_check_per_day}/day "
        f"{videos_to_check_per_hour}/hr {videos_to_check_per_ten_minutes}/10min"
    )
    log.info(f"Videos to check today {videos_to_check_per_day} - {tasks_completed_today} = {tasks_to_complete_today}")

    qs = Q(last_privacy_status_check__date__lt=thirty_days_ago) | Q(last_privacy_status_check__isnull=True)
    if app_settings.SAVE_INFO_JSON_FILE:
        qs |= Q(info_json="")

    videos_needing_an_update = videos_that_are_checkable.filter(qs)
    log.info(
        f"last_privacy_status_check__date__lt={thirty_days_ago} ({checks_video_age_days=}) "
        f"OR isnull=True = {videos_needing_an_update.count()=}"
    )

    force_check_per_call = app_settings.PRIVACY_STATUS_CHECK_FORCE_CHECK_PER_CALL
    if force_check_per_call:
        log.info(f"Video status updater task forced to check {force_check_per_call} videos on this execution.")
        videos_to_check_per_ten_minutes = force_check_per_call

    if tasks_completed_today >= videos_to_check_per_day and not force_check_per_call:
        log.info("Video status updater ended, max number of videos checked today")
        return

    index = 0
    countdown = 0
    countdown_random_min = 10
    countdown_random_max = 20

    if videos_to_check_per_ten_minutes < 5:
        countdown_random_min = 46
        countdown_random_max = 143

    for video in videos_needing_an_update[:videos_to_check_per_ten_minutes]:
        index += 1

        log.debug(f"{index=} {video.last_privacy_status_check=} {video.privacy_status=} {video.upload_date=} {video=}")

        update_video_details.apply_async(kwargs=dict(pk=video.pk, mode="auto"), countdown=countdown)

        countdown += random.randint(countdown_random_min, countdown_random_max)

    log.info(f"Finished Video Status Updater task, updating {index} videos")


@shared_task(bind=True, queue="queue-vidar")
@celery_helpers.prevent_asynchronous_task_execution(
    lock_key="channel-rename-files-{channel_id}", lock_expiry=2 * 60 * 60
)
def channel_rename_files(self, channel_id, commit=True, remove_empty=True, rename_videos=True):

    channel = Channel.objects.get(pk=channel_id)
    renamers.channel_rename_all_files(
        channel=channel,
        commit=commit,
        remove_empty=remove_empty,
        rename_videos=rename_videos,
    )


@shared_task(bind=True, queue="queue-vidar")
@celery_helpers.prevent_asynchronous_task_execution(lock_key="rename-archived-files", lock_expiry=2 * 60 * 60)
def rename_all_archived_video_files(self, remove_empty=True):

    if not file_helpers.can_file_be_moved(Video.file.field):
        raise FileStorageBackendHasNoMoveError("videos_rename_files called but files cannot be renamed")

    Video.objects.all().update(file_not_found=False)

    for video in Video.objects.archived():

        if video_services.does_file_need_fixing(video=video):
            rename_video_files.delay(
                pk=video.pk,
                remove_empty=remove_empty,
            )

    return True


@shared_task(bind=True, queue="queue-vidar")
def rename_video_files(self, pk, remove_empty=True):

    if not file_helpers.can_file_be_moved(Video.file.field):
        log.info("videos_rename_files called but files cannot be renamed")
        self.update_state(state=states.FAILURE, meta="File storage backend cannot move files")
        raise Ignore()

    changed = False
    video = Video.objects.get(pk=pk)

    if not video.file:
        self.update_state(state=states.FAILURE, meta=f"Renaming video.{pk=} does not have a file.")
        raise Ignore()

    try:
        changed = renamers.video_rename_all_files(
            video=video,
            commit=False,
            remove_empty=remove_empty,
        )
    except FileStorageBackendHasNoMoveError:
        log.exception("Attempting to rename files on storage backend that has no `move` functionality")
        self.update_state(state=states.FAILURE, meta="File storage backend cannot move files")
        raise Ignore()
    except OSError:
        video.file_not_found = True
        changed = True
        raise
    finally:
        if changed:
            video.save()

    return True


@shared_task(bind=True, queue="queue-vidar-processor")
@celery_helpers.prevent_asynchronous_task_execution(lock_key="convert-video-to-mp4-{pk}", lock_expiry=4 * 60 * 60)
def convert_video_to_mp4(self, pk, filepath=None):
    # NOTE: update celery_helpers if you change this task name

    if filepath and not app_settings.SHOULD_CONVERT_FILE_TO_HTML_PLAYABLE_FORMAT(filepath=filepath):
        return filepath

    task_started = timezone.now()

    with transaction.atomic():
        video = Video.objects.select_for_update().get(id=pk)
        video.append_to_latest_download_stats(convert_video_to_mp4_started=timezone.now())

    try:

        redis_services.video_conversion_to_mp4_started(video=video)

        local_filepath = filepath
        if not local_filepath:
            local_filepath, was_remote = app_settings.ENSURE_FILE_IS_LOCAL(file_field=video.file)

        output_filepath = app_settings.CONVERT_FILE_TO_HTML_PLAYABLE_FORMAT(filepath=local_filepath)

        notification_services.convert_to_mp4_complete(
            video=video,
            task_started=task_started,
        )
    finally:

        redis_services.video_conversion_to_mp4_finished(video=video)

    with transaction.atomic():
        video = Video.objects.select_for_update().get(id=pk)
        video.append_to_latest_download_stats(convert_video_to_mp4_finished=timezone.now())

    return str(output_filepath)


@shared_task(queue="queue-vidar")
def trigger_mirror_live_playlists():
    countdown = 0
    for channel in Channel.objects.active().filter(mirror_playlists=True):
        mirror_live_playlist.apply_async(args=[channel.pk], countdown=countdown)

        countdown += 120


@shared_task(bind=True, queue="queue-vidar")
def mirror_live_playlist(self, channel_id):
    channel = Channel.objects.get(pk=channel_id)

    output = interactor.channel_playlists(channel.provider_object_id, instance=channel)

    try:
        live_playlists = output["entries"]
    except (KeyError, TypeError) as exc:
        if self.request.retries < 2:
            raise self.retry(countdown=68, exc=exc)

        self.update_state(state=states.FAILURE, meta="Failure to read channels playlists")
        # ignore the task so no other state is recorded
        raise Ignore()

    log.info(f"{channel=} has {len(live_playlists)} live playlists and {channel.playlists.count()} local playlists")
    countdown = 0

    for live_playlist in live_playlists:
        title = live_playlist["title"]
        ytid = live_playlist["id"]

        if Playlist.objects.filter(Q(provider_object_id=ytid) | Q(provider_object_id_old=ytid)).exists():
            # log.info(f'Exists, skipping: {title=}')
            continue

        crontab = ""
        if channel.mirror_playlists_crontab:

            if channel.mirror_playlists_crontab == crontab_services.CrontabOptions.HOURLY:
                crontab = utils.generate_balanced_crontab_hourly()
            elif channel.mirror_playlists_crontab == crontab_services.CrontabOptions.DAILY:
                crontab = crontab_services.generate_daily(hour=playlist_services.crontab_hours)
            elif channel.mirror_playlists_crontab == crontab_services.CrontabOptions.WEEKLY:
                crontab = crontab_services.generate_weekly(hour=playlist_services.crontab_hours)
            elif channel.mirror_playlists_crontab == crontab_services.CrontabOptions.MONTHLY:
                crontab = crontab_services.generate_monthly(hour=playlist_services.crontab_hours)

        log.info(f"Creating, {title=}")
        playlist = Playlist.objects.create(
            channel=channel,
            provider_object_id=ytid,
            title=title,
            channel_provider_object_id=channel.provider_object_id,
            hidden=channel.mirror_playlists_hidden,
            restrict_to_assigned_channel=channel.mirror_playlists_restrict,
            crontab=crontab,
        )

        sync_playlist_data.apply_async(kwargs=dict(pk=playlist.pk, initial_sync=True), countdown=countdown)
        countdown += 120

        notification_services.playlist_added_from_mirror(
            channel=channel,
            playlist=playlist,
        )


@shared_task(queue="queue-vidar")
def slow_full_archive():

    max_automated_downloads = app_settings.SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT
    total_downloads = 0

    for channel in Channel.objects.active().filter(slow_full_archive=True):

        needs_indexing = (
            (channel.index_videos and not channel.fully_indexed)
            or (channel.index_shorts and not channel.fully_indexed_shorts)
            or (channel.index_livestreams and not channel.fully_indexed_livestreams)
        )

        if needs_indexing:
            fully_index_channel.delay(pk=channel.pk)
            continue

        full_archive_videos_to_process = channel.videos.filter(
            file="", privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible
        )

        if channel.full_archive_cutoff:
            log.debug(f"Full Archive Cutoff: {channel.full_archive_cutoff=}")
            full_archive_videos_to_process = full_archive_videos_to_process.filter(
                upload_date__gte=channel.full_archive_cutoff
            )

        if not full_archive_videos_to_process.exists():
            channel_services.full_archiving_completed(channel=channel)
            notification_services.full_archiving_completed(channel=channel)

        for video in full_archive_videos_to_process.order_by("upload_date"):

            if total_downloads >= max_automated_downloads:
                break

            if video.download_errors.exists():
                log.info(f"Skipping {video=} as its errored while downloading and will be handled later on")
                continue

            if celery_helpers.is_object_locked(obj=video):
                continue

            download_provider_video.delay(
                pk=video.pk,
                task_source="automated_archiver - Channel Slow Full Archive",
                requested_by="Channel Slow Full Archive",
            )

            total_downloads += 1

    return total_downloads
