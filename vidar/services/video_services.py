import json
import logging
import pathlib

from django.core.files.base import ContentFile
from django.db.models import F
from django.utils import timezone

from vidar import app_settings, models, utils
from vidar.exceptions import DownloadedInfoJsonFileNotFoundError
from vidar.helpers import video_helpers
from vidar.services import image_services, schema_services
from vidar.storages import vidar_storage


log = logging.getLogger(__name__)


def _correct_format_data_in_infojson_data(video, infojson_data):
    """info.json files downloaded without the file will set different format data.

    format_id, format_note, and format are only saved during
        download of the video file itself. So set those settings within info.json

    """
    infojson_data["format_id"] = video.format_id
    infojson_data["format_note"] = video.format_note

    format_ids = video.format_id.split("+", 1)
    output_format = []
    for f in infojson_data["formats"]:
        if f["format_id"] in format_ids:
            if fn := f.get("format_note"):
                output_format.append(fn)
    final_format = "+".join(output_format)
    infojson_data["format"] = final_format

    return infojson_data


def _load_downloaded_infojson_file(downloaded_file_data):

    filepath = pathlib.Path(downloaded_file_data["filepath"])

    infojson_filepath = filepath.parent / downloaded_file_data["infojson_filename"]

    try:
        with infojson_filepath.open("rb") as fo:
            return json.load(fo)
    except FileNotFoundError:
        raise DownloadedInfoJsonFileNotFoundError(infojson_filepath)

    finally:

        try:
            infojson_filepath.unlink()
        except OSError:
            log.exception(f"Failure to delete .info.json file {infojson_filepath=}")


def save_infojson_file(video, downloaded_file_data, save=True, overwrite_formats=True):
    if not app_settings.SAVE_INFO_JSON_FILE:
        return

    infojson_data = _load_downloaded_infojson_file(downloaded_file_data=downloaded_file_data)

    if video.format_id and overwrite_formats:
        # Video already has a format, ensure infojson has that format.
        infojson_data = _correct_format_data_in_infojson_data(video=video, infojson_data=infojson_data)

    if video.info_json:
        try:
            video.info_json.delete()
        except OSError:
            log.exception("Failed to delete existing info_json before replacement.")

    infojson_final_filename = schema_services.video_file_name(video=video, ext="info.json")
    video.info_json.save(infojson_final_filename, ContentFile(json.dumps(infojson_data)), save=save)


def generate_filepaths_for_storage(
    video, ext, filename=None, upload_to=video_helpers.upload_to_file, ensure_new_dir_exists=False
):
    final_filename = filename or schema_services.video_file_name(video=video, ext=ext)
    valid_new_filename = vidar_storage.get_valid_name(final_filename)
    new_storage_path = upload_to(video, valid_new_filename)
    new_full_filepath = pathlib.Path(vidar_storage.path(new_storage_path))
    if ensure_new_dir_exists:
        new_full_filepath.parent.mkdir(parents=True, exist_ok=True)
    return new_full_filepath, new_storage_path


def set_thumbnail(video, url, save=True):
    contents, final_ext = image_services.download_and_convert_to_jpg(url)

    final_filename = schema_services.video_file_name(video=video, ext=final_ext)

    video.thumbnail.save(final_filename, ContentFile(contents), save=False)

    if save:
        video.save(update_fields=["thumbnail"])


def does_file_need_fixing(video):
    if not video.file:
        return False
    ext = video.file.name.rsplit(".", 1)[-1]
    new_full_filepath, new_storage_path = generate_filepaths_for_storage(video=video, ext=ext)
    return video.file.name != str(new_storage_path)


def should_force_download_based_on_requirements_requested(video):
    log.info(f"Checking if video should be forced to download based on requirements, {video=}")

    if video.force_download:
        log.info(f"Force downloading {video=}")
        return True

    if video.channel:

        if video.channel.force_next_downloads:
            log.info(f"Channel forcing download {video=}")
            video.channel.force_next_downloads = F("force_next_downloads") - 1
            video.channel.save()
            video.channel.refresh_from_db()
            return True

        if utils.contains_one_of_many(video.title.lower(), video.channel.title_forces.lower().splitlines()):
            log.info(f"Permitted due to channel.title_forces {video=}")
            return True

    return False


