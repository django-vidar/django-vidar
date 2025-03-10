import logging

from django.core.management.base import BaseCommand

from django_celery_beat.models import CrontabSchedule, PeriodicTask


log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Initializes Celery's Periodic Tasks"

    def add_arguments(self, parser):
        # Named (optional) arguments
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force recreation of periodic tasks. Matches on Task name.",
        )

    def handle(self, *args, **options):

        if not options["force"] and PeriodicTask.objects.filter(task__startswith="vidar."):
            self.stdout.write(
                "Celery Periodic Tasks for django-vidar already exist. Pass --force to force creation/update."
            )
            return

        print("Creating tasks")

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
                "name": "vidar: daily update video details",
                "task": "vidar.tasks.update_video_statuses_and_details",
                "cron": "3,13,23,33,43,53 6-21 * * *",
            },
        ]

        for item in tasks:
            minute, hour, day_of_month, month_of_year, day_of_week = item["cron"].split(" ", 4)

            try:
                pt = PeriodicTask.objects.get(task=item["task"])
                self.stdout.write(f"Updating {item['task']}")
                pt.crontab.minute = minute
                pt.crontab.hour = hour
                pt.crontab.day_of_month = day_of_month
                pt.crontab.month_of_year = month_of_year
                pt.crontab.day_of_week = day_of_week
                pt.crontab.save()
                pt.save()

            except PeriodicTask.DoesNotExist:
                self.stdout.write(f"Create {item['task']}")
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
                )
