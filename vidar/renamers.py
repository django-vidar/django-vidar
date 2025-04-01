import logging
import pathlib

from vidar.exceptions import FileStorageBackendHasNoMoveError
from vidar.helpers import channel_helpers, extrafile_helpers, file_helpers, video_helpers
from vidar.services import channel_services, schema_services, video_services
from vidar.storages import vidar_storage


log = logging.getLogger(__name__)


def channel_rename_thumbnail_file(channel, commit=True):
    """Renames the given Channel.thumbnail to update its path and filename."""
    if not channel.thumbnail:
        log.info(f"{channel.thumbnail=} is empty, cannot rename thumbnail that does not exist.")
        return False

    old_storage_path = pathlib.PurePosixPath(channel.thumbnail.name)

    ext = channel.thumbnail.name.rsplit(".", 1)[-1]

    channel_directory = schema_services.channel_directory_name(channel=channel)
    _, new_storage_path = channel_services.generate_filepaths_for_storage(
        channel=channel,
        field=channel.thumbnail,
        filename=f"{channel_directory}.{ext}",
        upload_to=channel_helpers.upload_to_thumbnail,
    )
    if old_storage_path == new_storage_path:
        log.info(f"{channel.pk=} storage paths already match, {channel.thumbnail.name} does not need renaming.")
        return False
    log.info(f"{channel.pk=} renaming {channel.thumbnail.name} {commit=}")
    log.debug(f"{old_storage_path=}")
    log.debug(f"{new_storage_path=}")
    channel.thumbnail.storage.move(old_storage_path, new_storage_path)
    channel.thumbnail.name = str(new_storage_path)
    if commit:
        channel.save()
    return True


def channel_rename_banner_file(channel, commit=True):
    """Renames the given Channel.banner to update its path and filename."""
    if not channel.banner:
        log.info(f"{channel.banner=} is empty, cannot rename banner that does not exist.")
        return False

    old_storage_path = pathlib.PurePosixPath(channel.banner.name)

    ext = channel.banner.name.rsplit(".", 1)[-1]

    _, new_storage_path = channel_services.generate_filepaths_for_storage(
        channel=channel,
        field=channel.banner,
        filename=f"banner.{ext}",
        upload_to=channel_helpers.upload_to_banner,
    )
    if old_storage_path == new_storage_path:
        log.info(f"{channel.pk=} storage paths already match, {channel.banner.name} does not need renaming.")
        return False
    log.info(f"{channel.pk=} renaming {channel.banner.name} {commit=}")
    log.debug(f"{old_storage_path=}")
    log.debug(f"{new_storage_path=}")
    channel.banner.storage.move(old_storage_path, new_storage_path)
    channel.banner.name = str(new_storage_path)
    if commit:
        channel.save()
    return True


def channel_rename_tvart_file(channel, commit=True):
    """Renames the given Channel.tvart to update its path and filename."""
    if not channel.tvart:
        log.info(f"{channel.tvart=} is empty, cannot rename tvart that does not exist.")
        return False

    old_storage_path = pathlib.PurePosixPath(channel.tvart.name)

    ext = channel.tvart.name.rsplit(".", 1)[-1]

    _, new_storage_path = channel_services.generate_filepaths_for_storage(
        channel=channel,
        field=channel.tvart,
        filename=f"tvart.{ext}",
        upload_to=channel_helpers.upload_to_tvart,
    )
    if old_storage_path == new_storage_path:
        log.info(f"{channel.pk=} storage paths already match, {channel.tvart.name} does not need renaming.")
        return False
    log.info(f"{channel.pk=} renaming {channel.tvart.name} {commit=}")
    log.debug(f"{old_storage_path=}")
    log.debug(f"{new_storage_path=}")
    channel.tvart.storage.move(old_storage_path, new_storage_path)
    channel.tvart.name = str(new_storage_path)
    if commit:
        channel.save()
    return True


def channel_rename_all_videos(videos, commit=True, remove_empty=True):
    videos_changed = 0
    for video in videos.exclude(file=""):
        if video_rename_all_files(video=video, commit=commit, remove_empty=remove_empty):
            videos_changed += 1
    return videos_changed


def channel_rename_all_files(channel, commit=True, remove_empty=True, rename_videos=False):
    log.info(f"Checking channel files are named correctly. {commit=} {channel=}")

    # TODO: Make this work for remote storage systems too.
    if not file_helpers.can_file_be_moved(channel.thumbnail):
        raise FileStorageBackendHasNoMoveError("channel files storage backend has no ability to move")

    pre_exising_file_path = None
    if remove_empty:
        an_existing_file = channel.thumbnail or channel.tvart or channel.banner
        if an_existing_file:
            pre_exising_file_path = an_existing_file.name

    changed = []
    if channel_rename_thumbnail_file(channel, commit):
        changed.append("thumbnail")
    if channel_rename_tvart_file(channel, commit):
        changed.append("tvart")
    if channel_rename_banner_file(channel, commit):
        changed.append("banner")
    if rename_videos:
        if videos_changed_counter := channel_rename_all_videos(
            videos=channel.videos.exclude(file=""), commit=commit, remove_empty=remove_empty
        ):
            changed.append(f"{videos_changed_counter} videos")

    if changed:
        log.info(f"{changed} were renamed")

        if remove_empty and pre_exising_file_path:
            pathway = pathlib.Path(pre_exising_file_path).parent
            if pathway != pathlib.Path():
                try:
                    vidar_storage.delete(str(pathway))
                except OSError as e:
                    if "not empty" not in str(e):
                        raise

    return changed


