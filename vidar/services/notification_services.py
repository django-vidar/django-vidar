import logging
import requests

from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from vidar import app_settings
from vidar.templatetags.vidar_utils import smooth_timedelta


log = logging.getLogger(__name__)


def send_message(message, title=None):
    """
    Gotify message with priority >= 5

        Android push notification
        For information I need to know instantly

    Gotify message with priority < 5

        I see notification on PC, if I happen to be on computer
        I see notification, if I manually open gotify on Android
        For "nice to know" information

    """

    if not app_settings.NOTIFICATIONS_SEND:
        return

    url_base = app_settings.GOTIFY_URL
    if not url_base:
        return

    data = {
        "message": message,
        "priority": app_settings.GOTIFY_PRIORITY,
    }

    if title:
        if pt := app_settings.GOTIFY_TITLE_PREFIX:
            title = f"{pt}{title}"
        data["title"] = title

    token = app_settings.GOTIFY_TOKEN
    verify = app_settings.GOTIFY_URL_VERIFY

    try:
        return requests.post(f"{url_base}/message?token={token}", json=data, verify=verify)
    except requests.exceptions.RequestException:
        log.exception("Failed to send gotify notification")


def video_downloaded(video):

    if not app_settings.NOTIFICATIONS_VIDEO_DOWNLOADED:
        return

    if video.channel and not video.channel.send_download_notification:
        return

    latest_download = video.get_latest_download_stats()

    task_source = latest_download.get("task_source")

    quality = "C"
    if video.quality == 0:
        quality = "BV"
    elif video.at_max_quality:
        quality = "AMQ"

    file_size = video.file_size
    if file_size:
        try:
            file_size = filesizeformat(file_size)
        except:  # noqa: E722 ; pragma: no cover
            pass

    def isoformat_or_now(value):
        return timezone.datetime.fromisoformat(value) or timezone.now()

    def calculate_timer(started, finished):
        timer = None
        if started and finished:
            started = isoformat_or_now(started)
            finished = isoformat_or_now(finished)
            timer = finished - started
        return started, finished, timer

    convert_to_audio_started, convert_to_audio_finished, convert_to_audio_timer = calculate_timer(
        started=latest_download.get("convert_video_to_audio_started"),
        finished=latest_download.get("convert_video_to_audio_finished"),
    )

    convert_to_mp4_started, convert_to_mp4_finished, convert_to_mp4_timer = calculate_timer(
        started=latest_download.get("convert_video_to_mp4_started"),
        finished=latest_download.get("convert_video_to_mp4_finished"),
    )

    processing_started, processing_finished, processing_timer = calculate_timer(
        started=latest_download.get("processing_started"),
        finished=latest_download.get("processing_finished"),
    )

    download_started, download_finished, download_timer = calculate_timer(
        started=latest_download.get("download_started"),
        finished=latest_download.get("download_finished"),
    )

    try:
        video_duration = video.duration_as_timedelta()
    except TypeError:  # pragma: no cover
        video_duration = None

    msg_output = [
        f"{video.upload_date:%Y-%m-%d} - {video}\n{smooth_timedelta(video_duration)} long",
        f"Filesize: {file_size}",
    ]

    if download_timer:
        msg_output.append(f"Download Timer: {smooth_timedelta(download_timer)}")
    if convert_to_audio_timer:
        msg_output.append(f"Convert Audio: {smooth_timedelta(convert_to_audio_timer)}")
    if convert_to_mp4_timer:
        msg_output.append(f"Convert Video: {smooth_timedelta(convert_to_mp4_timer)}")
    if processing_timer:
        msg_output.append(f"Processing: {smooth_timedelta(processing_timer)}")

    if task_source:
        msg_output.append(f"Task Call Source: {task_source}")

    title = f"{quality}:{video.get_quality_display()}"
    if video.channel:
        title = f"{video.channel} @ {title}"

    return send_message(
        message="\n".join(msg_output),
        title=title,
    )


def video_removed_from_playlist(video, playlist, removed=False):
    if not app_settings.NOTIFICATIONS_VIDEO_REMOVED_FROM_PLAYLIST:
        return
    return send_message(
        message=f"Video {video!r} removed from playlist {playlist!r}\nLocally Removed: {removed}",
        title="Video Removed From Playlist",
    )


def video_added_to_playlist(video, playlist):
    if not app_settings.NOTIFICATIONS_VIDEO_ADDED_TO_PLAYLIST:
        return
    return send_message(
        message=f"Video {video!r} added to playlist {playlist!r}",
        title="Video Added To Playlist",
    )


def video_readded_to_playlist(video, playlist):
    if not app_settings.NOTIFICATIONS_VIDEO_READDED_TO_PLAYLIST:
        return
    return send_message(
        message=f"Video {video!r} re-added to playlist {playlist!r}",
        title="Video Re-Added To Playlist",
    )


def full_indexing_complete(channel, target, new_videos_count, total_videos_count):
    if not app_settings.NOTIFICATIONS_FULL_INDEXING_COMPLETE:
        return
    return send_message(
        message=f"Full Indexing {target} Completed\n\n"
        f"New Videos: {new_videos_count}\n"
        f"Total Videos: {total_videos_count}",
        title=f"{channel}",
    )


def full_archiving_started(channel):
    if not app_settings.NOTIFICATIONS_FULL_ARCHIVING_STARTED:
        return
    return send_message(
        message=f"Full Archive Enabled for {channel}",
        title=f"{channel}",
    )


def full_archiving_completed(channel):
    if not app_settings.NOTIFICATIONS_FULL_ARCHIVING_COMPLETED:
        return
    return send_message(
        message=f"Full Archive Completed for {channel}",
        title=f"{channel}",
    )


def playlist_disabled_due_to_string(playlist):
    if not app_settings.NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_STRING:
        return
    return send_message(
        message=f"Playlist Disabled: {playlist}, due to string found in video title",
        title="Playlist Disabled",
    )


def playlist_disabled_due_to_errors(playlist):
    if not app_settings.NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_ERRORS:
        return
    return send_message(
        message=f"Playlist Disabled: {playlist}, due to not being found {playlist.not_found_failures} times",
        title="Playlist Disabled",
    )


def playlist_added_from_mirror(channel, playlist):
    if not app_settings.NOTIFICATIONS_PLAYLIST_ADDED_BY_MIRROR:
        return
    return send_message(
        message=f"Channel playlist mirroring added: {playlist}",
        title=f"{channel} mirroring added playlist",
    )


def no_videos_archived_today():
    if not app_settings.NOTIFICATIONS_NO_VIDEOS_ARCHIVED_TODAY:
        return
    return send_message(
        title="No Archived Videos Today",
        message="Alerting, no videos were archived today. Is everything ok?",
    )


def convert_to_mp4_complete(video, task_started):
    if not app_settings.NOTIFICATIONS_CONVERT_TO_MP4_COMPLETED:
        return
    return send_message(
        title="Video Directly Converted to MP4",
        message=f"Finished converting video from source format into mp4\n\n{video}\n\n"
        f"Task Call Timer: {timezone.now() - task_started}\n",
    )


def channel_status_changed(channel):
    if not app_settings.NOTIFICATIONS_CHANNEL_STATUS_CHANGED:
        return
    return send_message(
        title="Channel Status Change",
        message=f"{channel=} status changed to {channel.status}",
    )
