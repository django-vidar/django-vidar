import os
import pathlib
import tempfile

from django.core.files.storage import FileSystemStorage

import moviepy

from vidar import app_settings


def is_field_using_local_storage(field):
    return isinstance(field.storage, FileSystemStorage) or getattr(field.storage, "vidar_is_local", None)


def can_file_be_moved(field):
    return hasattr(field.storage, "move")


def ensure_file_is_local(file_field):
    """In the event we move to S3/Remote based storage, we need a way to
    copy the remote file into a local location.

    returns path, was_remote
    """

    if is_field_using_local_storage(file_field):
        return file_field.path, False

    _, ext = file_field.name.rsplit(".", 1)

    fd, path = tempfile.mkstemp(dir=app_settings.MEDIA_CACHE, suffix=f".{ext}")

    with os.fdopen(fd, "wb") as fw, file_field.open("rb") as fo:
        fw.write(fo.read())

    return path, True


def should_convert_to_html_playable_format(filepath):
    if isinstance(filepath, pathlib.PurePath):
        filepath = filepath.name
    return filepath.endswith(".mkv")


def convert_to_html_playable_format(filepath):

    _, output_filepath = tempfile.mkstemp(dir=app_settings.MEDIA_CACHE, suffix=".mp4")

    clip = moviepy.VideoFileClip(filepath)
    clip.write_videofile(str(output_filepath))

    return output_filepath
