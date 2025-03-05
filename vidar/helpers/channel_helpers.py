import logging
import pathlib

from django.core.exceptions import ValidationError
from django.db import models

from vidar.services import schema_services


log = logging.getLogger(__name__)


def upload_to_banner(*args, **kwargs):
    return _channel_thumbnails_upload_to(*args, **kwargs)


def upload_to_thumbnail(*args, **kwargs):
    return _channel_thumbnails_upload_to(*args, **kwargs)


def upload_to_tvart(*args, **kwargs):
    return _channel_thumbnails_upload_to(*args, **kwargs)


def _channel_thumbnails_upload_to(instance, filename):
    return pathlib.PurePosixPath(schema_services.channel_directory_name(channel=instance)) / filename


def watched_percentage_minimum(value):
    if value < 1:
        raise ValidationError(
            "%(value)s is below 1",
            params={"value": value},
        )


def watched_percentage_maximum(value):
    if value > 100:
        raise ValidationError(
            "%(value)s is above 100",
            params={"value": value},
        )


class ChannelStatuses(models.TextChoices):
    ACTIVE = 'Active'
    BANNED = 'Banned'
    DELETED = 'Deleted'
    NO_LONGER_EXISTS = 'No Longer Exists'
    REMOVED = 'Removed'
    TERMINATED = 'Terminated'