def should_force_download_based_on_requirements_check(video):
    log.info(f"Checking if video should be forced to download based on requirements, {video=}")

    if video.force_download:
        log.info(f"Force downloading {video=}")
        return True

    if video.channel:

        if video.channel.force_next_downloads:
            log.info(f"Channel forcing download {video=}")
            return True

        if utils.contains_one_of_many(video.title.lower(), video.channel.title_forces.lower().splitlines()):
            log.info(f"Permitted due to channel.title_forces {video=}")
            return True

    return False


def is_permitted_to_download_check(video):
    """Check download requirements based on channel settings"""
    channel = video.channel
    log.info(f"Checking if permitted to download based on channel requirements, {channel=}")

    if not channel:
        log.info("No channel assigned, defaults to True")
        return True

    if channel.force_next_downloads:
        log.info("Permitted due to force_next_downloads")
        return True

    if utils.contains_one_of_many(video.title.lower(), channel.title_forces.lower().splitlines()):
        log.info("Permitted due to title_forces")
        return True

    if channel.skip_next_downloads:
        log.info("Not permitted due to skip_next_downloads")
        return False

    if utils.contains_one_of_many(video.title.lower(), channel.title_skips.lower().splitlines()):
        log.info("Not permitted due to title_skips")
        return False

    if video.is_video:
        if utils.is_duration_outside_min_max(
            duration=video.duration, minimum=channel.duration_minimum_videos, maximum=channel.duration_maximum_videos
        ):
            return False

    if video.is_livestream:
        if utils.is_duration_outside_min_max(
            duration=video.duration,
            minimum=channel.duration_minimum_livestreams,
            maximum=channel.duration_maximum_livestreams,
        ):
            return False

    return True


def is_permitted_to_download_requested(video):
    """Check and apply download requirements based on channel settings"""
    channel = video.channel
    log.info(f"Requested if permitted to download based on channel requirements, {channel=}")

    if not channel:
        log.info("No channel set, default is to permit")
        return True

    if channel.force_next_downloads:
        log.info(f"Channel has {channel.force_next_downloads=}, permitting")
        channel.force_next_downloads = F("force_next_downloads") - 1
        channel.save()
        channel.refresh_from_db()
        return True

    if utils.contains_one_of_many(video.title.lower(), video.channel.title_forces.lower().splitlines()):
        log.info("Channel.title_forces matched video.title, permitting")
        return True

    if channel.skip_next_downloads:
        log.info(f"Channel has {channel.skip_next_downloads=}, skipping")
        channel.skip_next_downloads = F("skip_next_downloads") - 1
        channel.save()
        channel.refresh_from_db()
        return False

    if utils.contains_one_of_many(video.title.lower(), channel.title_skips.lower().splitlines()):
        log.info("Channel.title_skips matched video.title, skipping")
        return False

    if video.is_video:
        minimum = channel.duration_minimum_videos
        maximum = channel.duration_maximum_videos
        if utils.is_duration_outside_min_max(duration=video.duration, minimum=minimum, maximum=maximum):
            log.info(f"{video.duration=} outside range {minimum, maximum}, skipping")
            return False

    if video.is_livestream:
        minimum = channel.duration_minimum_livestreams
        maximum = channel.duration_maximum_livestreams
        if utils.is_duration_outside_min_max(duration=video.duration, minimum=minimum, maximum=maximum):
            log.info(f"{video.duration=} outside range {minimum, maximum}, skipping")
            return False

    return True


def reset_fields(video, commit=True):
    video.quality = None
    video.at_max_quality = False
    video.starred = None
    video.format_note = ""
    video.format_id = ""
    video.date_downloaded = None
    video.watched = None
    video.force_download = False
    video.download_kwargs = None
    video.fps = 0
    video.width = 0
    video.height = 0
    video.file_size = None
    video.privacy_status = "Public"
    video.last_privacy_status_check = None
    video.system_notes = dict()
    video.requested_max_quality = False
    video.download_comments_on_index = False
    video.download_all_comments = False
    video.convert_to_audio = False

    if commit:
        video.save()


