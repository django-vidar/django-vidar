import json
import logging

from django.conf import settings
from django.utils import timezone

import redis

from vidar import app_settings


log = logging.getLogger(__name__)


_CALL_COUNTER = {}


def _is_permitted_cached(name):
    # I discovered using cached_property on AppSettings means a callable database value will not change the
    #   value after the initial call to the property until the server restarts. I wanted the REDIS_ values to be
    #   able to change on the fly and that was not possible. I also discovered the cached_property made
    #   writing tests for redis_services impossible. So I came up with this. It will cache the value by name and
    #   it will recheck the value every 100 calls.
    global _CALL_COUNTER

    if name not in _CALL_COUNTER:
        _CALL_COUNTER[name] = {"count": 1, "previous": None}

    _CALL_COUNTER[name]["count"] += 1

    if _CALL_COUNTER[name]["previous"] is None:
        _CALL_COUNTER[name]["previous"] = bool(getattr(app_settings, name))
    elif _CALL_COUNTER[name]["count"] % 100 == 0:
        _CALL_COUNTER[name]["previous"] = bool(getattr(app_settings, name))
    return _CALL_COUNTER[name]["previous"]


def _reset_call_counters():
    global _CALL_COUNTER
    _CALL_COUNTER = {}


def check_redis_message_allow(name):
    if isinstance(name, bool):
        if not name:
            return
    elif not _is_permitted_cached(name):
        return
    return _is_permitted_cached("REDIS_ENABLED")


class RedisMessaging:
    """collection of methods to interact with redis"""

    NAME_SPACE = "vidar:"

    def __init__(self):
        self.conn = None
        if url := getattr(settings, "VIDAR_REDIS_URL", None):
            self.conn = redis.from_url(url)
        elif url := getattr(settings, "CELERY_BROKER_URL", None):  # pragma: no cover
            self.conn = redis.from_url(url)

    CHANNELS = [
        "vidar",
    ]

    def set_direct_message(self, key, message, expire=True):
        """write new message to redis"""
        output = self.conn.execute_command("SET", key, json.dumps(message))

        if expire:
            if isinstance(expire, bool):
                secs = 15
            else:
                secs = expire
            self.conn.execute_command("EXPIRE", key, secs)

        return output

    def set_message(self, key, message, expire=True):
        """write new message to redis"""
        return self.set_direct_message(self.NAME_SPACE + key, message=message, expire=expire)

    def get_message(self, key):
        """get message dict from redis"""
        return self.get_direct_message(self.NAME_SPACE + key)

    def get_direct_message(self, key):
        """get message dict from redis"""
        reply = self.conn.execute_command("GET", key)
        if reply:
            json_str = json.loads(reply)
        else:
            json_str = {"status": False}

        return json_str

    def get_all_messages(self):
        messages = []
        for key in self.conn.scan_iter(f"{self.NAME_SPACE}*"):
            key = key.decode("utf8")
            reply = self.get_direct_message(key)
            if reply:
                messages.append(reply)

        return messages

    def get_app_messages(self, app):
        messages = []
        for key in self.conn.scan_iter(f"{self.NAME_SPACE}{app}*"):
            key = key.decode("utf8")
            reply = self.get_direct_message(key)
            if reply:
                messages.append(reply)

        return messages

    def flushdb(self):
        return self.conn.execute_command("FLUSHDB")


def channel_indexing(msg, channel, **kwargs):

    if not check_redis_message_allow(app_settings.REDIS_CHANNEL_INDEXING):
        return

    if msg.startswith("[download]"):
        mess_dict = {
            "status": "message:vidar",
            "level": "info",
            "title": "Processing Channel Index",
            "message": f"{channel}: {msg}",
            "url": channel.get_absolute_url(),
            "url_text": "Channel",
        }
        RedisMessaging().set_message(f"vidar:channel-index:{channel.pk}", mess_dict)
        return True


def playlist_indexing(msg, playlist, **kwargs):

    if not check_redis_message_allow(app_settings.REDIS_PLAYLIST_INDEXING):
        return

    if msg.startswith("[download]"):
        mess_dict = {
            "status": "message:vidar",
            "level": "info",
            "title": "Processing Playlist Index",
            "message": f"Playlist: {playlist}: {msg}",
            "url": playlist.get_absolute_url(),
            "url_text": "Playlist",
        }
        RedisMessaging().set_message(f"vidar:playlist-index:{playlist.pk}", mess_dict)
        return True


def video_conversion_to_mp4_started(video):

    if not check_redis_message_allow(app_settings.REDIS_VIDEO_CONVERSION_STARTED):
        return

    mess_dict = {
        "status": "message:vidar",
        "level": "info",
        "title": "Processing Video Conversion",
        "message": f"Video MKV Conversion Started {timezone.localtime()}: {video}",
        "url": video.get_absolute_url(),
        "url_text": "Video",
    }
    RedisMessaging().set_message(f"vidar:video-mkv-conversion:{video.pk}", mess_dict, expire=90 * 60)

    return True


def video_conversion_to_mp4_finished(video):

    if not check_redis_message_allow(app_settings.REDIS_VIDEO_CONVERSION_FINISHED):
        return

    mess_dict = {
        "status": "message:vidar",
        "level": "info",
        "title": "Processing Video Conversion",
        "message": f"Video MKV Conversion Finished {timezone.localtime()}: {video}",
        "url": video.get_absolute_url(),
        "url_text": "Video",
    }
    RedisMessaging().set_message(f"vidar:video-mkv-conversion:{video.pk}", mess_dict)

    return True


def progress_hook_download_status(d, raise_exceptions=False, **kwargs):

    if not check_redis_message_allow("REDIS_VIDEO_DOWNLOADING"):
        return

    yid = d.get("info_dict", {}).get("id")

    if not yid:
        return

    eta = timezone.timedelta(seconds=d.get("eta") or 0)
    speed = d.get("_speed_str", "")

    mess_dict = {
        "status": "message:vidar",
        "level": "info",
        "title": "Processing Archives",
        "message": f"{d['info_dict']['title']}: {d['status']} {d['_percent_str']} @ {speed} - ETA:{eta}",
        "url": kwargs.get("url"),
        "url_text": kwargs.get("url_text", "Video"),
    }
    RedisMessaging().set_message(f"vidar:{yid}", mess_dict)

    return True
