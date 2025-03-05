import datetime
import logging
import requests

from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from vidar import app_settings


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

    data = {
        'message': message,
        'priority': app_settings.GOTIFY_PRIORTY,
    }

    if title:
        data['title'] = title

    url_base = app_settings.GOTIFY_URL
    token = app_settings.GOTIFY_TOKEN
    verify = app_settings.GOTIFY_URL_VERIFY

    try:
        return requests.post(f'{url_base}/message?token={token}', json=data, verify=verify)
    except requests.exceptions.RequestException:
        log.exception('Failed to send gotify notification')


def video_downloaded(video, task_source, download_started, download_finished, processing_started, processing_finished):

    if not app_settings.NOTIFICATIONS_VIDEO_DOWNLOADED:
        return

    if video.channel and not video.channel.send_download_notification:
        return

    quality = "C"
    if video.quality == 0:
        quality = 'BV'
    elif video.at_max_quality:
        quality = 'AMQ'

    file_size = video.file_size
    if file_size:
        try:
            file_size = filesizeformat(file_size)
        except:  # noqa: E722
            pass

    def isoformat_or_now(value):
        if not value:
            return timezone.now()
        if isinstance(value, datetime.datetime):
            return value
        return timezone.datetime.fromisoformat(value)

    download_started = isoformat_or_now(download_started)
    download_finished = isoformat_or_now(download_finished)
    processing_started = isoformat_or_now(processing_started)
    processing_finished = isoformat_or_now(processing_finished)

    convert_to_audio_started = video.system_notes.get('convert_video_to_audio_started')
    convert_to_audio_finished = video.system_notes.get('convert_video_to_audio_finished')
    convert_to_audio_timer = None
    if convert_to_audio_started and convert_to_audio_finished:
        convert_to_audio_started = isoformat_or_now(convert_to_audio_started)
        convert_to_audio_finished = isoformat_or_now(convert_to_audio_finished)
        convert_to_audio_timer = convert_to_audio_finished - convert_to_audio_started

    convert_to_mp4_started = video.system_notes.get('convert_video_to_mp4_started')
    convert_to_mp4_finished = video.system_notes.get('convert_video_to_mp4_finished')
    convert_to_mp4_timer = None
    if convert_to_mp4_started and convert_to_mp4_finished:
        convert_to_mp4_started = isoformat_or_now(convert_to_mp4_started)
        convert_to_mp4_finished = isoformat_or_now(convert_to_mp4_finished)
        convert_to_mp4_timer = convert_to_mp4_finished - convert_to_mp4_started

    try:
        video_duration = video.duration_as_timedelta()
    except:  # noqa: E722
        video_duration = None

    msg_output = [
        f"{video.upload_date:%Y-%m-%d} - {video}\n{video_duration}",
        f"Filesize: {file_size}",
        f"Download Timer: {download_finished - download_started}",
    ]

    if convert_to_audio_timer:
        msg_output.append(f"Convert Audio: {convert_to_audio_timer}")
    if convert_to_mp4_timer:
        msg_output.append(f"Convert Video: {convert_to_mp4_timer}")

    msg_output.extend([
        f"Processing Timer: {processing_finished - processing_started}",
        f"Task Call Source: {task_source}",
    ])
    return send_message(
        message="\n".join(msg_output),
        title=f"YTDL: {video.channel} @ {quality}:{video.get_quality_display()}",
    )


def video_removed_from_playlist(video, playlist, removed=False):
    if not app_settings.NOTIFICATIONS_VIDEO_REMOVED_FROM_PLAYLIST:
        return
    return send_message(
        message=f'Video {video!r} removed from playlist {playlist!r}\nLocally Removed: {removed}',
        title='YTDL: Video Removed From Playlist',
    )


def video_added_to_playlist(video, playlist):
    if not app_settings.NOTIFICATIONS_VIDEO_ADDED_TO_PLAYLIST:
        return
    return send_message(
        message=f'Video {video!r} added to playlist {playlist!r}',
        title='YTDL: Video Added To Playlist',
    )


def video_readded_to_playlist(video, playlist):
    if not app_settings.NOTIFICATIONS_VIDEO_READDED_TO_PLAYLIST:
        return
    return send_message(
        message=f'Video {video!r} re-added to playlist {playlist!r}',
        title='YTDL: Video Re-Added To Playlist',
    )


def full_indexing_complete(channel, target, new_videos_count, total_videos_count):
    if not app_settings.NOTIFICATIONS_FULL_INDEXING_COMPLETE:
        return
    return send_message(
        message=f"Full Indexing {target} Completed\n\n"
                f"New Videos: {new_videos_count}\n"
                f"Total Videos: {total_videos_count}",
        title=f"YTDL: {channel}"
    )


def full_archiving_started(channel):
    if not app_settings.NOTIFICATIONS_FULL_ARCHIVING_STARTED:
        return
    return send_message(
        message=f"Full Archive Enabled for {channel}",
        title=f"YTDL: {channel}",
    )


def full_archiving_completed(channel):
    if not app_settings.NOTIFICATIONS_FULL_ARCHIVING_COMPLETED:
        return
    return send_message(
        message=f"Full Archive Completed for {channel}",
        title=f"YTDL: {channel}",
    )


def playlist_disabled_due_to_string(playlist):
    if not app_settings.NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_STRING:
        return
    return send_message(
        message=f'Playlist Disabled: {playlist}, due to string found in video title',
        title='YTDL: Playlist Disabled',
    )


def playlist_disabled_due_to_errors(playlist):
    if not app_settings.NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_ERRORS:
        return
    return send_message(
        message=f'Playlist Disabled: {playlist}, due to not being found {playlist.not_found_failures} times',
        title='YTDL: Playlist Disabled',
    )


def playlist_added_from_mirror(channel, playlist):
    if not app_settings.NOTIFICATIONS_PLAYLIST_ADDED_BY_MIRROR:
        return
    return send_message(
        message=f'Channel playlist mirroring added: {playlist}',
        title=f'YTDL: {channel} mirroring added playlist',
    )


def no_videos_archived_today():
    if not app_settings.NOTIFICATIONS_NO_VIDEOS_ARCHIVED_TODAY:
        return
    return send_message(
        title='YTDL: No Archived Videos Today',
        message='Alerting, no videos were archived today. Is everything ok?',
    )


def convert_to_mp4_complete(video, task_started):
    if not app_settings.NOTIFICATIONS_CONVERT_TO_MP4_COMPLETED:
        return
    return send_message(
        title='YTDL: Video Directly Converted to MP4',
        message=f'Finished converting video from source format into mp4\n\n{video}\n\n'
                f'Task Call Timer: {timezone.now() - task_started}\n',
    )


def channel_status_changed(channel):
    if not app_settings.NOTIFICATIONS_CHANNEL_STATUS_CHANGED:
        return
    return send_message(
        title='YTDL: Channel Status Change',
        message=f'{channel=} status changed to {channel.status}',
    )
