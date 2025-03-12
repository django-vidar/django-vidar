import logging
import time
from functools import partial

import yt_dlp

from vidar import app_settings, utils
from vidar.services import redis_services, ytdlp_services


log = logging.getLogger(__name__)


def _clean_kwargs(kwargs):
    # These are passed for the user_initializer, otherwise they need to be stripped.
    if "instance" in kwargs:
        kwargs.pop("instance")
    if "action" in kwargs:
        kwargs.pop("action")


def get_ytdlp(kwargs):

    if user_initializer_func := app_settings.YTDLP_INITIALIZER:
        ret = user_initializer_func(**kwargs)
        _clean_kwargs(kwargs)

    else:
        _clean_kwargs(kwargs)

        if "proxy" not in kwargs:
            if proxy := utils.get_proxy():
                log.info(f"get_ytdlp: Setting kwargs.setdefault proxy to {proxy}")
                kwargs.setdefault("proxy", proxy)

        ret = yt_dlp.YoutubeDL(kwargs)
    log.debug(kwargs)
    return ret


class YTDLPInteractor:

    @staticmethod
    def playlist_details(url, ignore_errors=True, detailed_video_data=False, **kwargs):

        kwargs.setdefault("default_search", "ytsearch")
        kwargs.setdefault("quiet", False)
        kwargs.setdefault("skip_download", True)
        kwargs.setdefault("extract_flat", not detailed_video_data)
        kwargs.setdefault("ignoreerrors", ignore_errors)
        kwargs.setdefault("noplaylist", True)
        kwargs.setdefault("check_formats", "none")
        kwargs["action"] = "playlist_details"
        with get_ytdlp(kwargs) as ydl:
            return ydl.extract_info(url, download=False)

    @staticmethod
    def video_download(url, **kwargs):

        local_url = kwargs.pop("local_url", None)
        hook_partial = partial(redis_services.progress_hook_download_status, url=local_url)

        kwargs.setdefault("progress_hooks", [hook_partial])
        kwargs.setdefault("quiet", True)

        # kwargs.setdefault('postprocessors', [
        #     {
        #         'key': 'SponsorBlock',
        #         'categories': ['all']
        #     },
        #     {
        #         'key': 'ModifyChapters',
        #         'remove_sponsor_segments': ['all']
        #     }
        # ])

        kwargs["action"] = "video_download"

        with get_ytdlp(kwargs) as ydl:
            return ydl.extract_info(url, download=True), kwargs

    @staticmethod
    def video_details(url, **kwargs):
        kwargs.setdefault("default_search", "ytsearch")
        kwargs.setdefault("quiet", False)
        kwargs.setdefault("skip_download", True)
        kwargs.setdefault("extract_flat", True)
        kwargs["action"] = "video_details"
        with get_ytdlp(kwargs) as ydl:
            return ydl.extract_info(url)

    @staticmethod
    def video_comments(
        url,
        all_comments=False,
        total_max_comments=None,
        max_parents=None,
        max_replies=None,
        max_replies_per_thread=None,
        sorting=None,
        **kwargs,
    ):

        kwargs.setdefault("download", False)
        kwargs.setdefault("getcomments", True)
        kwargs.setdefault("skip_download", False)

        if not all_comments and not kwargs.get("extractor_args"):

            extractor_args = ytdlp_services.get_comment_downloader_extractor_args(
                total_max_comments=total_max_comments,
                max_parents=max_parents,
                max_replies=max_replies,
                max_replies_per_thread=max_replies_per_thread,
                sorting=sorting,
            )

            kwargs.update(extractor_args)
        kwargs["action"] = "video_comments"
        with get_ytdlp(kwargs) as ydl:
            return ydl.extract_info(url, download=False)

    @staticmethod
    def channel_details(url, **kwargs):
        kwargs.setdefault("default_search", "ytsearch")
        kwargs.setdefault("quiet", False)
        kwargs.setdefault("skip_download", True)
        # kwargs.setdefault('extract_flat', True)
        kwargs.setdefault("playlist_items", "1,0")
        kwargs["action"] = "channel_details"
        with get_ytdlp(kwargs) as ydl:
            return ydl.extract_info(url, download=False)

    @staticmethod
    def channel_videos(url, limit=None, **kwargs):
        kwargs.setdefault("default_search", "ytsearch")
        kwargs.setdefault("quiet", False)
        kwargs.setdefault("skip_download", True)
        kwargs.setdefault("extract_flat", False)
        kwargs.setdefault("ignoreerrors", True)
        # kwargs.setdefault('sleep_interval_requests', 2)
        kwargs["action"] = "channel_videos"

        if limit:
            kwargs["playlistend"] = limit

        with get_ytdlp(kwargs) as ydl:
            return ydl.extract_info(url, download=False)

    @staticmethod
    def channel_playlists(youtube_id, **kwargs):
        kwargs.setdefault("quiet", False)
        kwargs.setdefault("skip_download", True)
        kwargs.setdefault("extract_flat", True)
        kwargs.setdefault("ignoreerrors", True)
        kwargs["action"] = "channel_playlists"
        with get_ytdlp(kwargs) as ydl:
            return ydl.extract_info(
                f"https://www.youtube.com/channel/{youtube_id}" f"/playlists?view=1&sort=dd&shelf_id=0", download=False
            )


def interactor_channel_videos_with_retry(url, sleep=5, **dl_kwargs):

    for x in range(2):

        chan = YTDLPInteractor.channel_videos(url=url, **dl_kwargs)

        if not chan or not chan["entries"]:
            time.sleep(sleep)
            continue

        return chan

    else:
        log.info(f"interactor_channel_videos_with_retry failed for {url}")

    return


class OutputCapturer:
    """
    from functools import partial

    def print_messages(msg, **kwargs):
        # kwargs will contain at a minimum the following keys:
        #   _type: 'info', 'debug', 'error', or 'warning'
        #   any parameters passed to the partial callback initialization

        print(msg, kwargs)

    interactor_capture = partial(OutputCapturer, callback_func=print_messages)

    ytdlp_kwargs = {
        'logger': interactor_capture(),
    }

    """

    def __init__(self, callback_func=None, **kwargs):
        self.callback_func = callback_func
        self.kwargs = kwargs or {}

    def msg_received(self, msg, _type):
        if callable(self.callback_func):
            self.callback_func(msg, _type=_type, **self.kwargs)

    def info(self, msg):
        self.msg_received(msg, "info")

    def debug(self, msg):
        self.msg_received(msg, "debug")

    def error(self, msg):
        self.msg_received(msg, "error")

    def warning(self, msg):
        self.msg_received(msg, "warning")