def can_delete(video, skip_playlist_ids=None):

    if video.prevent_deletion:
        log.info(f"{video.id=} prevented from deletion. prevent_deletion=True")
        return False

    if video.starred:
        log.info(f"{video.id=} prevented from deletion. video is starred")
        return False

    if skip_playlist_ids:
        if isinstance(skip_playlist_ids, int):
            skip_playlist_ids = [skip_playlist_ids]
        if video.playlists.exclude(pk__in=skip_playlist_ids, playlistitem__download=True).exists():
            log.info("Cannot delete video attached to playlist(s)")
            return False
    else:
        if video.playlistitem_set.filter(download=True).exists():
            log.info("Cannot delete video attached to playlist(s) while download is True")
            return False

    # 2024-05-02: I delete videos after download all the time,
    #   especially ones i realize i don't care for.
    # if video.channel:
    #     if video.channel.download_videos:
    #         return False

    return True


def delete_files(video):

    # Prepare necessary variables to remove video directory after removing the files.
    deletable_directories = set()
    for x in [video.file, video.thumbnail, video.audio, video.info_json]:
        if x and x.storage.exists(x.name):
            parent_dir = pathlib.Path(x.path).parent
            deletable_directories.add(parent_dir)
            x.delete(save=False)

    for ef in video.extra_files.all():
        x = ef.file
        if x and x.storage.exists(x.name):
            parent_dir = pathlib.Path(x.path).parent
            deletable_directories.add(parent_dir)
            x.delete(save=False)

    for directory in deletable_directories:
        try:
            directory.rmdir()
        except (OSError, TypeError) as exc:
            if "not empty" not in str(exc):
                log.exception("Failure to delete video directory")
            else:
                log.info(f"Failure to delete video {directory=}")


def delete_video(video, keep_record=False):

    delete_files(video=video)

    if not keep_record:

        if video.channel and video.privacy_status == models.Video.VideoPrivacyStatuses.PUBLIC:
            video.channel.fully_indexed = False
            video.channel.fully_indexed_shorts = False
            video.channel.fully_indexed_livestreams = False
            video.channel.save()

        return video.delete(deletion_permitted=True)

    else:

        reset_fields(video=video, commit=True)

    return True


def load_live_sponsorblock_video_data_into_duration_skips(video, categories=None, user=None, save_highlight=True):

    newly_created = []

    sb_data = utils.get_sponsorblock_video_data(video.provider_object_id, categories=categories)

    for row in sb_data:
        category = row["category"]
        start, end = row["segment"]
        start, end = int(start), int(end)
        if category == "poi_highlight":

            if save_highlight:
                video.highlights.update_or_create(
                    source="POI",
                    point=start,
                    note="SponsorBlock Highlight",
                )

        else:

            existing_skips = video.duration_skips.values_list("start", "end")
            output = utils.do_new_start_end_points_overlap_existing(start, end, existing_skips)
            if not output:
                obj, c = video.duration_skips.get_or_create(
                    sb_uuid=row["UUID"],
                    defaults=dict(
                        start=start,
                        end=end,
                        sb_category=category,
                        sb_votes=int(row["votes"]),
                        sb_data=row,
                        user=user,
                    ),
                )
                if c:
                    newly_created.append(obj)

    if "sponsorblock-loaded" not in video.system_notes:
        video.system_notes["sponsorblock-loaded"] = []

    video.system_notes["sponsorblock-loaded"].append(timezone.now().isoformat())
    video.save()

    return newly_created


def load_chapters_from_info_json(video, reload=False, info_json_data=None):

    if not info_json_data:

        if not video.info_json:
            log.info(f"Video has no info_json to load chapters from. {video=}")
            return

        with video.info_json.open() as fo:
            info_json_data = json.load(fo)

    chapters = info_json_data.get("chapters")

    if not chapters:
        log.info(f"Video has no chapters in info_json {video=}")
        return

    qs = video.highlights.filter(source=models.Highlight.Sources.CHAPTERS)

    if not reload and qs.count() >= len(chapters):
        log.info("Video has chapters and no reload was requested.")
        return

    qs.delete()

    for chapter in chapters:
        video.highlights.create(
            source=models.Highlight.Sources.CHAPTERS,
            note=chapter["title"],
            point=int(chapter["start_time"]),
            end_point=int(chapter["end_time"]),
        )

    log.info(f"Added {len(chapters)} chapters to {video=}")

    return len(chapters)


