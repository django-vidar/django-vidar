import json
import logging

from django.conf import settings
from django.utils import timezone

import redis

from vidar import app_settings


log = logging.getLogger(__name__)


class RedisMessaging:
    """collection of methods to interact with redis"""

    NAME_SPACE = "django:"

    def __init__(self):
        self.conn = redis.Redis(
            host=settings.CELERY_BROKER_HOSTNAME,
            port=settings.CELERY_BROKER_PORT,
            db=settings.CELERY_BROKER_DB
        )

    CHANNELS = [
        "vidar",
    ]

    def set_direct_message(self, key, message, expire=True):
        """write new message to redis"""
        self.conn.execute_command("SET", key, json.dumps(message))

        if expire:
            if isinstance(expire, bool):
                secs = 15
            else:
                secs = expire
            self.conn.execute_command("EXPIRE", key, secs)

    def set_message(self, key, message, expire=True):
        """write new message to redis"""
        self.set_direct_message(self.NAME_SPACE + key, message=message, expire=expire)

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

    def list_items(self, query):
        """list all matches"""
        reply = self.conn.execute_command(
            "KEYS", self.NAME_SPACE + query + "*"
        )
        all_matches = [i.decode().lstrip(self.NAME_SPACE) for i in reply]
        all_results = []
        for match in all_matches:
            json_str = self.get_message(match)
            all_results.append(json_str)

        return all_results

    def del_message(self, key):
        """delete key from redis"""
        response = self.conn.execute_command("DEL", self.NAME_SPACE + key)
        return response

    def get_lock(self, lock_key):
        """handle lock for task management"""
        redis_lock = self.conn.lock(self.NAME_SPACE + lock_key)
        return redis_lock

    def get_progress(self):
        """get a list of all progress messages"""
        all_messages = []
        for channel in self.CHANNELS:
            key = "message:" + channel
            reply = self.conn.execute_command(
                "GET", self.NAME_SPACE + key
            )
            if reply:
                json_str = json.loads(reply)
                all_messages.append(json_str)

        return all_messages

    def get_all_messages(self):
        messages = []
        for key in self.conn.scan_iter(f'{self.NAME_SPACE}*'):
            key = key.decode('utf8')
            reply = self.get_direct_message(key)
            if reply:
                messages.append(reply)

        return messages

    def get_app_messages(self, app):
        messages = []
        for key in self.conn.scan_iter(f'{self.NAME_SPACE}{app}*'):
            key = key.decode('utf8')
            reply = self.get_direct_message(key)
            if reply:
                messages.append(reply)

        return messages

    def exists(self, key):
        return self.exists_direct(self.NAME_SPACE + key)

    def exists_direct(self, key):
        return self.conn.exists(key)


def channel_indexing(msg, **kwargs):
    if msg.startswith('[download]'):
        mess_dict = {
            "status": "message:vidar",
            "level": "info",
            "title": "Processing Channel Index",
            "message": f"{kwargs['channel']}: {msg}",
            "url": kwargs['channel'].get_absolute_url(),
            "url_text": "Channel",
        }
        RedisMessaging().set_message(f'vidar:channel-index:{kwargs["channel"].pk}', mess_dict)


def playlist_indexing(msg, **kwargs):
    if msg.startswith('[download]'):
        mess_dict = {
            "status": "message:vidar",
            "level": "info",
            "title": "Processing Playlist Index",
            "message": f"Playlist: {kwargs['playlist']}: {msg}",
            "url": kwargs['playlist'].get_absolute_url(),
            "url_text": 'Playlist',
        }
        RedisMessaging().set_message(f'vidar:playlist-index:{kwargs["playlist"].pk}', mess_dict)


def video_conversion_to_mp4_started(video):
    mess_dict = {
        "status": "message:vidar",
        "level": "info",
        "title": "Processing Video Conversion",
        "message": f"Video MKV Conversion Started {timezone.localtime()}: {video}",
        "url": video.get_absolute_url(),
        "url_text": "Video",
    }
    RedisMessaging().set_message(f'vidar:video-mkv-conversion:{video.pk}', mess_dict, expire=90 * 60)


def video_conversion_to_mp4_finished(video):
    mess_dict = {
        "status": "message:vidar",
        "level": "info",
        "title": "Processing Video Conversion",
        "message": f"Video MKV Conversion Finished {timezone.localtime()}: {video}",
        "url": video.get_absolute_url(),
        "url_text": "Video",
    }
    RedisMessaging().set_message(f'vidar:video-mkv-conversion:{video.pk}', mess_dict)


def progress_hook_download_status(d, raise_exceptions=False, **kwargs):

    if not app_settings.REDIS_UPDATE_DOWNLOAD_MESSAGE:
        return

    try:
        yid = d.get('info_dict', {}).get('id')

        if not yid:
            return

        eta = timezone.timedelta(seconds=d.get('eta') or 0)
        speed = d.get('_speed_str', '')

        mess_dict = {
            "status": "message:vidar",
            "level": "info",
            "title": "Processing Archives",
            "message": f"{d['info_dict']['title']}: {d['status']} {d['_percent_str']} @ {speed} - ETA:{eta}",
            "url": kwargs.get('url'),
            "url_text": kwargs.get('url_text', 'Video'),
        }
        RedisMessaging().set_message(f'vidar:{yid}', mess_dict)

    except:  # noqa: E722
        log.exception('Failed to format progress_hook data')
        if raise_exceptions:
            raise
