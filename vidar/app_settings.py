from django.conf import settings
from django.utils.module_loading import import_string


def get_setting(name, dflt):
    getter = getattr(
        settings,
        "VIDAR_SETTING_GETTER",
        lambda name, dflt: getattr(settings, name, dflt),
    )
    getter = import_callable(getter)
    return getter(name, dflt)


def import_callable(path_or_callable):
    if not hasattr(path_or_callable, "__call__"):
        ret = import_string(path_or_callable)
    else:
        ret = path_or_callable
    return ret


class AppSettings(object):
    def __init__(self, prefix):
        self.prefix = prefix

    def _setting(self, name, default):
        return get_setting(self.prefix + name, default)

    def _django_setting(self, name, default):
        return getattr(settings, self.prefix + name, default)

    @property
    def AUTOMATED_DOWNLOADS_DAILY_LIMIT(self):
        return self._setting(
            "AUTOMATED_DOWNLOADS_DAILY_LIMIT",
            400,
        )

    @property
    def AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT(self):
        """If a video duration (in seconds) is longer than this value,
        the AUTOMATED_DOWNLOADS_PER_TASK_LIMIT will be halved."""
        return self._setting(
            "AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT",
            90 * 60,
        )

    @property
    def AUTOMATED_DOWNLOADS_PER_TASK_LIMIT(self):
        return self._setting(
            "AUTOMATED_DOWNLOADS_PER_TASK_LIMIT",
            4,
        )

    @property
    def AUTOMATED_QUALITY_UPGRADES_PER_TASK_LIMIT(self):
        return self._setting(
            "AUTOMATED_QUALITY_UPGRADES_PER_TASK_LIMIT",
            4,
        )

    @property
    def AUTOMATED_CRONTAB_CATCHUP(self):
        return self._setting(
            "AUTOMATED_CRONTAB_CATCHUP",
            True,
        )

    @property
    def CHANNEL_BANNER_RATE_LIMIT(self):
        return self._setting(
            "CHANNEL_BANNER_RATE_LIMIT",
            30,
        )

    @property
    def CHANNEL_DIRECTORY_SCHEMA(self):
        return self._setting(
            "CHANNEL_DIRECTORY_SCHEMA",
            "{{ channel.system_safe_name }}",
        )

    @property
    def CHANNEL_BLOCK_RESCAN_WINDOW_HOURS(self):
        # If a channel is scanned and then the automated system tries to scan again
        #   within this window, the channel is skipped.
        return self._setting(
            "CHANNEL_BLOCK_RESCAN_WINDOW_HOURS",
            2,
        )

    @property
    def COMMENTS_MAX_PARENTS(self):
        return self._setting(
            "COMMENTS_MAX_PARENTS",
            "all",
        )

    @property
    def COMMENTS_MAX_REPLIES(self):
        return self._setting(
            "COMMENTS_MAX_REPLIES",
            100,
        )

    @property
    def COMMENTS_MAX_REPLIES_PER_THREAD(self):
        return self._setting(
            "COMMENTS_MAX_REPLIES_PER_THREAD",
            10,
        )

    @property
    def COMMENTS_SORTING(self):
        return self._setting(
            "COMMENTS_SORTING",
            "top",
        )

    @property
    def COMMENTS_TOTAL_MAX_COMMENTS(self):
        return self._setting(
            "COMMENTS_TOTAL_MAX_COMMENTS",
            100,
        )

    @property
    def COOKIES(self):
        return self._setting("COOKIES", None)

    @property
    def COOKIES_ALWAYS_REQUIRED(self):
        return self._setting("COOKIES_ALWAYS_REQUIRED", False)

    @property
    def COOKIES_APPLY_ON_RETRIES(self):
        return self._setting("COOKIES_APPLY_ON_RETRIES", False)

    @property
    def COOKIES_CHECKER(self):
        user_func = self._setting("COOKIES_CHECKER", "vidar.services.video_services.should_use_cookies")
        func = import_callable(user_func)
        return func

    @property
    def COOKIES_FILE(self):
        return self._setting("COOKIES_FILE", None)

    @property
    def COOKIES_GETTER(self):
        user_func = self._setting("COOKIES_GETTER", "vidar.services.video_services.get_cookies")
        func = import_callable(user_func)
        return func

    @property
    def CRON_DEFAULT_SELECTION(self):
        return self._setting(
            "CRON_DEFAULT_SELECTION",
            "6-22/4 * * *|7-21/4 * * *",
        )

    @property
    def CRONTAB_CHECK_INTERVAL(self):
        return int(
            self._setting(
                "CRONTAB_CHECK_INTERVAL",
                10,
            )
        )

    @property
    def CRONTAB_CHECK_INTERVAL_MAX_IN_DAYS(self):
        return int(
            self._setting(
                "CRONTAB_CHECK_INTERVAL_MAX_IN_DAYS",
                3,
            )
        )

    @property
    def DELETE_DOWNLOAD_CACHE(self):
        return self._setting(
            "DELETE_DOWNLOAD_CACHE",
            True,
        )

    @property
    def DEFAULT_QUALITY(self):
        return int(
            self._setting(
                "DEFAULT_QUALITY",
                1080,
            )
        )

    @property
    def DOWNLOAD_SPEED_RATE_LIMIT(self):
        return self._setting(
            "DOWNLOAD_SPEED_RATE_LIMIT",
            5000,
        )

    @property
    def GOTIFY_PRIORITY(self):
        return self._setting("GOTIFY_PRIORITY", 5)

    @property
    def GOTIFY_TITLE_PREFIX(self):
        return self._setting("GOTIFY_TITLE_PREFIX", "")

    @property
    def GOTIFY_TOKEN(self):
        return self._setting("GOTIFY_TOKEN", None)

    @property
    def GOTIFY_URL(self):
        return self._setting("GOTIFY_URL", None)

    @property
    def GOTIFY_URL_VERIFY(self):
        return self._setting("GOTIFY_URL_VERIFY", True)

    @property
    def LOAD_SPONSORBLOCK_DATA_ON_DOWNLOAD(self):
        return self._setting(
            "LOAD_SPONSORBLOCK_DATA_ON_DOWNLOAD",
            True,
        )

    @property
    def LOAD_SPONSORBLOCK_DATA_ON_UPDATE_VIDEO_DETAILS(self):
        return self._setting(
            "LOAD_SPONSORBLOCK_DATA_ON_UPDATE_VIDEO_DETAILS",
            True,
        )

    @property
    def MEDIA_CACHE(self):
        return self._setting("MEDIA_CACHE", "")

    @property
    def MEDIA_HARDLINK(self):
        return self._setting("MEDIA_HARDLINK", False)

    @property
    def MEDIA_ROOT(self):
        return self._setting("MEDIA_ROOT", settings.MEDIA_ROOT)

    @property
    def MEDIA_URL(self):
        return self._setting("MEDIA_URL", settings.MEDIA_URL)

    @property
    def MEDIA_STORAGE_CLASS(self):
        user_func = self._django_setting("MEDIA_STORAGE_CLASS", "vidar.storages.LocalFileSystemStorage")
        func = import_callable(user_func)
        return func

    @property
    def METADATA_ALBUM(self):
        user_func = self._setting("METADATA_ALBUM", "vidar.services.video_services.metadata_album")
        func = import_callable(user_func)
        return func

    @property
    def METADATA_ARTIST(self):
        user_func = self._setting("METADATA_ARTIST", "vidar.services.video_services.metadata_artist")
        func = import_callable(user_func)
        return func

    @property
    def MONTHLY_CHANNEL_UPDATE_BANNERS(self):
        return self._setting("MONTHLY_CHANNEL_UPDATE_BANNERS", False)

    @property
    def MONTHLY_CHANNEL_CRONTAB_BALANCING(self):
        return self._setting("MONTHLY_CHANNEL_CRONTAB_BALANCING", False)

    @property
    def MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT(self):
        return self._setting("MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT", True)

    @property
    def NOTIFICATIONS_CHANNEL_STATUS_CHANGED(self):
        return self._setting("NOTIFICATIONS_CHANNEL_STATUS_CHANGED", True)

    @property
    def NOTIFICATIONS_CONVERT_TO_MP4_COMPLETED(self):
        return self._setting("NOTIFICATIONS_CONVERT_TO_MP4_COMPLETED", True)

    @property
    def NOTIFICATIONS_SEND(self):
        return self._setting("NOTIFICATIONS_SEND", True)

    @property
    def NOTIFICATIONS_VIDEO_DOWNLOADED(self):
        return self._setting("NOTIFICATIONS_VIDEO_DOWNLOADED", True)

    @property
    def NOTIFICATIONS_FULL_ARCHIVING_COMPLETED(self):
        return self._setting("NOTIFICATIONS_FULL_ARCHIVING_COMPLETED", True)

    @property
    def NOTIFICATIONS_FULL_ARCHIVING_STARTED(self):
        return self._setting("NOTIFICATIONS_FULL_ARCHIVING_STARTED", True)

    @property
    def NOTIFICATIONS_FULL_INDEXING_COMPLETE(self):
        return self._setting("NOTIFICATIONS_FULL_INDEXING_COMPLETE", True)

    @property
    def NOTIFICATIONS_NO_VIDEOS_ARCHIVED_TODAY(self):
        return self._setting("NOTIFICATIONS_NO_VIDEOS_ARCHIVED_TODAY", True)

    @property
    def NOTIFICATIONS_PLAYLIST_ADDED_BY_MIRROR(self):
        return self._setting("NOTIFICATIONS_PLAYLIST_ADDED_BY_MIRROR", True)

    @property
    def NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_ERRORS(self):
        return self._setting("NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_ERRORS", True)

    @property
    def NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_STRING(self):
        return self._setting("NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_STRING", True)

    @property
    def NOTIFICATIONS_VIDEO_ADDED_TO_PLAYLIST(self):
        return self._setting("NOTIFICATIONS_VIDEO_ADDED_TO_PLAYLIST", True)

    @property
    def NOTIFICATIONS_VIDEO_READDED_TO_PLAYLIST(self):
        return self._setting("NOTIFICATIONS_VIDEO_READDED_TO_PLAYLIST", True)

    @property
    def NOTIFICATIONS_VIDEO_REMOVED_FROM_PLAYLIST(self):
        return self._setting("NOTIFICATIONS_VIDEO_REMOVED_FROM_PLAYLIST", True)

    @property
    def PLAYLIST_BLOCK_RESCAN_WINDOW_HOURS(self):
        # If a playlist is scanned and then the automated system tries to scan again
        #   within this window, the playlist is skipped.
        return self._setting(
            "PLAYLIST_BLOCK_RESCAN_WINDOW_HOURS",
            2,
        )

    @property
    def PRIVACY_STATUS_CHECK_HOURS_PER_DAY(self):
        """How many hours per day does the update_video_statuses_and_details task run for?"""
        return self._setting(
            "PRIVACY_STATUS_CHECK_HOURS_PER_DAY",
            16,  # 5am to 9pm
        )

    @property
    def PRIVACY_STATUS_CHECK_MAX_CHECK_PER_VIDEO(self):
        """How many times should an update_video_details be used on a video, automatically."""
        return self._setting(
            "PRIVACY_STATUS_CHECK_MAX_CHECK_PER_VIDEO",
            3,
        )

    @property
    def PRIVACY_STATUS_CHECK_MIN_AGE(self):
        """How many days before a video status should be checked."""
        return self._setting(
            "PRIVACY_STATUS_CHECK_MIN_AGE",
            30,
        )

    @property
    def PRIVACY_STATUS_CHECK_FORCE_CHECK_PER_CALL(self):
        return self._setting(
            "PRIVACY_STATUS_CHECK_FORCE_CHECK_PER_CALL",
            0,
        )

    @property
    def PROXIES(self):
        """A list of proxies to select from.

        If a callable is supplied, it will be called with the previous proxies,
            the current video being attempted, and the number of attempt the system is on.
            The callable must return a string of a proxy to use, or None to not use a proxy.

        See utils.get_proxy for parameters
        def my_custom_vidar_get_proxy(previous_proxies=None, instance=None, attempt=None):
            ...

        VIDAR_PROXIES = my_custom_vidar_get_proxy
        """
        proxies = self._setting(
            "PROXIES",
            [],
        )

        if isinstance(proxies, (list, tuple, set)):
            return proxies

        if callable(proxies):
            return proxies

        if isinstance(proxies, str):
            for k in ",|;":
                if k in proxies:
                    return proxies.split(k)
            return import_callable(proxies)

        raise ValueError("VIDAR_PROXIES must be: Iterable, a callable, or a dot notation path to a function.")

    @property
    def PROXIES_DEFAULT(self):
        """The default proxy to use if all PROXIES fails"""
        return self._setting("PROXIES_DEFAULT", "")

    @property
    def REDIS_CHANNEL_INDEXING(self):
        return self._setting("REDIS_CHANNEL_INDEXING", True)

    @property
    def REDIS_ENABLED(self):
        return self._setting("REDIS_ENABLED", False)

    @property
    def REDIS_PLAYLIST_INDEXING(self):
        return self._setting("REDIS_PLAYLIST_INDEXING", True)

    @property
    def REDIS_VIDEO_DOWNLOADING(self):
        return self._setting("REDIS_VIDEO_DOWNLOADING", True)

    @property
    def REDIS_VIDEO_CONVERSION_FINISHED(self):
        return self._setting("REDIS_VIDEO_CONVERSION_FINISHED", True)

    @property
    def REDIS_VIDEO_CONVERSION_STARTED(self):
        return self._setting("REDIS_VIDEO_CONVERSION_STARTED", True)

    @property
    def REQUESTS_RATE_LIMIT(self):
        return self._setting(
            "REQUESTS_RATE_LIMIT",
            5,
        )

    @property
    def SAVE_INFO_JSON_FILE(self):
        return self._setting(
            "SAVE_INFO_JSON_FILE",
            True,
        )

    @property
    def SHORTS_FORCE_MAX_QUALITY(self):
        return bool(
            self._setting(
                "SHORTS_FORCE_MAX_QUALITY",
                True,
            )
        )

    @property
    def SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT(self):
        return self._setting(
            "SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT",
            1,
        )

    @property
    def VIDEO_AUTO_DOWNLOAD_LIVE_AMQ_WHEN_DETECTED(self):
        """When update_video_details task is called, a video's live quality may have been
        updated since it was last downloaded. Maybe the download task grabbed 480p while youtube
        was still processing 1080p. If a channel is set to download the best quality available,
        this will track if a videos quality has been upgraded since the video was last downloaded.
        If so, redownload it at max quality."""
        return self._setting(
            "VIDEO_AUTO_DOWNLOAD_LIVE_AMQ_WHEN_DETECTED",
            False,
        )

    @property
    def VIDEO_DOWNLOAD_ERROR_ATTEMPTS(self):
        """How many times to try downloading a video, divide this by VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS
        to see how many days it takes to fully error and stop trying. Default is 14 days worth."""
        return self._setting(
            "VIDEO_DOWNLOAD_ERROR_ATTEMPTS",
            70,
        )

    @property
    def VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS(self):
        return self._setting(
            "VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS",
            5,
        )

    @property
    def VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD(self):
        # How long to wait between error attempts
        return self._setting(
            "VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD",
            60,
        )

    @property
    def VIDEO_DOWNLOAD_FORMAT(self):
        return self._setting(
            "VIDEO_DOWNLOAD_FORMAT",
            "best[height<={quality}]",
            # "bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}][ext=mp4]",
        )

    @property
    def VIDEO_DOWNLOAD_FORMAT_BEST(self):
        return self._setting(
            "VIDEO_DOWNLOAD_FORMAT_BEST",
            "bestvideo[ext=mp4]+bestaudio[ext=mp4]",
        )

    @property
    def VIDEO_DIRECTORY_SCHEMA(self):
        return self._setting(
            "VIDEO_DIRECTORY_SCHEMA",
            '{{ video.upload_date|date:"Y-m-d" }} - {{ video.system_safe_title }} [{{ video.provider_object_id }}]',
        )

    @property
    def VIDEO_FILENAME_SCHEMA(self):
        return self._setting(
            "VIDEO_FILENAME_SCHEMA",
            '{{ video.upload_date|date:"Y-m-d" }} - {{ video.system_safe_title }} [{{ video.provider_object_id }}]',
        )

    @property
    def VIDEO_LIVE_DOWNLOAD_RETRY_HOURS(self):
        return self._setting(
            "VIDEO_LIVE_DOWNLOAD_RETRY_HOURS",
            6,
        )

    @property
    def YTDLP_INITIALIZER(self):
        if user_initializer := self._setting("YTDLP_INITIALIZER", None):
            user_initializer_func = import_callable(user_initializer)
            return user_initializer_func


_app_settings = AppSettings("VIDAR_")


def __getattr__(name):
    # See https://peps.python.org/pep-0562/
    return getattr(_app_settings, name)
