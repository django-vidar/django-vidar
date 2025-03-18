import logging

from django.core.management.base import BaseCommand

from django_celery_beat.models import CrontabSchedule, PeriodicTask

from vidar import app_settings


log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Initializes some core Vidar data. Tasks, and Settings."

    def add_arguments(self, parser):
        # Named (optional) arguments
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force recreation of periodic tasks. Matches on Task name.",
        )
        parser.add_argument("--create-tasks", action="store_false", help="Create celery periodic tasks.")
        parser.add_argument(
            "--update-tasks", action="store_true", help="Update celery periodic tasks, matching on Task name."
        )
        parser.add_argument(
            "--init-settings",
            action="store_true",
            help="Call each vidar setting option. Useful when using your "
            "own VIDAR_SETTING_GETTER and initializing each variable.",
        )

    def handle(self, *args, **options):

        tasks = [
            {
                "name": "vidar: automated archiver",
                "task": "vidar.tasks.automated_archiver",
                "cron": "*/10 * * * *",
            },
            {
                "name": "vidar: automated video quality upgrades",
                "task": "vidar.tasks.automated_video_quality_upgrades",
                "cron": "26 * * * *",
            },
            {
                "name": "vidar: daily maintenances",
                "task": "vidar.tasks.daily_maintenances",
                "cron": "18 7 * * *",
            },
            {
                "name": "vidar: monthly maintenances",
                "task": "vidar.tasks.monthly_maintenances",
                "cron": "18 14 1 * *",
            },
            {
                "name": "vidar: slow full archive",
                "task": "vidar.tasks.slow_full_archive",
                "cron": "34 9-19 * * *",
            },
            {
                "name": "vidar: trigger crontab scans",
                "task": "vidar.tasks.trigger_crontab_scans",
                "cron": "*/10 * * * *",
            },
            {
                "name": "vidar: mirror channel playlists",
                "task": "vidar.tasks.trigger_mirror_live_playlists",
                "cron": "14 7 * * *",
            },
            {
                "name": "vidar: update video details",
                "task": "vidar.tasks.update_video_statuses_and_details",
                "cron": "3,13,23,33,43,53 6-21 * * *",
                "enabled": False,
            },
        ]

        for item in tasks:
            minute, hour, day_of_month, month_of_year, day_of_week = item["cron"].split(" ", 4)

            task_already_exists = PeriodicTask.objects.filter(task=item["task"]).count()

            if options["update_tasks"] and task_already_exists:

                if task_already_exists > 1:
                    self.stdout.write(f"Failure to update task as more than one entry already exists: {item['task']}")
                    continue

                pt = PeriodicTask.objects.get(task=item["task"])
                self.stdout.write(f"Updating {item['task']}")
                pt.enabled = item.get("enabled", True)
                pt.crontab.minute = minute
                pt.crontab.hour = hour
                pt.crontab.day_of_month = day_of_month
                pt.crontab.month_of_year = month_of_year
                pt.crontab.day_of_week = day_of_week
                pt.crontab.save()
                pt.save()

            if options["create_tasks"] and not task_already_exists:
                self.stdout.write(f"Creating Periodic Task: {item['task']}")
                cron = CrontabSchedule.objects.create(
                    minute=minute,
                    hour=hour,
                    day_of_month=day_of_month,
                    month_of_year=month_of_year,
                    day_of_week=day_of_week,
                )

                PeriodicTask.objects.create(
                    task=item["task"],
                    name=item["name"],
                    crontab=cron,
                    enabled=item.get("enabled", True),
                )

        if options["init_settings"]:
            self.stdout.write("Calling all system settings.")
            app_settings.AUTOMATED_DOWNLOADS_DAILY_LIMIT
            app_settings.AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT
            app_settings.AUTOMATED_DOWNLOADS_PER_TASK_LIMIT
            app_settings.AUTOMATED_QUALITY_UPGRADES_PER_TASK_LIMIT
            app_settings.AUTOMATED_CRONTAB_CATCHUP
            app_settings.CHANNEL_BANNER_RATE_LIMIT
            app_settings.CHANNEL_DIRECTORY_SCHEMA
            app_settings.CHANNEL_BLOCK_RESCAN_WINDOW_HOURS
            app_settings.COMMENTS_MAX_PARENTS
            app_settings.COMMENTS_MAX_REPLIES
            app_settings.COMMENTS_MAX_REPLIES_PER_THREAD
            app_settings.COMMENTS_SORTING
            app_settings.COMMENTS_TOTAL_MAX_COMMENTS
            app_settings.COOKIES
            app_settings.COOKIES_ALWAYS_REQUIRED
            app_settings.COOKIES_APPLY_ON_RETRIES
            app_settings.COOKIES_CHECKER
            app_settings.COOKIES_FILE
            app_settings.COOKIES_GETTER
            app_settings.CRON_DEFAULT_SELECTION
            app_settings.CRONTAB_CHECK_INTERVAL
            app_settings.CRONTAB_CHECK_INTERVAL_MAX_IN_DAYS
            app_settings.DELETE_DOWNLOAD_CACHE
            app_settings.DEFAULT_QUALITY
            app_settings.DOWNLOAD_SPEED_RATE_LIMIT
            app_settings.GOTIFY_PRIORITY
            app_settings.GOTIFY_TITLE_PREFIX
            app_settings.GOTIFY_TOKEN
            app_settings.GOTIFY_URL
            app_settings.GOTIFY_URL_VERIFY
            app_settings.LOAD_SPONSORBLOCK_DATA_ON_DOWNLOAD
            app_settings.LOAD_SPONSORBLOCK_DATA_ON_UPDATE_VIDEO_DETAILS
            app_settings.MEDIA_CACHE
            app_settings.MEDIA_HARDLINK
            app_settings.MEDIA_ROOT
            app_settings.MEDIA_URL
            app_settings.MONTHLY_CHANNEL_UPDATE_BANNERS
            app_settings.MONTHLY_CHANNEL_CRONTAB_BALANCING
            app_settings.MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT
            app_settings.NOTIFICATIONS_CHANNEL_STATUS_CHANGED
            app_settings.NOTIFICATIONS_CONVERT_TO_MP4_COMPLETED
            app_settings.NOTIFICATIONS_SEND
            app_settings.NOTIFICATIONS_VIDEO_DOWNLOADED
            app_settings.NOTIFICATIONS_FULL_ARCHIVING_COMPLETED
            app_settings.NOTIFICATIONS_FULL_ARCHIVING_STARTED
            app_settings.NOTIFICATIONS_FULL_INDEXING_COMPLETE
            app_settings.NOTIFICATIONS_NO_VIDEOS_ARCHIVED_TODAY
            app_settings.NOTIFICATIONS_PLAYLIST_ADDED_BY_MIRROR
            app_settings.NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_ERRORS
            app_settings.NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_STRING
            app_settings.NOTIFICATIONS_VIDEO_ADDED_TO_PLAYLIST
            app_settings.NOTIFICATIONS_VIDEO_READDED_TO_PLAYLIST
            app_settings.NOTIFICATIONS_VIDEO_REMOVED_FROM_PLAYLIST
            app_settings.PLAYLIST_BLOCK_RESCAN_WINDOW_HOURS
            app_settings.PRIVACY_STATUS_CHECK_HOURS_PER_DAY
            app_settings.PRIVACY_STATUS_CHECK_MAX_CHECK_PER_VIDEO
            app_settings.PRIVACY_STATUS_CHECK_MIN_AGE
            app_settings.PRIVACY_STATUS_CHECK_FORCE_CHECK_PER_CALL
            app_settings.PROXIES
            app_settings.PROXIES_DEFAULT
            app_settings.REDIS_CHANNEL_INDEXING
            app_settings.REDIS_ENABLED
            app_settings.REDIS_PLAYLIST_INDEXING
            app_settings.REDIS_VIDEO_DOWNLOADING
            app_settings.REDIS_VIDEO_CONVERSION_FINISHED
            app_settings.REDIS_VIDEO_CONVERSION_STARTED
            app_settings.REQUESTS_RATE_LIMIT
            app_settings.SAVE_INFO_JSON_FILE
            app_settings.SHORTS_FORCE_MAX_QUALITY
            app_settings.SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT
            app_settings.VIDEO_AUTO_DOWNLOAD_LIVE_AMQ_WHEN_DETECTED
            app_settings.VIDEO_DOWNLOAD_ERROR_ATTEMPTS
            app_settings.VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS
            app_settings.VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD
            app_settings.VIDEO_DOWNLOAD_FORMAT
            app_settings.VIDEO_DOWNLOAD_FORMAT_BEST
            app_settings.VIDEO_DIRECTORY_SCHEMA
            app_settings.VIDEO_FILENAME_SCHEMA
            app_settings.VIDEO_LIVE_DOWNLOAD_RETRY_HOURS
            app_settings.YTDLP_INITIALIZER
