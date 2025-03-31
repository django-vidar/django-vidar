import logging
import pathlib

from django.core.files.base import ContentFile
from django.utils import timezone

from vidar import app_settings, exceptions, storages
from vidar.helpers import channel_helpers
from vidar.services import image_services, notification_services, schema_services


log = logging.getLogger(__name__)


def set_thumbnail(channel, url, save=True):
    log.debug(f"Setting thumbnail with {url}")
    contents, final_ext = image_services.download_and_convert_to_jpg(url)
    directory_name = schema_services.channel_directory_name(channel=channel)
    final_filename = f"{directory_name}.{final_ext}"
    channel.thumbnail.save(final_filename, ContentFile(contents), save=save)


def set_banner(channel, url, save=True):
    log.debug(f"Setting banner with {url}")
    contents, final_ext = image_services.download_and_convert_to_jpg(url)
    channel.banner.save("banner.jpg", ContentFile(contents), save=save)


def set_tvart(channel, url, save=True):
    log.debug(f"Setting tvart with {url}")
    contents, final_ext = image_services.download_and_convert_to_jpg(url)
    channel.tvart.save("tvart.jpg", ContentFile(contents), save=save)


def generate_filepaths_for_storage(channel, field, filename, upload_to):
    valid_new_filename = storages.vidar_storage.get_valid_name(filename)
    new_storage_path = upload_to(channel, valid_new_filename)
    new_full_filepath = pathlib.Path(field.storage.path(new_storage_path))
    return new_full_filepath, new_storage_path


def cleanup_storage(channel, dry_run=False):
    # Clean up cover.jpg and extras if exists.
    log.info(f"Clean up channel storage directory, {channel}")

    try:
        channel_directory_name = schema_services.channel_directory_name(channel=channel).strip()
    except exceptions.DirectorySchemaInvalidError:
        log.info("Skipping channel directory cleanup, name is invalid")
        return

    if channel_directory_name in ("/", "\\"):
        log.info("Skipping channel directory cleanup, it may remove other data")
        return

    channel_directory_path_str = storages.vidar_storage.path(channel_directory_name)
    channel_directory_path = pathlib.Path(channel_directory_path_str)

    log.debug(f"{channel_directory_path_str=}")
    log.debug(f"{channel_directory_path=}")

    if channel_directory_path == storages.vidar_storage.path(""):
        log.info("Skipping channel directory cleanup, directory path returned same as primary storage path.")
        return

    log.info(f"Cleaning up directory {channel_directory_path=}.")

    if not channel_directory_path.exists():
        log.info("Channel directory does not exist")
        return

    log.info("Channel directory exists, deleting remaining data.")

    if not dry_run:
        storages.vidar_storage.delete(channel_directory_path)

    return True


def recalculate_video_sort_ordering(channel):
    index = 0
    for video in channel.videos.order_by("upload_date", "inserted", "pk"):
        index += 1

        video.sort_ordering = index
        video.save(update_fields=["sort_ordering"])


def generate_sort_name(name: str):

    if not name or not name.lower().startswith("the ") or len(name) < 4:
        return ""

    the_format = name[:4]
    name_without_the = name[4:]

    return f"{name_without_the}, {the_format}".strip()


def set_channel_details_from_ytdlp(channel, response):
    channel.name = response["title"]
    channel.description = response["description"]
    channel.active = True
    channel.uploader_id = response["uploader_id"]

    if not channel.sort_name:
        channel.sort_name = generate_sort_name(channel.name)

    channel.save()


def no_longer_active(channel, status="Banned", commit=True):
    channel.status = status

    channel.scanner_crontab = ""
    channel.index_videos = False
    channel.index_shorts = False
    channel.index_livestreams = False
    channel.full_archive = False
    channel.full_archive_after = None
    channel.mirror_playlists = False
    channel.swap_index_videos_after = None
    channel.swap_index_shorts_after = None
    channel.swap_index_livestreams_after = None

    if commit:
        channel.save()

    channel.playlists.exclude(crontab="").update(crontab="")


def apply_exception_status(channel, exc):
    exc_msg = str(exc).lower()

    status_changed = False
    old_status = channel.status

    if "account" in exc_msg and "terminated" in exc_msg:
        no_longer_active(channel=channel, status=channel_helpers.ChannelStatuses.TERMINATED)
        status_changed = True

    elif "violated" in exc_msg and "community" in exc_msg:
        no_longer_active(channel=channel, status=channel_helpers.ChannelStatuses.REMOVED)
        status_changed = True

    elif "channel" in exc_msg and "does not exist" in exc_msg:
        no_longer_active(channel=channel, status=channel_helpers.ChannelStatuses.NO_LONGER_EXISTS)
        status_changed = True

    if status_changed:
        log.info(f"Channel status changed from {old_status=} to {channel.status=}")
        notification_services.channel_status_changed(channel=channel)
        return True


def full_archiving_completed(channel):

    channel.full_archive = False
    channel.slow_full_archive = False
    channel.send_download_notification = True
    channel.fully_indexed = True
    channel.save()


def recently_scanned(channel):

    hours = channel.block_rescan_window_in_hours

    if not hours:
        hours = app_settings.CHANNEL_BLOCK_RESCAN_WINDOW_HOURS

    if not hours:
        return

    ago = timezone.now() - timezone.timedelta(hours=hours)
    return channel.scan_history.filter(inserted__gte=ago).first()


def delete_files(channel):

    # Prepare necessary variables to remove channel directory after removing the files.
    deletable_directories = {}
    for x in [channel.thumbnail, channel.banner, channel.tvart]:
        if x:
            if x.storage not in deletable_directories:
                deletable_directories[x.storage] = set()
            parent_dir = pathlib.Path(x.path).parent
            deletable_directories[x.storage].add(parent_dir)
            x.delete(save=False)

    for storage, directories in deletable_directories.items():
        for directory in directories:
            storage.delete(directory)