def load_thumbnail_from_info_json(video, info_json_data=None):

    if not info_json_data:
        if not video.info_json:
            log.info(f"Video has no info_json to load thumbnail from. {video=}")
            return

        with video.info_json.open() as fo:
            info_json_data = json.load(fo)

    if thumbnail_url := info_json_data.get("thumbnail"):
        try:
            set_thumbnail(video=video, url=thumbnail_url)
            return True
        except:  # noqa: E722
            log.exception(f"Thumbnail failure {thumbnail_url=} on {video.channel=}")


def is_too_old(video):
    if not video.upload_date:
        return True
    # If upload date is before Dec 15 2005, it's bad.
    return video.upload_date <= timezone.now().replace(year=2005, month=12, day=14).date()


def log_update_video_details_called(video, mode="auto", commit=True, result=None):

    if mode != "auto":
        return

    if "update_video_details_automated" not in video.system_notes:
        video.system_notes["update_video_details_automated"] = {}

    log.info(f"Video has been auto checked {len(video.system_notes['update_video_details_automated'])} times.")

    video.system_notes["update_video_details_automated"][timezone.now().isoformat()] = result
    video.privacy_status_checks = len(video.system_notes["update_video_details_automated"])

    if commit:
        video.save(update_fields=["system_notes", "privacy_status_checks"])


def should_download_comments(video):
    if video.download_comments_on_index or video.download_all_comments:
        return True
    if video.channel:
        if video.channel.download_comments_with_video or video.channel.download_comments_during_scan:
            return True
    return video.playlists.filter(download_comments_on_index=True).exists()


def should_convert_to_audio(video):
    if video.convert_to_audio:
        return True
    if video.channel and video.channel.convert_videos_to_mp3:
        return True
    return video.playlists.filter(convert_to_audio=True).exists()


def should_convert_to_mp4(video, filepath):
    if isinstance(filepath, pathlib.PurePath):
        filepath = filepath.name
    return filepath.endswith(".mkv")


def is_blocked(provider_object_id):
    if models.VideoBlocked.objects.filter(provider_object_id=provider_object_id).exists():
        log.debug(f'Video id "{provider_object_id}" is blocked.')
        return True


def block(video: models.Video):
    obj, _ = models.VideoBlocked.objects.get_or_create(
        provider_object_id=video.provider_object_id,
        channel_id=video.channel_provider_object_id,
        title=video.title,
    )
    return obj


def unblock(provider_object_id):
    return models.VideoBlocked.objects.filter(provider_object_id=provider_object_id).delete()


def quality_to_download(video: models.Video, extras: (set, list, tuple) = None):
    """Returns the necessary quality required based on Channel and Playlist preferences."""

    # Always download shorts at max quality
    if video.is_short and app_settings.SHORTS_FORCE_MAX_QUALITY:
        return 0

    wanted = set()

    if extras and isinstance(extras, (set, list, tuple)):
        wanted.update(extras)

    if video.quality:
        wanted.add(video.quality)
    if video.channel:
        wanted.add(video.channel.quality)
    for playlist in video.playlists.exclude(quality__isnull=True):
        wanted.add(playlist.quality)

    if 0 in wanted:
        return 0

    qualities = set()
    for x in wanted:
        try:
            qualities.add(int(x))
        except TypeError:
            log.debug(f"Failure to convert value to int: {x} ")

    # If the video, channel, or playlist had a quality selected, use that before applying default.
    #   Some channels we might only care for 720 but the system default could be set to 1080.
    if qualities:
        return max(qualities)

    return app_settings.DEFAULT_QUALITY


def should_use_cookies(video: models.Video, attempt=0):

    if attempt and not app_settings.COOKIES_APPLY_ON_RETRIES:
        return False

    if app_settings.COOKIES_ALWAYS_REQUIRED:
        return True

    return video.needs_cookies or video.channel and video.channel.needs_cookies


def get_cookies(video: models.Video):

    if system_cookies := app_settings.COOKIES:
        return system_cookies

    if cookies_file := app_settings.COOKIES_FILE:
        if hasattr(cookies_file, "open"):
            return cookies_file.open().read()
        with open(cookies_file) as fo:
            return fo.read()

    if app_settings.COOKIES_ALWAYS_REQUIRED:
        raise ValueError("VIDAR_COOKIES_ALWAYS_REQUIRED=True but no cookies were returned.")
