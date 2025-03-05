from django.utils import timezone

from vidar import app_settings
from vidar.services import video_services


crontab_hours = [14, 15, 16, 17]


def delete_playlist_videos(playlist):

    total_deleted = 0

    for pi in playlist.playlistitem_set.all():

        if not video_services.can_delete(video=pi.video, skip_playlist_ids=playlist.id):
            continue

        keep_record = bool(pi.video.channel_id)

        video_services.delete_video(video=pi.video, keep_record=keep_record)

        total_deleted += 1

    return total_deleted


def recently_scanned(playlist):

    hours = app_settings.PLAYLIST_BLOCK_RESCAN_WINDOW_HOURS

    if not hours:
        return

    ago = timezone.now() - timezone.timedelta(hours=hours)
    return playlist.scan_history.filter(inserted__gte=ago).first()