def video_rename_local_file(video, commit=True):
    """Renames the given Video.file to update its path and filename."""
    if not video.file:
        log.info(f"{video.file=} is empty, cannot rename file that does not exist.")
        return False

    old_storage_path = pathlib.PurePosixPath(video.file.name)

    ext = video.file.name.rsplit(".", 1)[-1]

    _, new_storage_path = video_services.generate_filepaths_for_storage(video=video, ext=ext)

    if old_storage_path == new_storage_path:
        log.info(f"{video.pk=} storage paths already match, {video.file.name} does not need renaming.")
        return False
    log.info(f"{video.pk=} renaming {commit=} {video.file.name}")
    log.debug(f"{old_storage_path=}")
    log.debug(f"{new_storage_path=}")
    video.file.storage.move(old_storage_path, new_storage_path)
    video.file.name = str(new_storage_path)
    if commit:
        video.save()
    return True


def video_rename_local_info_json(video, commit=True):
    """Renames the given Video.info_json to update its path and filename."""
    if not video.info_json:
        log.info(f"{video.info_json=} is empty, cannot rename info_json that does not exist.")
        return False

    old_storage_path = pathlib.PurePosixPath(video.info_json.name)

    _, new_storage_path = video_services.generate_filepaths_for_storage(
        video=video, ext="info.json", upload_to=video_helpers.upload_to_infojson
    )
    if old_storage_path == new_storage_path:
        log.info(f"{video.pk=} storage paths already match, {video.info_json.name} does not need renaming.")
        return False
    log.info(f"{video.pk=} renaming {commit=} {video.info_json.name}")
    log.debug(f"{old_storage_path=}")
    log.debug(f"{new_storage_path=}")
    video.info_json.storage.move(old_storage_path, new_storage_path)
    video.info_json.name = str(new_storage_path)
    if commit:
        video.save()
    return True


def video_rename_thumbnail_file(video, commit=True):
    """Renames the given Video.thumbnail to update its path and filename."""
    if not video.thumbnail:
        log.info(f"{video.thumbnail=} is empty, cannot rename thumbnail that does not exist.")
        return False

    old_storage_path = pathlib.PurePosixPath(video.thumbnail.name)

    ext = video.thumbnail.name.rsplit(".", 1)[-1]

    _, new_storage_path = video_services.generate_filepaths_for_storage(
        video=video, ext=ext, upload_to=video_helpers.upload_to_thumbnail
    )
    if old_storage_path == new_storage_path:
        log.info(f"{video.pk=} storage paths already match, {video.thumbnail.name} does not need renaming.")
        return False
    log.info(f"{video.pk=} renaming {commit=} {video.thumbnail.name}")
    log.debug(f"{old_storage_path=}")
    log.debug(f"{new_storage_path=}")
    video.thumbnail.storage.move(old_storage_path, new_storage_path)
    video.thumbnail.name = str(new_storage_path)
    if commit:
        video.save()
    return True


def video_rename_extra_file(video, extra_file, commit=True):

    old_storage_path = pathlib.Path(extra_file.file.name)
    new_storage_path = pathlib.Path(
        extrafile_helpers.extrafile_file_upload_to(
            instance=extra_file,
            filename=old_storage_path.name,
        )
    )

    if old_storage_path == new_storage_path:
        log.info(f"{video.pk=} storage paths already match, extra_{extra_file.pk=} does not need renaming.")
        return False

    log.info(f"{video.pk=} renaming extra_{extra_file.pk=} {commit=}")
    log.debug(f"{old_storage_path=}")
    log.debug(f"{new_storage_path=}")

    extra_file.file.storage.move(old_storage_path, new_storage_path)
    extra_file.file.name = new_storage_path
    if commit:
        extra_file.save()
    return True


def video_rename_all_files(video, commit=True, remove_empty=True):
    log.info(f"Checking video files are named correctly. {commit=} {video=}")

    if not file_helpers.can_file_be_moved(video.file):
        raise FileStorageBackendHasNoMoveError("video files storage backend has no ability to move")

    pre_exising_file_path = None
    if remove_empty:
        an_existing_file = video.file or video.info_json or video.thumbnail
        if an_existing_file:
            pre_exising_file_path = an_existing_file.name

    changed = []
    if video_rename_local_file(video=video, commit=commit):
        changed.append("file")
    if video_rename_local_info_json(video=video, commit=commit):
        changed.append("info_json")
    if video_rename_thumbnail_file(video=video, commit=commit):
        changed.append("thumbnail")

    for extra_file in video.extra_files.all():
        video_rename_extra_file(video=video, extra_file=extra_file, commit=commit)

    if changed:
        log.info(f"{changed} were renamed.")

        if remove_empty and pre_exising_file_path:
            pathway = pathlib.Path(pre_exising_file_path).parent
            if pathway != pathlib.Path():
                try:
                    vidar_storage.delete(str(pathway))
                except OSError as e:
                    if "not empty" not in str(e):
                        raise

    return changed
