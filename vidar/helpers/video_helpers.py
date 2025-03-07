import logging
import pathlib

from django.utils import timezone

from vidar import app_settings
from vidar.services import schema_services


log = logging.getLogger(__name__)


def get_video_upload_to_directory(instance):
    if instance.channel_id:
        channel_dir = schema_services.channel_directory_name(channel=instance.channel)
        path = pathlib.PurePosixPath(channel_dir)

        if instance.channel.store_videos_by_year_separation:
            if instance.upload_date:
                year = instance.upload_date.year
            else:
                year = timezone.now().year
            path /= str(year)

        if instance.channel.store_videos_in_separate_directories:
            path /= schema_services.video_directory_name(video=instance)

    else:
        path = pathlib.PurePosixPath("public")

        if instance.upload_date:
            year = instance.upload_date.year
        else:
            year = timezone.now().year

        path /= str(year)

    return path


def video_upload_to_side_by_side(instance, filename):

    path = get_video_upload_to_directory(instance)

    path /= filename

    return path


def upload_to_file(instance, filename):
    return video_upload_to_side_by_side(instance, filename)


def upload_to_infojson(instance, filename):
    return video_upload_to_side_by_side(instance, filename)


def upload_to_audio(instance, filename):
    root = None
    if instance.channel_id:
        root = schema_services.channel_directory_name(channel=instance.channel)
    if not root:
        root = "public"

    path = pathlib.PurePosixPath(root)

    path /= "audio"

    if instance.upload_date:
        year = instance.upload_date.year
    else:
        year = timezone.localdate().year

    path /= str(year)
    path /= filename

    return path


def upload_to_thumbnail(instance, filename):
    return video_upload_to_side_by_side(instance, filename)


def default_quality():
    return app_settings.DEFAULT_QUALITY
