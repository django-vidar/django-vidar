import datetime

import celery.states
import requests.exceptions
import yt_dlp

from unittest.mock import call, patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from django_celery_results.models import TaskResult

from vidar import models, tasks, app_settings, exceptions
from vidar.helpers import channel_helpers, celery_helpers
from vidar.services import crontab_services

from .test_functions import date_to_aware_date

User = get_user_model()


class Update_channel_banners_tests(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
        )

    @patch("vidar.interactor.channel_details")
    def test_download_error_sets_channel_status(self, mock_details):
        mock_details.side_effect = yt_dlp.DownloadError("account terminated")
        tasks.update_channel_banners.delay(self.channel.pk).get()
        self.channel.refresh_from_db()
        self.assertEqual(channel_helpers.ChannelStatuses.TERMINATED, self.channel.status)

    @patch("vidar.interactor.channel_details")
    def test_download_error_raises_unknown_status(self, mock_details):
        mock_details.side_effect = yt_dlp.DownloadError("unknown status returned")
        with self.assertRaises(yt_dlp.DownloadError):
            tasks.update_channel_banners.delay(self.channel.pk).get()
        self.channel.refresh_from_db()
        self.assertEqual(channel_helpers.ChannelStatuses.ACTIVE, self.channel.status)

    @patch("vidar.interactor.channel_details")
    @patch("vidar.services.channel_services.set_channel_details_from_ytdlp")
    @patch("vidar.services.channel_services.set_thumbnail")
    @patch("vidar.services.channel_services.set_banner")
    @patch("vidar.services.channel_services.set_tvart")
    def test_setters_called(self, mock_tvart, mock_banner, mock_thumb, mock_serv, mock_details):
        mock_details.return_value = {
            "thumbnails": [
                {"id": "avatar_uncropped", "url": "thumbnail url"},  # thumbnail
                {"width": 720, "height": 120, "url": "banner url"},  # banner
                {"id": "banner_uncropped", "url": "tvart url"},      # tvart
            ]
        }
        retries = tasks.update_channel_banners.delay(self.channel.pk).get()
        self.assertEqual(0, retries)

        mock_details.assert_called_once()
        mock_thumb.assert_called_with(channel=self.channel, url="thumbnail url")
        mock_banner.assert_called_with(channel=self.channel, url="banner url")
        mock_tvart.assert_called_with(channel=self.channel, url="tvart url")

    @patch("vidar.interactor.channel_details")
    @patch("vidar.services.channel_services.set_channel_details_from_ytdlp")
    def test_fails_no_urls(self, mock_serv, mock_details):
        mock_details.return_value = {"thumbnails": []}
        retries = tasks.update_channel_banners.delay(self.channel.pk).get()
        self.assertEqual(3, retries)

        mock_details.assert_called()
        self.assertEqual(4, mock_details.call_count)

    @patch("vidar.interactor.channel_details")
    def test_fails_to_set_channel_details(self, mock_details):
        mock_details.return_value = {}
        with self.assertLogs('vidar.tasks') as logger:

            with self.assertRaises(KeyError):
                tasks.update_channel_banners.delay(self.channel.pk).get()

        log = logger.output[-1]
        self.assertIn("Failure to call set_channel_details_from_ytdlp", log)


class Trigger_channel_scanner_tasks_tests(TestCase):

    @patch("vidar.tasks.scan_channel_for_new_videos")
    @patch("vidar.tasks.scan_channel_for_new_shorts")
    @patch("vidar.tasks.scan_channel_for_new_livestreams")
    def test_index_videos_only(self, mock_live, mock_shorts, mock_videos):
        channel = models.Channel.objects.create(
            index_videos=True,
            index_shorts=False,
            index_livestreams=False
        )

        wait_period, countdown, limit = 5, 0, 10

        tasks.trigger_channel_scanner_tasks(
            channel=channel, limit=limit, wait_period=wait_period, countdown=countdown
        )

        mock_videos.apply_async.assert_called_with(
            kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown
        )
        mock_live.apply_async.assert_not_called()
        mock_shorts.apply_async.assert_not_called()

    @patch("vidar.tasks.scan_channel_for_new_videos")
    @patch("vidar.tasks.scan_channel_for_new_shorts")
    @patch("vidar.tasks.scan_channel_for_new_livestreams")
    def test_index_shorts_only(self, mock_live, mock_shorts, mock_videos):
        channel = models.Channel.objects.create(
            index_videos=False,
            index_shorts=True,
            index_livestreams=False
        )

        wait_period, countdown, limit = 5, 0, 10

        tasks.trigger_channel_scanner_tasks(
            channel=channel, limit=limit, wait_period=wait_period, countdown=countdown
        )

        mock_shorts.apply_async.assert_called_with(
            kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown
        )
        mock_live.apply_async.assert_not_called()
        mock_videos.apply_async.assert_not_called()

    @patch("vidar.tasks.scan_channel_for_new_videos")
    @patch("vidar.tasks.scan_channel_for_new_shorts")
    @patch("vidar.tasks.scan_channel_for_new_livestreams")
    def test_index_livestreams_only(self, mock_live, mock_shorts, mock_videos):
        channel = models.Channel.objects.create(
            index_videos=False,
            index_shorts=False,
            index_livestreams=True
        )

        wait_period, countdown, limit = 5, 0, 10

        tasks.trigger_channel_scanner_tasks(
            channel=channel, limit=limit, wait_period=wait_period, countdown=countdown
        )

        mock_live.apply_async.assert_called_with(
            kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown
        )
        mock_shorts.apply_async.assert_not_called()
        mock_videos.apply_async.assert_not_called()

    @patch("vidar.tasks.scan_channel_for_new_videos")
    @patch("vidar.tasks.scan_channel_for_new_shorts")
    @patch("vidar.tasks.scan_channel_for_new_livestreams")
    def test_index_all(self, mock_live, mock_shorts, mock_videos):
        channel = models.Channel.objects.create(
            index_videos=True,
            index_shorts=True,
            index_livestreams=True
        )

        wait_period, countdown, limit = 5, 0, 10

        tasks.trigger_channel_scanner_tasks(
            channel=channel, limit=limit, wait_period=wait_period, countdown=countdown
        )

        mock_videos.apply_async.assert_called_with(
            kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown
        )
        mock_shorts.apply_async.assert_called_with(
            kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown+wait_period
        )
        mock_live.apply_async.assert_called_with(
            kwargs=dict(pk=channel.pk, limit=limit), countdown=countdown+wait_period*2
        )

    @patch("vidar.tasks.scan_channel_for_new_videos")
    @patch("vidar.tasks.scan_channel_for_new_shorts")
    @patch("vidar.tasks.scan_channel_for_new_livestreams")
    def test_scan_history_created_on_call(self, mock_live, mock_shorts, mock_videos):
        channel = models.Channel.objects.create(
            index_videos=False,
            index_shorts=False,
            index_livestreams=False
        )

        self.assertFalse(channel.scan_history.exists())

        tasks.trigger_channel_scanner_tasks(channel=channel)

        self.assertTrue(channel.scan_history.exists())

        mock_live.apply_async.assert_not_called()
        mock_shorts.apply_async.assert_not_called()
        mock_videos.apply_async.assert_not_called()


class Check_missed_channel_scans_since_last_ran_tests(TestCase):
    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            scanner_crontab="*/5 * * * *"
        )

    def test_no_task_history_returns_none(self):
        output = tasks.check_missed_channel_scans_since_last_ran()
        self.assertEqual((None, None), output)

    @patch("vidar.tasks.trigger_crontab_scans")
    def test_no_history_scans_selected_range(self, mock_trig):
        mock_trig.return_value = {"channels": [], "playlists": []}

        start = timezone.now().replace(minute=0)
        end = start + timezone.timedelta(minutes=9)

        pc, pp = tasks.check_missed_channel_scans_since_last_ran(
            start=start,
            end=end,
            delta=timezone.timedelta(minutes=5),
            force=True,
        )
        self.assertEqual(2, mock_trig.call_count)
        self.assertEqual([], pc)
        self.assertEqual([], pp)

    @patch("vidar.tasks.trigger_crontab_scans")
    def test_with_task_history_returns_none_too_soon(self, mock_trig):
        ts = timezone.now()
        with patch.object(timezone, "now", return_value=ts):
            TaskResult.objects.create(
                task_id="asd-asd-asd",
                task_name="vidar.tasks.trigger_crontab_scans",
                status="SUCCESS",
            )
        output = tasks.check_missed_channel_scans_since_last_ran()
        self.assertEqual((None, None), output)

        mock_trig.assert_not_called()

    @patch("vidar.tasks.trigger_crontab_scans")
    def test_with_task_history_returns_none_too_old(self, mock_trig):
        ts = timezone.now() - timezone.timedelta(days=app_settings.CRONTAB_CHECK_INTERVAL_MAX_IN_DAYS+1)
        with patch.object(timezone, "now", return_value=ts):
            TaskResult.objects.create(
                task_id="asd-asd-asd",
                task_name="vidar.tasks.trigger_crontab_scans",
                status="SUCCESS",
            )
        output = tasks.check_missed_channel_scans_since_last_ran()
        self.assertEqual((None, None), output)

        mock_trig.assert_not_called()


    @patch("vidar.tasks.trigger_crontab_scans")
    def test_with_task_history_returns_correctly(self, mock_trig):
        mock_trig.return_value = {"channels": ["test-1"], "playlists": []}
        end = timezone.now().replace(minute=0)
        ts = end - timezone.timedelta(minutes=app_settings.CRONTAB_CHECK_INTERVAL*2)
        with patch.object(timezone, "now", return_value=ts):
            TaskResult.objects.create(
                task_id="asd-asd-asd",
                task_name="vidar.tasks.trigger_crontab_scans",
                status="SUCCESS",
            )
        channels, playlists = tasks.check_missed_channel_scans_since_last_ran(end=end)
        self.assertEqual(5, mock_trig.call_count)
        self.assertFalse(playlists)
        self.assertEqual(1, len(channels))
        self.assertIn("test-1", channels)


class Trigger_mirror_live_playlists_tests(TestCase):
    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            mirror_playlists=True,
        )
        self.channel2 = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            mirror_playlists=False,
        )

    @patch("vidar.tasks.mirror_live_playlist")
    def test_basics(self, mock_task):
        tasks.trigger_mirror_live_playlists.delay().get()
        mock_task.apply_async.assert_called_once_with(args=[self.channel.pk], countdown=0)


class Mirror_live_playlist_tests(TestCase):
    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            mirror_playlists=True,
            mirror_playlists_crontab=crontab_services.CrontabOptions.DAILY,
        )

    @patch("vidar.services.notification_services.playlist_added_from_mirror")
    @patch("vidar.tasks.sync_playlist_data")
    @patch("vidar.interactor.channel_playlists")
    def test_adds_all_new_playlists(self, mock_inter, mock_sync, mock_notif):
        mock_inter.return_value = {
            "entries": [
                {
                    "id": "playlist-1",
                    "title": "Playlist 1",
                },
                {
                    "id": "playlist-2",
                    "title": "Playlist 2",
                },
            ]
        }

        tasks.mirror_live_playlist.delay(self.channel.pk).get()

        mock_inter.assert_called_once()

        qs = self.channel.playlists.all().order_by("provider_object_id")

        self.assertEqual(2, qs.count())

        p1 = qs[0]  # type: models.Playlist
        p2 = qs[1]  # type: models.Playlist

        self.assertEqual("Playlist 1", p1.title)
        self.assertEqual("Playlist 2", p2.title)

        self.assertTrue(p1.crontab)
        self.assertTrue(p2.crontab)

        self.assertEqual(2, mock_sync.apply_async.call_count)
        self.assertEqual(2, mock_notif.call_count)

    @patch("vidar.services.notification_services.playlist_added_from_mirror")
    @patch("vidar.tasks.sync_playlist_data")
    @patch("vidar.interactor.channel_playlists")
    def test_skips_existing_adds_new(self, mock_inter, mock_sync, mock_notif):
        mock_inter.return_value = {
            "entries": [
                {
                    "id": "playlist-1",
                    "title": "Playlist 1",
                },
                {
                    "id": "playlist-2",
                    "title": "Playlist 2",
                },
            ]
        }

        models.Playlist.objects.create(
            channel=self.channel,
            provider_object_id="playlist-1",
            title="Playlist 1",
        )

        tasks.mirror_live_playlist.delay(self.channel.pk).get()

        mock_inter.assert_called_once()

        qs = self.channel.playlists.all().order_by("provider_object_id")

        self.assertEqual(2, qs.count())

        p1 = qs[0]  # type: models.Playlist
        p2 = qs[1]  # type: models.Playlist

        self.assertEqual("Playlist 1", p1.title)
        self.assertEqual("Playlist 2", p2.title)
        self.assertFalse(p1.crontab)
        self.assertTrue(p2.crontab)

        self.assertEqual(1, mock_sync.apply_async.call_count)
        self.assertEqual(1, mock_notif.call_count)

    @patch("vidar.services.notification_services.playlist_added_from_mirror")
    @patch("vidar.tasks.sync_playlist_data")
    @patch("vidar.interactor.channel_playlists")
    def test_skips_existing_provider_id_old_adds_new(self, mock_inter, mock_sync, mock_notif):
        mock_inter.return_value = {
            "entries": [
                {
                    "id": "playlist-1",
                    "title": "Playlist 1",
                },
                {
                    "id": "playlist-2",
                    "title": "Playlist 2",
                },
            ]
        }

        models.Playlist.objects.create(
            channel=self.channel,
            provider_object_id_old="playlist-1",
            title="Playlist 1",
        )

        tasks.mirror_live_playlist.delay(self.channel.pk).get()

        mock_inter.assert_called_once()

        qs = self.channel.playlists.all().order_by("provider_object_id")

        self.assertEqual(2, qs.count())

        p1 = qs[0]  # type: models.Playlist
        p2 = qs[1]  # type: models.Playlist

        self.assertEqual("Playlist 1", p1.title)
        self.assertEqual("Playlist 2", p2.title)
        self.assertFalse(p1.crontab)
        self.assertTrue(p2.crontab)

        self.assertEqual(1, mock_sync.apply_async.call_count)
        self.assertEqual(1, mock_notif.call_count)

    @patch("vidar.interactor.channel_playlists")
    def test_no_entries_retries_then_fails(self, mock_inter):
        mock_inter.return_value = {}

        tasks.mirror_live_playlist.delay(self.channel.pk).get()

        self.assertEqual(3, mock_inter.call_count)

    @patch("vidar.utils.generate_balanced_crontab_hourly")
    @patch("vidar.services.notification_services.playlist_added_from_mirror")
    @patch("vidar.tasks.sync_playlist_data")
    @patch("vidar.interactor.channel_playlists")
    def test_add_assigns_crontab_hourly(self, mock_inter, mock_sync, mock_notif, mock_cron):
        cron_type = crontab_services.CrontabOptions.HOURLY
        mock_cron.return_value = cron_type
        self.channel.mirror_playlists_crontab = cron_type
        self.channel.save()
        mock_inter.return_value = {
            "entries": [
                {"id": "playlist-1", "title": "Playlist 1"},
                {"id": "playlist-2", "title": "Playlist 2"},
            ]
        }

        tasks.mirror_live_playlist.delay(self.channel.pk).get()

        mock_inter.assert_called_once()

        qs = self.channel.playlists.all().order_by("provider_object_id")

        self.assertEqual(2, qs.count())

        p1 = qs[0]  # type: models.Playlist
        p2 = qs[1]  # type: models.Playlist

        self.assertEqual(cron_type, p1.crontab)
        self.assertEqual(cron_type, p2.crontab)

    @patch("vidar.services.crontab_services.generate_daily")
    @patch("vidar.services.notification_services.playlist_added_from_mirror")
    @patch("vidar.tasks.sync_playlist_data")
    @patch("vidar.interactor.channel_playlists")
    def test_add_assigns_crontab_daily(self, mock_inter, mock_sync, mock_notif, mock_cron):
        cron_type = crontab_services.CrontabOptions.DAILY
        mock_cron.return_value = cron_type
        self.channel.mirror_playlists_crontab = cron_type
        self.channel.save()
        mock_inter.return_value = {
            "entries": [
                {"id": "playlist-1", "title": "Playlist 1"},
                {"id": "playlist-2", "title": "Playlist 2"},
            ]
        }

        tasks.mirror_live_playlist.delay(self.channel.pk).get()

        mock_inter.assert_called_once()

        qs = self.channel.playlists.all().order_by("provider_object_id")

        self.assertEqual(2, qs.count())

        p1 = qs[0]  # type: models.Playlist
        p2 = qs[1]  # type: models.Playlist

        self.assertEqual(cron_type, p1.crontab)
        self.assertEqual(cron_type, p2.crontab)

    @patch("vidar.services.crontab_services.generate_weekly")
    @patch("vidar.services.notification_services.playlist_added_from_mirror")
    @patch("vidar.tasks.sync_playlist_data")
    @patch("vidar.interactor.channel_playlists")
    def test_add_assigns_crontab_weekly(self, mock_inter, mock_sync, mock_notif, mock_cron):
        cron_type = crontab_services.CrontabOptions.WEEKLY
        mock_cron.return_value = cron_type
        self.channel.mirror_playlists_crontab = cron_type
        self.channel.save()
        mock_inter.return_value = {
            "entries": [
                {"id": "playlist-1", "title": "Playlist 1"},
                {"id": "playlist-2", "title": "Playlist 2"},
            ]
        }

        tasks.mirror_live_playlist.delay(self.channel.pk).get()

        mock_inter.assert_called_once()

        qs = self.channel.playlists.all().order_by("provider_object_id")

        self.assertEqual(2, qs.count())

        p1 = qs[0]  # type: models.Playlist
        p2 = qs[1]  # type: models.Playlist

        self.assertEqual(cron_type, p1.crontab)
        self.assertEqual(cron_type, p2.crontab)

    @patch("vidar.services.crontab_services.generate_monthly")
    @patch("vidar.services.notification_services.playlist_added_from_mirror")
    @patch("vidar.tasks.sync_playlist_data")
    @patch("vidar.interactor.channel_playlists")
    def test_add_assigns_crontab_monthly(self, mock_inter, mock_sync, mock_notif, mock_cron):
        cron_type = crontab_services.CrontabOptions.MONTHLY
        mock_cron.return_value = cron_type
        self.channel.mirror_playlists_crontab = cron_type
        self.channel.save()
        mock_inter.return_value = {
            "entries": [
                {"id": "playlist-1", "title": "Playlist 1"},
                {"id": "playlist-2", "title": "Playlist 2"},
            ]
        }

        tasks.mirror_live_playlist.delay(self.channel.pk).get()

        mock_inter.assert_called_once()

        qs = self.channel.playlists.all().order_by("provider_object_id")

        self.assertEqual(2, qs.count())

        p1 = qs[0]  # type: models.Playlist
        p2 = qs[1]  # type: models.Playlist

        self.assertEqual(cron_type, p1.crontab)
        self.assertEqual(cron_type, p2.crontab)


class Subscribe_to_channel_tests(TestCase):
    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
        )

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    @patch("vidar.tasks.rename_video_files")
    @patch("vidar.tasks.update_channel_banners")
    @patch("vidar.interactor.channel_details")
    def test_basics(self, mock_inter, mock_banners, mock_renamer, mock_scanner):
        mock_inter.return_value = {
            "title": "Channel 1",
            "description": "c1desc",
            "uploader_id": "asdfghjkl",
        }

        tasks.subscribe_to_channel.delay(self.channel.provider_object_id, sleep=False).get()

        self.channel.refresh_from_db()

        self.assertEqual("Channel 1", self.channel.name)
        self.assertEqual("c1desc", self.channel.description)
        self.assertEqual("asdfghjkl", self.channel.uploader_id)

        mock_banners.delay.assert_called_once()
        mock_renamer.delay.assert_not_called()
        mock_scanner.assert_called_once()

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    @patch("vidar.tasks.rename_video_files")
    @patch("vidar.tasks.update_channel_banners")
    @patch("vidar.interactor.channel_details")
    def test_only_videos_with_files_get_renamer_called(self, mock_inter, mock_banners, mock_renamer, mock_scanner):
        models.Video.objects.create(channel=self.channel, file='test.mp4')
        models.Video.objects.create(channel=self.channel)
        mock_inter.return_value = {
            "title": "Channel 1",
            "description": "c1desc",
            "uploader_id": "asdfghjkl",
        }

        tasks.subscribe_to_channel.delay(self.channel.provider_object_id, sleep=False).get()

        mock_banners.delay.assert_called_once()
        mock_renamer.delay.assert_called_once()
        mock_scanner.assert_called_once()


class Trigger_crontab_scans_tests(TestCase):

    @patch("vidar.tasks.check_missed_channel_scans_since_last_ran")
    def test_check_missed_called_by_default(self, mock_task):
        tasks.trigger_crontab_scans.delay()
        mock_task.assert_called_once()

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    def test_triggers_channel_on_time(self, mock_trig):
        channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            scanner_crontab="0 9 * * *"
        )

        now = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        output = tasks.trigger_crontab_scans.delay(
            now=now.timestamp(),
            check_if_crontab_was_missed=False
        ).get()

        mock_trig.assert_called_once()

        self.assertDictEqual({"channels": [channel.pk], "playlists": []}, output)

    @patch("vidar.tasks.check_missed_channel_scans_since_last_ran")
    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    def test_channel_skipped_as_checker_triggered_already(self, mock_trig, mock_checker):
        channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            scanner_crontab="0 9 * * *"
        )

        mock_checker.return_value = ([channel.pk], [])

        now = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        output = tasks.trigger_crontab_scans.delay(
            now=now.timestamp(),
        ).get()

        mock_trig.assert_not_called()

        self.assertDictEqual({"channels": [channel.pk], "playlists": []}, output)

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    def test_triggers_nothing(self, mock_trig):
        channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            scanner_crontab="0 9 * * *"
        )

        now = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        output = tasks.trigger_crontab_scans.delay(
            now=now.timestamp(),
            check_if_crontab_was_missed=False
        ).get()

        mock_trig.assert_not_called()

        self.assertDictEqual({"channels": [], "playlists": []}, output)

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    def test_triggers_nothing_as_channel_was_scanned_earlier(self, mock_trig):
        channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            scanner_crontab="* * * * *"
        )

        now = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)

        with patch.object(timezone, 'now', return_value=now - timezone.timedelta(minutes=15)):
            channel.scan_history.create()

        with patch.object(timezone, "now", return_value=now):
            output = tasks.trigger_crontab_scans.delay(
                now=now.timestamp(),
                check_if_crontab_was_missed=False
            ).get()

        mock_trig.assert_not_called()

        self.assertDictEqual({"channels": [], "playlists": []}, output)

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    def test_scan_after_datetime_triggers_regardless(self, mock_trig):

        now = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)

        channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            scanner_crontab="* * * * *",
            scan_after_datetime=now,
        )

        with patch.object(timezone, 'now', return_value=now - timezone.timedelta(minutes=15)):
            channel.scan_history.create()

        with patch.object(timezone, "now", return_value=now):
            output = tasks.trigger_crontab_scans.delay(
                now=now.timestamp(),
                check_if_crontab_was_missed=False
            ).get()

        mock_trig.assert_called_once()

        self.assertDictEqual({"channels": [channel.pk], "playlists": []}, output)

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    def test_scan_after_datetime_skipped_as_crontab_got_it_first(self, mock_trig):

        now = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)

        channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            scanner_crontab="* * * * *",
            scan_after_datetime=now,
        )

        with patch.object(timezone, "now", return_value=now):
            output = tasks.trigger_crontab_scans.delay(
                now=now.timestamp(),
                check_if_crontab_was_missed=False
            ).get()

        mock_trig.assert_called_once()

        self.assertDictEqual({"channels": [channel.pk], "playlists": []}, output)

    @patch("vidar.tasks.sync_playlist_data")
    def test_triggers_playlist_on_time(self, mock_sync):
        playlist = models.Playlist.objects.create(
            provider_object_id="playlist-id",
            title="test playlist",
            crontab="0 9 * * *"
        )

        now = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        output = tasks.trigger_crontab_scans.delay(
            now=now.timestamp(),
            check_if_crontab_was_missed=False
        ).get()

        mock_sync.delay.assert_called_once()

        self.assertDictEqual({"channels": [], "playlists": [playlist.pk]}, output)

    @patch("vidar.tasks.check_missed_channel_scans_since_last_ran")
    @patch("vidar.tasks.sync_playlist_data")
    def test_playlist_skipped_as_checker_triggered_already(self, mock_sync, mock_checker):
        playlist = models.Playlist.objects.create(
            provider_object_id="playlist-id",
            title="test playlist",
            crontab="0 9 * * *"
        )

        mock_checker.return_value = ([], [playlist.pk])

        now = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        output = tasks.trigger_crontab_scans.delay(
            now=now.timestamp(),
        ).get()

        mock_sync.assert_not_called()

        self.assertDictEqual({"channels": [], "playlists": [playlist.pk]}, output)

    @patch("vidar.tasks.sync_playlist_data")
    def test_triggers_nothing_with_playlists(self, mock_sync):
        playlist = models.Playlist.objects.create(
            provider_object_id="playlist-id",
            title="test playlist",
            crontab="0 9 * * *"
        )

        now = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        output = tasks.trigger_crontab_scans.delay(
            now=now.timestamp(),
            check_if_crontab_was_missed=False
        ).get()

        mock_sync.assert_not_called()

        self.assertDictEqual({"channels": [], "playlists": []}, output)

    @patch("vidar.tasks.sync_playlist_data")
    def test_triggers_nothing_as_playlist_was_scanned_earlier(self, mock_sync):
        playlist = models.Playlist.objects.create(
            provider_object_id="playlist-id",
            title="test playlist",
            crontab="* * * * *"
        )

        now = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)

        with patch.object(timezone, 'now', return_value=now - timezone.timedelta(minutes=15)):
            playlist.scan_history.create()

        with patch.object(timezone, "now", return_value=now):
            output = tasks.trigger_crontab_scans.delay(
                now=now.timestamp(),
                check_if_crontab_was_missed=False
            ).get()

        mock_sync.assert_not_called()

        self.assertDictEqual({"channels": [], "playlists": []}, output)


class Scan_channel_for_new_videos_tests(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            uploader_id="channel-uploader-id",
            index_videos=True,
            download_videos=True,
        )

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_fails_account_terminated(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("account terminated")
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_inter.assert_called_once()
        self.channel.refresh_from_db()
        self.assertEqual(channel_helpers.ChannelStatuses.TERMINATED, self.channel.status)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_fails_invalid_status(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("invalid status")
        with self.assertRaises(yt_dlp.DownloadError):
            tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_inter.assert_called_once()
        self.channel.refresh_from_db()
        self.assertEqual(channel_helpers.ChannelStatuses.ACTIVE, self.channel.status)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_nothing(self, mock_inter):
        mock_inter.return_value = None
        output = tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        self.assertIsNone(output)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_no_entries(self, mock_inter):
        mock_inter.return_value = {"entries": []}
        output = tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        self.assertIsNone(output)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_premiering_video_with_blank_entry(self, mock_inter):
        mock_inter.return_value = {"entries": [[],]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        self.assertFalse(self.channel.videos.exists())

    @patch("vidar.interactor.func_with_retry")
    def test_video_id_is_blocked(self, mock_inter):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "id": "video-id",
        },]}
        models.VideoBlocked.objects.create(
            provider_object_id="video-id",
        )
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        self.assertFalse(self.channel.videos.exists())
        self.channel.refresh_from_db()
        self.assertEqual("channel-uploader-id", self.channel.uploader_id)

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_created(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_called_once()
        mock_comments.delay.assert_not_called()

        self.assertEqual(1, self.channel.videos.count())
        self.channel.refresh_from_db()
        video = self.channel.videos.get()
        self.assertEqual(self.channel, video.channel)
        self.assertEqual(datetime.date(2025, 4, 5), video.upload_date)
        self.assertTrue(video.is_video)
        self.assertFalse(video.is_short)
        self.assertFalse(video.is_livestream)
        self.assertEqual("video title", video.title)
        self.assertEqual("video description", video.description)

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_created_sets_channel_uploader_id(self, mock_inter, mock_download, mock_comments):
        self.channel.uploader_id = ""
        self.channel.save()

        mock_inter.return_value = {"entries": [{
            "uploader_id": "video-uploader-id",
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_called_once()
        mock_comments.delay.assert_not_called()

        self.assertEqual(1, self.channel.videos.count())
        self.channel.refresh_from_db()
        video = self.channel.videos.get()
        self.assertEqual(self.channel, video.channel)
        self.assertEqual(self.channel.uploader_id, "video-uploader-id")

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_exists_permit_download_false_skipped(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}

        models.Video.objects.create(provider_object_id="video-id", permit_download=False)

        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_new_video_not_downloaded_upload_date_is_too_old(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "19810112",
        },]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()
        self.assertEqual(1, self.channel.videos.count())

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_not_downloaded_when_channel_download_is_false(self, mock_inter, mock_download, mock_comments):
        self.channel.download_videos = False
        self.channel.save()

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

        self.assertEqual(1, self.channel.videos.count())

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_force_downloaded_when_channel_download_is_false(self, mock_inter, mock_download, mock_comments):
        self.channel.download_videos = False
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
            force_download=True
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_called_once()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_not_downloaded_when_channel_skip_next(self, mock_inter, mock_download, mock_comments):
        self.channel.skip_next_downloads = 1
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_has_file_do_nothing(self, mock_inter, mock_download, mock_comments):
        self.channel.videos.create(
            provider_object_id="video-id",
            file="test.mp4",
            force_download=True,
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_has_file_download_comments(self, mock_inter, mock_download, mock_comments):
        self.channel.download_comments_during_scan = True
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
            file="test.mp4",
            force_download=True,
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_called_once()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_video_exists_not_downloaded(self, mock_inter, mock_download, mock_comments):

        self.channel.videos.create(
            provider_object_id="video-id",
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_videos.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()


class Scan_channel_for_new_shorts_tests(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            uploader_id="channel-uploader-id",
            index_shorts=True,
            download_shorts=True,
        )

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_fails_account_terminated(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("account terminated")
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_inter.assert_called_once()
        self.channel.refresh_from_db()
        self.assertEqual(channel_helpers.ChannelStatuses.TERMINATED, self.channel.status)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_fails_no_shorts_tab(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("This channel does not have a shorts tab")
        with self.assertRaises(yt_dlp.DownloadError):
            tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_inter.assert_called_once()
        self.channel.refresh_from_db()
        self.assertFalse(self.channel.index_shorts)
        self.assertFalse(self.channel.download_shorts)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_fails_invalid_status(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("invalid status")
        with self.assertRaises(yt_dlp.DownloadError):
            tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_inter.assert_called_once()
        self.channel.refresh_from_db()
        self.assertEqual(channel_helpers.ChannelStatuses.ACTIVE, self.channel.status)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_nothing(self, mock_inter):
        mock_inter.return_value = None
        output = tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        self.assertIsNone(output)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_no_entries(self, mock_inter):
        mock_inter.return_value = {"entries": []}
        output = tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        self.assertIsNone(output)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_premiering_video_with_blank_entry(self, mock_inter):
        mock_inter.return_value = {"entries": [[],]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        self.assertFalse(self.channel.videos.exists())

    @patch("vidar.interactor.func_with_retry")
    def test_short_id_is_blocked(self, mock_inter):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "id": "video-id",
        },]}
        models.VideoBlocked.objects.create(
            provider_object_id="video-id",
        )
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        self.assertFalse(self.channel.videos.exists())
        self.channel.refresh_from_db()
        self.assertEqual("channel-uploader-id", self.channel.uploader_id)

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_short_created(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
            "original_url": "https://www.youtube.com/shorts/video-id/",
        },]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_called_once()
        mock_comments.delay.assert_not_called()

        self.assertEqual(1, self.channel.videos.count())
        self.channel.refresh_from_db()
        video = self.channel.videos.get()
        self.assertEqual(self.channel, video.channel)
        self.assertEqual(datetime.date(2025, 4, 5), video.upload_date)
        self.assertTrue(video.is_short)
        self.assertFalse(video.is_video)
        self.assertFalse(video.is_livestream)
        self.assertEqual("video title", video.title)
        self.assertEqual("video description", video.description)

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_short_exists_permit_download_false_skipped(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}

        models.Video.objects.create(provider_object_id="video-id", permit_download=False)

        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_new_video_not_downloaded_upload_date_is_too_old(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "19810112",
        },]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()
        self.assertEqual(1, self.channel.videos.count())

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_short_not_downloaded_when_channel_download_is_false(self, mock_inter, mock_download, mock_comments):
        self.channel.download_shorts = False
        self.channel.save()

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

        self.assertEqual(1, self.channel.videos.count())

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_short_force_downloaded_when_channel_download_is_false(self, mock_inter, mock_download, mock_comments):
        self.channel.download_shorts = False
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
            force_download=True
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_called_once()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_short_not_downloaded_when_channel_skip_next(self, mock_inter, mock_download, mock_comments):
        self.channel.skip_next_downloads = 1
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_short_has_file_do_nothing(self, mock_inter, mock_download, mock_comments):
        self.channel.videos.create(
            provider_object_id="video-id",
            file="test.mp4",
            force_download=True,
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_short_has_file_download_comments(self, mock_inter, mock_download, mock_comments):
        self.channel.download_comments_during_scan = True
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
            file="test.mp4",
            force_download=True,
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_called_once()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_short_exists_not_downloaded(self, mock_inter, mock_download, mock_comments):

        self.channel.videos.create(
            provider_object_id="video-id",
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_shorts.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()


class Scan_channel_for_new_livestreams_tests(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
            uploader_id="channel-uploader-id",
            index_livestreams=True,
            download_livestreams=True,
        )

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_fails_account_terminated(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("account terminated")
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_inter.assert_called_once()
        self.channel.refresh_from_db()
        self.assertEqual(channel_helpers.ChannelStatuses.TERMINATED, self.channel.status)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_fails_not_currently_live(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("not currently live")
        with self.assertRaises(yt_dlp.DownloadError):
            tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_inter.assert_called_once()
        self.channel.refresh_from_db()
        self.assertFalse(self.channel.index_livestreams)
        self.assertFalse(self.channel.download_livestreams)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_fails_invalid_status(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("invalid status")
        with self.assertRaises(yt_dlp.DownloadError):
            tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_inter.assert_called_once()
        self.channel.refresh_from_db()
        self.assertEqual(channel_helpers.ChannelStatuses.ACTIVE, self.channel.status)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_nothing(self, mock_inter):
        mock_inter.return_value = None
        output = tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        self.assertIsNone(output)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_no_entries(self, mock_inter):
        mock_inter.return_value = {"entries": []}
        output = tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        self.assertIsNone(output)

    @patch("vidar.interactor.func_with_retry")
    def test_yt_dlp_returns_premiering_video_with_blank_entry(self, mock_inter):
        mock_inter.return_value = {"entries": [[],]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        self.assertFalse(self.channel.videos.exists())

    @patch("vidar.interactor.func_with_retry")
    def test_livestream_id_is_blocked(self, mock_inter):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "id": "video-id",
        },]}
        models.VideoBlocked.objects.create(
            provider_object_id="video-id",
        )
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        self.assertFalse(self.channel.videos.exists())
        self.channel.refresh_from_db()
        self.assertEqual("channel-uploader-id", self.channel.uploader_id)

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_livestream_created(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
            "was_live": True,
        },]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_called_once()
        mock_comments.delay.assert_not_called()

        self.assertEqual(1, self.channel.videos.count())
        self.channel.refresh_from_db()
        video = self.channel.videos.get()
        self.assertEqual(self.channel, video.channel)
        self.assertEqual(datetime.date(2025, 4, 5), video.upload_date)
        self.assertFalse(video.is_short)
        self.assertFalse(video.is_video)
        self.assertTrue(video.is_livestream)
        self.assertEqual("video title", video.title)
        self.assertEqual("video description", video.description)

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_livestream_exists_permit_download_false_skipped(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}

        models.Video.objects.create(provider_object_id="video-id", permit_download=False)

        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_new_video_not_downloaded_upload_date_is_too_old(self, mock_inter, mock_download, mock_comments):
        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "19810112",
        },]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()
        self.assertEqual(1, self.channel.videos.count())

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_livestream_not_downloaded_when_channel_download_is_false(self, mock_inter, mock_download, mock_comments):
        self.channel.download_livestreams = False
        self.channel.save()

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

        self.assertEqual(1, self.channel.videos.count())

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_livestream_force_downloaded_when_channel_download_is_false(self, mock_inter, mock_download, mock_comments):
        self.channel.download_livestreams = False
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
            force_download=True
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_called_once()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_livestream_not_downloaded_when_channel_skip_next(self, mock_inter, mock_download, mock_comments):
        self.channel.skip_next_downloads = 1
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_livestream_has_file_do_nothing(self, mock_inter, mock_download, mock_comments):
        self.channel.videos.create(
            provider_object_id="video-id",
            file="test.mp4",
            force_download=True,
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_livestream_has_file_download_comments(self, mock_inter, mock_download, mock_comments):
        self.channel.download_comments_during_scan = True
        self.channel.save()

        self.channel.videos.create(
            provider_object_id="video-id",
            file="test.mp4",
            force_download=True,
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        },]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_called_once()

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.func_with_retry")
    def test_livestream_exists_not_downloaded(self, mock_inter, mock_download, mock_comments):

        self.channel.videos.create(
            provider_object_id="video-id",
        )

        mock_inter.return_value = {"entries": [{
            "uploader_id": self.channel.uploader_id,
            "channel_id": self.channel.provider_object_id,
            "id": "video-id",
            "title": "video title",
            "description": "video description",
            "upload_date": "20250405",
        }, ]}
        tasks.scan_channel_for_new_livestreams.delay(pk=self.channel.pk).get()
        mock_download.delay.assert_not_called()
        mock_comments.delay.assert_not_called()


class Fully_index_channel_test(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            provider_object_id="channel-id",
            name="test channel",
            status=channel_helpers.ChannelStatuses.ACTIVE,
        )

    def test_no_indexings_returns_none(self):
        self.channel.index_videos = False
        self.channel.index_shorts = False
        self.channel.index_livestreams = False
        self.channel.save()

        output = tasks.fully_index_channel(pk=self.channel.pk)
        self.assertIsNone(output)

    @patch("vidar.interactor.func_with_retry")
    def test_ytdlp_returns_nothing(self, mock_inter):
        mock_inter.return_value = None

        self.channel.index_videos = True
        self.channel.index_shorts = True
        self.channel.index_livestreams = True
        self.channel.save()

        output = tasks.fully_index_channel(pk=self.channel.pk)
        self.assertIsNone(output)

        self.assertEqual(3, mock_inter.call_count)

    @patch("vidar.interactor.func_with_retry")
    def test_ytdlp_returns_premiering_video(self, mock_inter):
        mock_inter.return_value = {
            "entries": [
                []
            ]
        }

        self.channel.index_videos = True
        self.channel.index_shorts = False
        self.channel.index_livestreams = False
        self.channel.save()

        output = tasks.fully_index_channel(pk=self.channel.pk)
        self.assertIsNone(output)

        self.assertEqual(1, mock_inter.call_count)

        self.assertFalse(models.Video.objects.exists())

    @patch("vidar.interactor.func_with_retry")
    def test_creates_videos_and_sets_fully_indexed_flag(self, mock_inter):
        self.channel.index_videos = True
        self.channel.index_shorts = False
        self.channel.index_livestreams = False
        self.channel.save()

        mock_inter.return_value = {
            "entries": [
                {
                    "uploader_id": self.channel.uploader_id,
                    "channel_id": self.channel.provider_object_id,
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ]
        }

        tasks.fully_index_channel(pk=self.channel.pk)

        self.assertEqual(1, models.Video.objects.filter(is_video=True).count())

        self.channel.refresh_from_db()
        self.assertTrue(self.channel.fully_indexed)
        self.assertFalse(self.channel.fully_indexed_shorts)
        self.assertFalse(self.channel.fully_indexed_livestreams)

    @patch("vidar.interactor.func_with_retry")
    def test_creates_shorts_and_sets_fully_indexed_flag(self, mock_inter):
        self.channel.index_videos = False
        self.channel.index_shorts = True
        self.channel.index_livestreams = False
        self.channel.save()

        mock_inter.return_value = {
            "entries": [
                {
                    "uploader_id": self.channel.uploader_id,
                    "channel_id": self.channel.provider_object_id,
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                    "original_url": "https://www.youtube.com/shorts/video-id"
                }
            ]
        }

        tasks.fully_index_channel(pk=self.channel.pk)

        self.assertEqual(1, models.Video.objects.filter(is_short=True).count())

        self.channel.refresh_from_db()
        self.assertFalse(self.channel.fully_indexed)
        self.assertTrue(self.channel.fully_indexed_shorts)
        self.assertFalse(self.channel.fully_indexed_livestreams)

    @patch("vidar.interactor.func_with_retry")
    def test_creates_livestreams_and_sets_fully_indexed_flag(self, mock_inter):
        self.channel.index_videos = False
        self.channel.index_shorts = False
        self.channel.index_livestreams = True
        self.channel.save()

        mock_inter.return_value = {
            "entries": [
                {
                    "uploader_id": self.channel.uploader_id,
                    "channel_id": self.channel.provider_object_id,
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                    "was_live": True
                }
            ]
        }

        tasks.fully_index_channel(pk=self.channel.pk)

        self.assertEqual(1, models.Video.objects.filter(is_livestream=True).count())

        self.channel.refresh_from_db()
        self.assertFalse(self.channel.fully_indexed)
        self.assertFalse(self.channel.fully_indexed_shorts)
        self.assertTrue(self.channel.fully_indexed_livestreams)

    @patch("vidar.interactor.func_with_retry")
    def test_unblock_video(self, mock_inter):
        mock_inter.return_value = {
            "entries": [
                {
                    "uploader_id": self.channel.uploader_id,
                    "channel_id": self.channel.provider_object_id,
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ]
        }

        models.VideoBlocked.objects.create(provider_object_id="video-id")

        tasks.fully_index_channel(pk=self.channel.pk)

        self.assertFalse(models.VideoBlocked.objects.exists())

    @patch("vidar.interactor.func_with_retry")
    def test_target_sets_type_video(self, mock_inter):
        mock_inter.return_value = {
            "entries": [
                {
                    "uploader_id": self.channel.uploader_id,
                    "channel_id": self.channel.provider_object_id,
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ]
        }

        ts = timezone.now()
        with patch.object(timezone, "now", return_value=ts):
            tasks.fully_index_channel(pk=self.channel.pk)

        self.assertEqual(1, models.Video.objects.count())

        video = models.Video.objects.get()
        self.assertTrue(video.is_video)
        self.assertFalse(video.is_short)
        self.assertFalse(video.is_livestream)

        self.channel.refresh_from_db()
        self.assertEqual(ts, self.channel.last_scanned)

    @patch("vidar.interactor.func_with_retry")
    def test_target_sets_type_short(self, mock_inter):
        self.channel.index_videos = False
        self.channel.index_shorts = True
        self.channel.save()

        mock_inter.return_value = {
            "entries": [
                {
                    "uploader_id": self.channel.uploader_id,
                    "channel_id": self.channel.provider_object_id,
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                    "original_url": "https://www.youtube.com/shorts/video-id"
                }
            ]
        }

        ts = timezone.now()
        with patch.object(timezone, "now", return_value=ts):
            tasks.fully_index_channel(pk=self.channel.pk)

        self.assertEqual(1, models.Video.objects.count())

        video = models.Video.objects.get()
        self.assertFalse(video.is_video)
        self.assertTrue(video.is_short)
        self.assertFalse(video.is_livestream)

        self.channel.refresh_from_db()
        self.assertEqual(ts, self.channel.last_scanned_shorts)

    @patch("vidar.interactor.func_with_retry")
    def test_target_sets_type_livestream(self, mock_inter):
        self.channel.index_videos = False
        self.channel.index_shorts = False
        self.channel.index_livestreams = True
        self.channel.save()

        mock_inter.return_value = {
            "entries": [
                {
                    "uploader_id": self.channel.uploader_id,
                    "channel_id": self.channel.provider_object_id,
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                    "was_live": True
                }
            ]
        }

        ts = timezone.now()
        with patch.object(timezone, "now", return_value=ts):
            tasks.fully_index_channel(pk=self.channel.pk)

        self.assertEqual(1, models.Video.objects.count())

        video = models.Video.objects.get()
        self.assertFalse(video.is_video)
        self.assertFalse(video.is_short)
        self.assertTrue(video.is_livestream)

        self.channel.refresh_from_db()
        self.assertEqual(ts, self.channel.last_scanned_livestreams)


class Video_downloaded_successfully_tests(TestCase):

    def setUp(self) -> None:
        self.video = models.Video.objects.create(
            title="video 1",
            download_comments_on_index=True,
        )

    @patch("vidar.services.notification_services.video_downloaded")
    @patch("vidar.signals.video_download_successful")
    @patch("vidar.tasks.load_sponsorblock_data")
    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.load_video_thumbnail")
    def test_successful(self, mock_load, mock_comments, mock_sb, mock_signal, mock_notif):

        self.video.info_json = SimpleUploadedFile("info.json", b"{}")
        self.video.save()

        celery_helpers.object_lock_acquire(obj=self.video, timeout=2)

        tasks.video_downloaded_successfully(pk=self.video.pk)

        self.assertFalse(celery_helpers.is_object_locked(obj=self.video))

        mock_load.apply_async.assert_called_once()
        mock_comments.delay.assert_called_once()

        mock_sb.delay.assert_called_once()
        mock_signal.send.assert_called_once()
        mock_notif.assert_called_once()


class Download_provider_video_comments_tests(TestCase):

    def setUp(self) -> None:
        self.video = models.Video.objects.create(
            title="video 1",
            privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC,
        )

    def test_privacy_status_not_public_does_nothing(self):
        self.video.privacy_status = models.Video.VideoPrivacyStatuses.PRIVATE
        self.video.save()

        with self.assertLogs("vidar.tasks") as logger:
            output = tasks.download_provider_video_comments.delay(self.video.pk).get()

        self.assertIsNone(output)
        self.assertEqual(1, len(logger.output))
        log = logger.output[0]
        self.assertIn("Video is not publicly visible", log)

    @patch("vidar.interactor.video_comments")
    def test_ytdlp_returns_nothing(self, mock_inter):
        mock_inter.return_value = None

        tasks.download_provider_video_comments.delay(self.video.pk).get()

        mock_inter.assert_called_once()

        self.video.refresh_from_db()

        self.assertIn("comments_downloaded", self.video.system_notes)

    @patch("vidar.interactor.video_comments")
    def test_ytdlp_downloaderror(self, mock_inter):
        mock_inter.side_effect = yt_dlp.DownloadError("tests failure")

        with self.assertRaises(yt_dlp.DownloadError):
            tasks.download_provider_video_comments.delay(self.video.pk).get()

        self.assertEqual(4, mock_inter.call_count)

        self.video.refresh_from_db()

        self.assertIn("proxies_attempted_comment_grabber", self.video.system_notes)

    @patch("vidar.interactor.video_comments")
    def test_creates_comments(self, mock_inter):
        mock_inter.return_value = {
            "comments": [
                {
                    "id": "comment-id-1",
                    "parent": "root",
                    "timestamp": str(int(timezone.now().timestamp())),

                    "author": "Author",
                    "author_id": "author-id",
                    "author_is_uploader": False,
                    "author_thumbnail": "author-url",
                    "is_favorited": False,
                    "like_count": 0,
                    "text": "comment here in tests",
                },
            ]
        }

        tasks.download_provider_video_comments.delay(self.video.pk).get()

        self.assertEqual(1, self.video.comments.count())

    @patch("vidar.interactor.video_comments")
    def test_child_comment_without_parent_in_local_system_is_not_created(self, mock_inter):
        mock_inter.return_value = {
            "comments": [
                {
                    "id": "comment-id-1",
                    "parent": "root",
                    "timestamp": str(int(timezone.now().timestamp())),

                    "author": "Author",
                    "author_id": "author-id",
                    "author_is_uploader": False,
                    "author_thumbnail": "author-url",
                    "is_favorited": False,
                    "like_count": 0,
                    "text": "comment here in tests",
                },
                {
                    "id": "comment-id-2",
                    "parent": "comment-id-15",
                    "timestamp": str(int(timezone.now().timestamp())),

                    "author": "Author",
                    "author_id": "author-id",
                    "author_is_uploader": False,
                    "author_thumbnail": "author-url",
                    "is_favorited": False,
                    "like_count": 0,
                    "text": "comment here in tests",
                },
            ]
        }

        tasks.download_provider_video_comments.delay(self.video.pk).get()

        self.assertEqual(1, self.video.comments.count())
        comment = self.video.comments.get()
        self.assertEqual("comment-id-1", comment.pk)

    @patch("vidar.interactor.video_comments")
    def test_child_comment_with_parent_in_local_system_is_created(self, mock_inter):
        mock_inter.return_value = {
            "comments": [
                {
                    "id": "comment-id-1",
                    "parent": "root",
                    "timestamp": str(int(timezone.now().timestamp())),

                    "author": "Author",
                    "author_id": "author-id",
                    "author_is_uploader": False,
                    "author_thumbnail": "author-url",
                    "is_favorited": False,
                    "like_count": 0,
                    "text": "comment here in tests",
                },
                {
                    "id": "comment-id-2",
                    "parent": "comment-id-1",
                    "timestamp": str(int(timezone.now().timestamp())),

                    "author": "Author",
                    "author_id": "author-id",
                    "author_is_uploader": False,
                    "author_thumbnail": "author-url",
                    "is_favorited": False,
                    "like_count": 0,
                    "text": "comment here in tests",
                },
            ]
        }

        tasks.download_provider_video_comments.delay(self.video.pk).get()

        self.assertEqual(2, self.video.comments.count())
        comment1 = self.video.comments.order_by('pk').first()
        comment2 = self.video.comments.order_by('pk').last()
        self.assertEqual("comment-id-1", comment1.pk)
        self.assertEqual("comment-id-2", comment2.pk)

        self.assertEqual(comment1.pk, comment2.parent_youtube_id)


class Delete_channel_videos_tests(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            name="test channel",
            fully_indexed=True,
            fully_indexed_shorts=True,
            fully_indexed_livestreams=True,
        )
        self.video_without_file = self.channel.videos.create(title="Video without file")
        self.video_with_file = self.channel.videos.create(title="Video without file", file="test.mp4")

        self.playlist = models.Playlist.objects.create(title="playlist 1")
        self.video_with_playlist = self.channel.videos.create(title="video with playlist")
        self.playlist.playlistitem_set.create(video=self.video_with_playlist)

    @patch("vidar.services.video_services.delete_video")
    def test_not_keeping_archived_videos(self, mock_delete):
        tasks.delete_channel_videos(pk=self.channel.pk)

        mock_delete.assert_has_calls([
            call(video=self.video_without_file),
            call(video=self.video_with_file),
        ], any_order=True)

        self.channel.refresh_from_db()
        self.assertFalse(self.channel.fully_indexed)
        self.assertFalse(self.channel.fully_indexed_shorts)
        self.assertFalse(self.channel.fully_indexed_livestreams)

    @patch("vidar.services.video_services.delete_video")
    def test_keeping_archived_videos(self, mock_delete):
        tasks.delete_channel_videos(pk=self.channel.pk, keep_archived_videos=True)

        mock_delete.assert_called_with(video=self.video_without_file)

        self.channel.refresh_from_db()
        self.assertFalse(self.channel.fully_indexed)
        self.assertFalse(self.channel.fully_indexed_shorts)
        self.assertFalse(self.channel.fully_indexed_livestreams)


class Delete_channel_tests(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            name="test channel",
        )
        self.video_without_file = self.channel.videos.create(title="Video without file")
        self.video_with_file = self.channel.videos.create(title="Video without file", file="test.mp4")

        self.playlist = models.Playlist.objects.create(title="playlist 1", channel=self.channel)
        self.video_with_playlist = self.channel.videos.create(title="video with playlist")
        self.playlist.playlistitem_set.create(video=self.video_with_playlist)

    @patch("vidar.services.video_services.delete_video")
    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.services.playlist_services.delete_playlist_videos")
    @patch("vidar.services.channel_services.delete_files")
    def test_deletes_files(self, mock_delete_files, mock_delete_playlist_videos, mock_renamer, mock_delete_video):
        tasks.delete_channel(pk=self.channel.pk)
        mock_delete_files.assert_called_once()
        mock_delete_playlist_videos.assert_called_once()
        mock_renamer.assert_not_called()
        mock_delete_video.assert_has_calls((
            call(video=self.video_with_file),
            call(video=self.video_without_file).
            call(video=self.video_with_playlist),
        ), any_order=True)

    @patch("vidar.services.video_services.delete_video")
    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.services.playlist_services.delete_playlist_videos")
    @patch("vidar.services.channel_services.delete_files")
    def test_keep_archived_videos(self, mock_delete_files, mock_delete_playlist_videos, mock_renamer, mock_delete_video):
        tasks.delete_channel(pk=self.channel.pk, keep_archived_videos=True)
        mock_delete_files.assert_called_once()
        mock_delete_playlist_videos.assert_called_once()
        mock_renamer.assert_called_with(video=self.video_with_file)
        mock_delete_video.assert_has_calls((
            call(video=self.video_without_file).
            call(video=self.video_with_playlist),
        ), any_order=True)

        self.video_with_file.refresh_from_db()
        self.assertIsNone(self.video_with_file.channel)

    @patch("vidar.services.video_services.delete_video")
    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.services.playlist_services.delete_playlist_videos")
    @patch("vidar.services.channel_services.delete_files")
    def test_keep_archived_videos(self, mock_delete_files, mock_delete_playlist_videos, mock_renamer, mock_delete_video):
        tasks.delete_channel(pk=self.channel.pk, keep_archived_videos=True)
        mock_delete_files.assert_called_once()
        mock_delete_playlist_videos.assert_called_once()
        mock_renamer.assert_called_with(video=self.video_with_file)
        mock_delete_video.assert_has_calls((
            call(video=self.video_without_file).
            call(video=self.video_with_playlist),
        ), any_order=True)

        self.video_with_file.refresh_from_db()
        self.assertIsNone(self.video_with_file.channel)

    @patch("vidar.services.video_services.delete_video")
    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.services.playlist_services.delete_playlist_videos")
    @patch("vidar.services.channel_services.delete_files")
    def test_video_has_secondary_playlist(self, mock_delete_files, mock_delete_playlist_videos, mock_renamer, mock_delete_video):
        playlist2 = models.Playlist.objects.create(title="Playlist 2")
        playlist2.playlistitem_set.create(video=self.video_with_playlist)
        tasks.delete_channel(pk=self.channel.pk, keep_archived_videos=False)
        mock_delete_files.assert_called_once()
        mock_delete_playlist_videos.assert_called_once()
        mock_renamer.assert_called_with(video=self.video_with_playlist)
        mock_delete_video.assert_has_calls((
            call(video=self.video_without_file).
            call(video=self.video_with_file),
        ), any_order=True)

        self.video_with_playlist.refresh_from_db()
        self.assertIsNone(self.video_with_playlist.channel)

    @patch("vidar.services.video_services.delete_video")
    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.services.playlist_services.delete_playlist_videos")
    @patch("vidar.services.channel_services.delete_files")
    def test_video_has_secondary_playlist_keeping_archived(self, mock_delete_files, mock_delete_playlist_videos, mock_renamer, mock_delete_video):
        playlist2 = models.Playlist.objects.create(title="Playlist 2")
        playlist2.playlistitem_set.create(video=self.video_with_playlist)
        tasks.delete_channel(pk=self.channel.pk, keep_archived_videos=True)
        mock_delete_files.assert_called_once()
        mock_delete_playlist_videos.assert_called_once()
        mock_renamer.assert_has_calls((
            call(video=self.video_without_file).
            call(video=self.video_with_file),
        ), any_order=True)
        mock_delete_video.assert_called_with(video=self.video_without_file)

        self.video_without_file.refresh_from_db()
        self.assertIsNone(self.video_without_file.channel)

        self.video_with_file.refresh_from_db()
        self.assertIsNone(self.video_with_file.channel)

    @patch("vidar.services.video_services.delete_video")
    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.services.playlist_services.delete_playlist_videos")
    @patch("vidar.services.channel_services.delete_files")
    def test_renamer_raises_backend_error(self, mock_delete_files, mock_delete_playlist_videos, mock_renamer, mock_delete_video):
        mock_renamer.side_effect = exceptions.FileStorageBackendHasNoMoveError()
        tasks.delete_channel(pk=self.channel.pk, keep_archived_videos=True)
        mock_delete_files.assert_called_once()
        mock_delete_playlist_videos.assert_called_once()
        mock_renamer.assert_called_with(video=self.video_with_file)
        mock_delete_video.assert_has_calls((
            call(video=self.video_without_file).
            call(video=self.video_with_playlist),
        ), any_order=True)

        self.video_with_file.refresh_from_db()
        self.assertIsNone(self.video_with_file.channel)


class Daily_maintenances_tests(TestCase):

    @patch("vidar.signals.pre_daily_maintenance")
    @patch("vidar.signals.post_daily_maintenance")
    def test_signals_sent(self, mock_post, mock_pre):
        tasks.daily_maintenances.delay().get()
        mock_pre.send.assert_called_once()
        mock_post.send.assert_called_once()

    @patch("vidar.services.video_services.set_thumbnail")
    @patch("vidar.interactor.video_details")
    def test_archived_video_without_thumbnail_ytdlp_returns_nothing(self, mock_details, mock_setter):
        video = models.Video.objects.create(file="test.mp4")
        mock_details.return_value = {}

        tasks.daily_maintenances.delay().get()

        mock_details.assert_called_once()
        mock_setter.assert_not_called()

    @patch("vidar.services.video_services.set_thumbnail")
    @patch("vidar.interactor.video_details")
    def test_archived_video_without_thumbnail_obtains_one(self, mock_details, mock_setter):
        video = models.Video.objects.create(file="test.mp4")
        mock_details.return_value = {"thumbnail": "..."}

        tasks.daily_maintenances.delay().get()

        mock_details.assert_called_once()
        mock_setter.assert_called_once()

    @patch("vidar.services.video_services.set_thumbnail")
    @patch("vidar.interactor.video_details")
    def test_archived_video_without_thumbnail_fails(self, mock_details, mock_setter):
        mock_setter.side_effect = requests.exceptions.RequestException()
        video = models.Video.objects.create(file="test.mp4")
        mock_details.return_value = {"thumbnail": "..."}

        with self.assertLogs("vidar.tasks") as logger:
            tasks.daily_maintenances.delay().get()

        self.assertIn("failure to set thumbnail", logger.output[-1])
        mock_details.assert_called_once()
        mock_setter.assert_called_once()

    @patch("vidar.services.video_services.delete_video")
    def test_delete_videos_marked_for_deletion(self, mock_deleted):
        video = models.Video.objects.create(mark_for_deletion=True)
        tasks.daily_maintenances.delay().get()
        mock_deleted.assert_called_with(video=video)

    @patch("vidar.services.video_services.delete_video")
    def test_delete_videos_marked_for_deletion_fails(self, mock_deleted):
        mock_deleted.side_effect = ValueError("failed for some reason")
        video = models.Video.objects.create(mark_for_deletion=True)

        with self.assertLogs("vidar.tasks") as logger:
            tasks.daily_maintenances.delay().get()

        self.assertIn("Failed to delete", logger.output[-1])
        mock_deleted.assert_called_with(video=video)

    @patch("vidar.tasks.convert_video_to_audio")
    def test_video_wants_audio(self, mock_task):

        video = models.Video.objects.create(convert_to_audio=True, thumbnail="thumbnail.jpg", file="test.mp4")

        tasks.daily_maintenances.delay().get()

        mock_task.delay.assert_called_once()

    @patch("vidar.tasks.convert_video_to_audio")
    def test_channel_wants_audio(self, mock_task):

        channel = models.Channel.objects.create(
            convert_videos_to_mp3=True,
        )

        video = channel.videos.create(file="test.mp4", thumbnail="thumbnail.jpg",)

        tasks.daily_maintenances.delay().get()

        mock_task.delay.assert_called_once()

    @patch("vidar.tasks.convert_video_to_audio")
    def test_playlist_wants_audio(self, mock_task):

        playlist = models.Playlist.objects.create(
            convert_to_audio=True,
        )

        video = models.Video.objects.create(file="test.mp4", thumbnail="thumbnail.jpg",)

        playlist.videos.add(video)

        tasks.daily_maintenances.delay().get()

        mock_task.delay.assert_called_once()

    @patch("vidar.services.video_services.delete_video")
    def test_delete_videos_after_watching(self, mock_deleter):

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_videos_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_video=True,
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_called_with(video=video, keep_record=True)

    @patch("vidar.services.video_services.delete_video")
    def test_delete_videos_after_watching_keep_starred(self, mock_deleter):

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_videos_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_video=True,
            starred=timezone.now(),
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_not_called()

    @patch("vidar.services.video_services.delete_video")
    def test_delete_videos_after_watching_fails(self, mock_deleter):

        mock_deleter.side_effect = ValueError("test failure to delete")

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_videos_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_video=True,
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        with self.assertLogs("vidar.tasks") as logger:
            tasks.daily_maintenances.delay().get()
        self.assertIn("Failed to delete video", logger.output[-1])

    @patch("vidar.services.video_services.delete_video")
    def test_delete_shorts_after_watching(self, mock_deleter):

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_shorts_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_short=True,
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_called_with(video=video, keep_record=True)

    @patch("vidar.services.video_services.delete_video")
    def test_delete_shorts_after_watching_keep_starred(self, mock_deleter):

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_shorts_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_short=True,
            starred=timezone.now(),
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_not_called()

    @patch("vidar.services.video_services.delete_video")
    def test_delete_shorts_after_watching_fails(self, mock_deleter):

        mock_deleter.side_effect = ValueError("test failure to delete")

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_shorts_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_short=True,
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        with self.assertLogs("vidar.tasks") as logger:
            tasks.daily_maintenances.delay().get()
        self.assertIn("Failed to delete video", logger.output[-1])

    @patch("vidar.services.video_services.delete_video")
    def test_delete_livestreams_after_watching(self, mock_deleter):

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_livestreams_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_livestream=True,
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_called_with(video=video, keep_record=True)

    @patch("vidar.services.video_services.delete_video")
    def test_delete_livestreams_after_watching_keep_starred(self, mock_deleter):

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_livestreams_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_livestream=True,
            starred=timezone.now(),
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_not_called()

    @patch("vidar.services.video_services.delete_video")
    def test_delete_livestreams_after_watching_fails(self, mock_deleter):
        mock_deleter.side_effect = ValueError("test failure to delete")

        user = User.objects.create(username='test', password="password")

        channel = models.Channel.objects.create(delete_livestreams_after_watching=True)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            duration=100,
            is_livestream=True,
        )

        models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=90)

        with self.assertLogs("vidar.tasks") as logger:
            tasks.daily_maintenances.delay().get()
        self.assertIn("Failed to delete video", logger.output[-1])

    @patch("vidar.services.video_services.delete_video")
    def test_delete_videos_after_days(self, mock_deleter):

        channel = models.Channel.objects.create(delete_videos_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_video=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        video2 = channel.videos.create(
            file="test2.mp4",
            thumbnail="thumbnail2.jpg",
            is_video=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=1)
        )

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_called_with(video=video, keep_record=True)

    @patch("vidar.services.video_services.delete_video")
    def test_delete_videos_after_days_keep_starred(self, mock_deleter):

        channel = models.Channel.objects.create(delete_videos_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_video=True,
            starred=timezone.now(),
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        video2 = channel.videos.create(
            file="test2.mp4",
            thumbnail="thumbnail2.jpg",
            is_video=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=1)
        )

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_not_called()

    @patch("vidar.services.video_services.delete_video")
    def test_delete_videos_after_days_fails(self, mock_deleter):
        mock_deleter.side_effect = ValueError("test failure to delete")

        channel = models.Channel.objects.create(delete_videos_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_video=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        tasks.daily_maintenances.delay().get()

        with self.assertLogs("vidar.tasks") as logger:
            tasks.daily_maintenances.delay().get()
        self.assertIn("Failed to delete video", logger.output[-1])

    @patch("vidar.services.video_services.delete_video")
    def test_delete_shorts_after_days(self, mock_deleter):

        channel = models.Channel.objects.create(delete_shorts_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_short=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        video2 = channel.videos.create(
            file="test2.mp4",
            thumbnail="thumbnail2.jpg",
            is_short=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=1)
        )

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_called_with(video=video, keep_record=True)

    @patch("vidar.services.video_services.delete_video")
    def test_delete_shorts_after_days_keep_starred(self, mock_deleter):

        channel = models.Channel.objects.create(delete_shorts_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_short=True,
            starred=timezone.now(),
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        video2 = channel.videos.create(
            file="test2.mp4",
            thumbnail="thumbnail2.jpg",
            is_short=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=1)
        )

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_not_called()

    @patch("vidar.services.video_services.delete_video")
    def test_delete_shorts_after_days_fails(self, mock_deleter):
        mock_deleter.side_effect = ValueError("test failure to delete")

        channel = models.Channel.objects.create(delete_shorts_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_short=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        tasks.daily_maintenances.delay().get()

        with self.assertLogs("vidar.tasks") as logger:
            tasks.daily_maintenances.delay().get()
        self.assertIn("Failed to delete video", logger.output[-1])

    @patch("vidar.services.video_services.delete_video")
    def test_delete_livestreams_after_days(self, mock_deleter):

        channel = models.Channel.objects.create(delete_livestreams_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_livestream=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        video2 = channel.videos.create(
            file="test2.mp4",
            thumbnail="thumbnail2.jpg",
            is_livestream=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=1)
        )

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_called_with(video=video, keep_record=True)

    @patch("vidar.services.video_services.delete_video")
    def test_delete_livestreams_after_days_keep_starred(self, mock_deleter):

        channel = models.Channel.objects.create(delete_livestreams_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_livestream=True,
            starred=timezone.now(),
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        video2 = channel.videos.create(
            file="test2.mp4",
            thumbnail="thumbnail2.jpg",
            is_livestream=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=1)
        )

        tasks.daily_maintenances.delay().get()

        mock_deleter.assert_not_called()

    @patch("vidar.services.video_services.delete_video")
    def test_delete_livestreams_after_days_fails(self, mock_deleter):
        mock_deleter.side_effect = ValueError("test failure to delete")

        channel = models.Channel.objects.create(delete_livestreams_after_days=2)

        video = channel.videos.create(
            file="test.mp4",
            thumbnail="thumbnail.jpg",
            is_livestream=True,
            date_downloaded=timezone.now() - timezone.timedelta(days=4)
        )

        tasks.daily_maintenances.delay().get()

        with self.assertLogs("vidar.tasks") as logger:
            tasks.daily_maintenances.delay().get()
        self.assertIn("Failed to delete video", logger.output[-1])


class Channel_rename_files_tests(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(name="Test Channel")

    @patch("vidar.renamers.channel_rename_all_files")
    def test_success(self, mock_renamer):
        tasks.channel_rename_files.delay(channel_id=self.channel.pk).get()

        mock_renamer.assert_called_once()

    @patch("vidar.renamers.channel_rename_all_files")
    def test_backend_has_no_move(self, mock_renamer):
        mock_renamer.side_effect = exceptions.FileStorageBackendHasNoMoveError()

        with self.assertRaises(exceptions.FileStorageBackendHasNoMoveError):
            tasks.channel_rename_files.delay(channel_id=self.channel.pk).get()


class Rename_all_archived_video_files_tests(TestCase):

    def test_resets_file_not_found_flag(self):
        video = models.Video.objects.create(file_not_found=True)
        tasks.rename_all_archived_video_files.delay().get()

        video.refresh_from_db()

        self.assertFalse(video.file_not_found)

    @patch("vidar.helpers.file_helpers.can_file_be_moved")
    def test_storage_has_no_move(self, mock_can):
        mock_can.return_value = False

        with self.assertRaises(exceptions.FileStorageBackendHasNoMoveError):
            tasks.rename_all_archived_video_files.delay().get()

    @patch("vidar.tasks.rename_video_files")
    def test_video_has_file_no_need_to_rename(self, mock_renamer):
        video = models.Video.objects.create(
            title="Test Video",
            provider_object_id="video-id",
            file="public/2025/2025-01-23 - Test Video [video-id].mp4",
            upload_date=date_to_aware_date('2025-01-23')
        )

        tasks.rename_all_archived_video_files.delay().get()

        mock_renamer.delay.assert_not_called()

    @patch("vidar.tasks.rename_video_files")
    def test_videos_one_has_file_no_need_to_rename_other_needs_fixing(self, mock_renamer):
        video = models.Video.objects.create(
            title="Test Video",
            provider_object_id="video-id",
            file="public/2025/2025-01-23 - Test Video [video-id].mp4",
            upload_date=date_to_aware_date('2025-01-23')
        )
        video = models.Video.objects.create(
            title="Test Video 2",
            provider_object_id="video-id-2",
            file="test 2.mp4",
            upload_date=date_to_aware_date('2025-01-23')
        )

        tasks.rename_all_archived_video_files.delay().get()

        mock_renamer.delay.assert_called_once_with(pk=video.pk, commit=True, remove_empty=True)


class Rename_video_files_tests(TestCase):

    @patch("vidar.helpers.file_helpers.can_file_be_moved")
    def test_storage_has_no_move(self, mock_can):
        mock_can.return_value = False

        output = tasks.rename_video_files.delay(pk=0)
        task_output = output.get()
        self.assertIsNone(task_output)
        self.assertEqual(celery.states.IGNORED, output.status)

    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.helpers.file_helpers.can_file_be_moved")
    def test_video_has_no_file(self, mock_can, mock_renamer):
        mock_can.return_value = True
        video = models.Video.objects.create()

        output = tasks.rename_video_files.delay(pk=video.pk)
        task_output = output.get()

        self.assertEqual(celery.states.IGNORED, output.status)
        self.assertIsNone(task_output)
        mock_renamer.assert_not_called()

    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.helpers.file_helpers.can_file_be_moved")
    def test_renamer_raises_backend_error(self, mock_can, mock_renamer):
        mock_can.return_value = True
        mock_renamer.side_effect = exceptions.FileStorageBackendHasNoMoveError()
        video = models.Video.objects.create(file="test.mp4")

        output = tasks.rename_video_files.delay(pk=video.pk)
        task_output = output.get()

        self.assertEqual(celery.states.IGNORED, output.status)
        self.assertIsNone(task_output)
        mock_renamer.assert_called_once()

    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.helpers.file_helpers.can_file_be_moved")
    def test_renamer_raises_filenotfounderror(self, mock_can, mock_renamer):
        mock_can.return_value = True
        mock_renamer.side_effect = FileNotFoundError()
        video = models.Video.objects.create(file="test.mp4")

        with self.assertRaises(FileNotFoundError):
            tasks.rename_video_files.delay(pk=video.pk).get()

        video.refresh_from_db()

        self.assertTrue(video.file_not_found)

    @patch("vidar.renamers.video_rename_all_files")
    @patch("vidar.helpers.file_helpers.can_file_be_moved")
    def test_successful(self, mock_can, mock_renamer):
        mock_can.return_value = True
        mock_renamer.return_value = True
        video = models.Video.objects.create(file="test.mp4")

        output = tasks.rename_video_files.delay(pk=video.pk)
        task_output = output.get()

        self.assertEqual(celery.states.SUCCESS, output.status)
        self.assertTrue(task_output)
        mock_renamer.assert_called_once()


class Convert_video_to_mp4_tests(TestCase):

    @patch("vidar.services.redis_services.video_conversion_to_mp4_started")
    def test_filepath_is_not_valid_for_conversion(self, mock_redis_start):
        video = models.Video.objects.create(file="test.mp4")
        output = tasks.convert_video_to_mp4.delay(
            pk=video.pk,
            filepath=video.file.name,
        ).get()
        self.assertEqual("test.mp4", output)

        mock_redis_start.assert_not_called()

    @patch("vidar.services.redis_services.video_conversion_to_mp4_finished")
    @patch("vidar.services.redis_services.video_conversion_to_mp4_started")
    @patch("vidar.services.notification_services.convert_to_mp4_complete")
    @patch("moviepy.VideoFileClip")
    @patch("tempfile.mkstemp")
    @patch("vidar.helpers.file_helpers.ensure_file_is_local")
    def test_successful(self, mock_ensure, mock_mkstemp, mock_moviepy, mock_notif_finished, mock_redis_started, mock_redis_finished):
        clipper = MagicMock()
        mock_moviepy.return_value = clipper
        video = models.Video.objects.create(file="test.mkv")

        mock_mkstemp.return_value = ("", "output dir/test.mp4")

        output = tasks.convert_video_to_mp4.delay(
            pk=video.pk,
            filepath=video.file.name,
        ).get()

        self.assertEqual("output dir/test.mp4", output)

        mock_moviepy.assert_called_once_with("test.mkv")
        clipper.write_videofile.assert_called_once_with("output dir/test.mp4")

        mock_notif_finished.assert_called_once()
        mock_redis_started.assert_called_once()
        mock_redis_finished.assert_called_once()
        mock_ensure.assert_not_called()

        video.refresh_from_db()

        self.assertIn("convert_video_to_mp4_started", video.system_notes)
        self.assertIn("convert_video_to_mp4_finished", video.system_notes)

    @patch("vidar.services.redis_services.video_conversion_to_mp4_finished")
    @patch("vidar.services.redis_services.video_conversion_to_mp4_started")
    @patch("vidar.services.notification_services.convert_to_mp4_complete")
    @patch("moviepy.VideoFileClip")
    @patch("tempfile.mkstemp")
    @patch("vidar.helpers.file_helpers.ensure_file_is_local")
    def test_successful_when_not_passing_filepath(self, mock_ensure, mock_mkstemp, mock_moviepy, mock_notif_finished, mock_redis_started, mock_redis_finished):
        clipper = MagicMock()
        mock_moviepy.return_value = clipper
        mock_ensure.return_value = "test.mkv", False
        video = models.Video.objects.create(file="test.mkv")

        mock_mkstemp.return_value = ("", "output dir/test.mp4")

        output = tasks.convert_video_to_mp4.delay(pk=video.pk).get()

        self.assertEqual("output dir/test.mp4", output)

        mock_moviepy.assert_called_once_with("test.mkv")
        clipper.write_videofile.assert_called_once_with("output dir/test.mp4")

        mock_notif_finished.assert_called_once()
        mock_redis_started.assert_called_once()
        mock_redis_finished.assert_called_once()
        mock_ensure.assert_called_once()

        video.refresh_from_db()

        self.assertIn("convert_video_to_mp4_started", video.system_notes)
        self.assertIn("convert_video_to_mp4_finished", video.system_notes)


class Monthly_maintenances_tests(TestCase):

    @patch("vidar.signals.pre_monthly_maintenance")
    @patch("vidar.signals.post_monthly_maintenance")
    def test_signals_sent(self, mock_post, mock_pre):
        tasks.monthly_maintenances.delay().get()
        mock_pre.send.assert_called_once()
        mock_post.send.assert_called_once()

    @override_settings(VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=True)
    @patch("vidar.tasks.update_channel_banners")
    def test_only_indexing_channels_get_banner_updates(self, mock_banner):
        channel1 = models.Channel.objects.create(index_videos=True, index_shorts=False, index_livestreams=False)
        channel2 = models.Channel.objects.create(index_videos=False, index_shorts=False, index_livestreams=False)

        tasks.monthly_maintenances.delay().get()

        mock_banner.apply_async.assert_called_with(args=[channel1.pk], countdown=0)

    @override_settings(VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False)
    @patch("vidar.tasks.update_channel_banners")
    def test_only_indexing_channels_get_banner_updates_system_disabled(self, mock_banner):
        channel1 = models.Channel.objects.create(index_videos=True, index_shorts=False, index_livestreams=False)
        channel2 = models.Channel.objects.create(index_videos=False, index_shorts=False, index_livestreams=False)

        tasks.monthly_maintenances.delay().get()

        mock_banner.apply_async.assert_not_called()

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=True,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=False,
    )
    @patch("vidar.helpers.statistics_helpers.most_common_date_weekday")
    def test_crontab_balancing_skip_channels_with_daily_crontab(self, mock_stats_dow):
        mock_stats_dow.return_value = 2
        channel1 = models.Channel.objects.create(index_videos=True, scanner_crontab="* * * * *")

        tasks.monthly_maintenances.delay().get()

        mock_stats_dow.assert_not_called()

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=True,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=False,
    )
    @patch("vidar.helpers.statistics_helpers.most_common_date_weekday")
    def test_crontab_balancing_skip_channels_with_no_videos(self, mock_stats_dow):
        mock_stats_dow.return_value = 2
        channel1 = models.Channel.objects.create(index_videos=True, scanner_crontab="* * * * 4")

        tasks.monthly_maintenances.delay().get()

        mock_stats_dow.assert_not_called()

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=True,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=False,
    )
    @patch("vidar.helpers.statistics_helpers.most_common_date_weekday")
    def test_crontab_balancing_channels_with_large_upload_date_range(self, mock_stats_dow):
        mock_stats_dow.return_value = 2
        old_crontab = "10 4 * * 4"
        channel = models.Channel.objects.create(index_videos=True, scanner_crontab=old_crontab)

        channel.videos.create(upload_date=date_to_aware_date("2024-01-01"))
        channel.videos.create(upload_date=date_to_aware_date("2024-05-10"))

        tasks.monthly_maintenances.delay().get()

        mock_stats_dow.assert_called_once()

        channel.refresh_from_db()

        self.assertNotEqual(old_crontab, channel.scanner_crontab)
        self.assertRegex(channel.scanner_crontab, r'^\d+ \d+ \* \* 3$')

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=False,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=True,
    )
    @patch("vidar.tasks.rename_all_archived_video_files")
    def test_rename_all_files_calls_task(self, mock_task):
        tasks.monthly_maintenances.delay().get()
        mock_task.assert_called_once()

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=False,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=True,
    )
    @patch("vidar.tasks.rename_all_archived_video_files")
    def test_rename_all_files_calls_task_but_backend_failures(self, mock_task):
        mock_task.side_effect = exceptions.FileStorageBackendHasNoMoveError()
        with self.assertLogs("vidar.tasks") as logger:
            tasks.monthly_maintenances.delay().get()
            expected_log_msg = "Failure to confirm filenames are correct as File backend does not support move."
            log_has_line = any([True for x in logger.output if expected_log_msg in x])
            self.assertTrue(log_has_line, "logger did not capture FileStorageBackendHasNoMoveError error.")

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=False,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=False,
        VIDAR_MONTHLY_CLEAR_DLP_FORMATS=True
    )
    def test_clear_old_dlp_formats_from_videos(self):
        video1 = models.Video.objects.create(dlp_formats={"test": "here"}, upload_date=date_to_aware_date("2023-04-01"))
        video2 = models.Video.objects.create(upload_date=date_to_aware_date("2024-04-01"))
        video3 = models.Video.objects.create(dlp_formats={"test": "here"}, upload_date=timezone.now().date())

        tasks.monthly_maintenances.delay().get()

        video1.refresh_from_db()
        video2.refresh_from_db()
        video3.refresh_from_db()

        self.assertIsNone(video1.dlp_formats)
        self.assertIsNone(video2.dlp_formats)
        self.assertDictEqual({"test": "here"}, video3.dlp_formats)

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=False,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=False,
        VIDAR_MONTHLY_CLEAR_DLP_FORMATS=False,
    )
    def test_clear_old_dlp_formats_from_videos_system_disabled(self):
        video1 = models.Video.objects.create(dlp_formats={"test": "here"}, upload_date=date_to_aware_date("2023-04-01"))
        video2 = models.Video.objects.create(upload_date=date_to_aware_date("2024-04-01"))
        video3 = models.Video.objects.create(dlp_formats={"test": "here"}, upload_date=timezone.now().date())

        tasks.monthly_maintenances.delay().get()

        video1.refresh_from_db()
        video2.refresh_from_db()
        video3.refresh_from_db()

        self.assertDictEqual({"test": "here"}, video1.dlp_formats)
        self.assertIsNone(video2.dlp_formats)
        self.assertDictEqual({"test": "here"}, video3.dlp_formats)

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=False,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=False,
        VIDAR_MONTHLY_ASSIGN_OLDEST_THUMBNAILS_TO_CHANNEL_YEAR_DIRECTORY=True
    )
    @patch("vidar.oneoffs.assign_oldest_thumbnail_to_channel_year_directories")
    def test_assign_oldest_thumbnails(self, mock_func):
        tasks.monthly_maintenances.delay().get()

        mock_func.assert_called_once()

    @override_settings(
        VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS=False,
        VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING=False,
        VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT=False,
        VIDAR_MONTHLY_ASSIGN_OLDEST_THUMBNAILS_TO_CHANNEL_YEAR_DIRECTORY=True
    )
    @patch("vidar.oneoffs.assign_oldest_thumbnail_to_channel_year_directories")
    def test_assign_oldest_thumbnails_fails_backend_error(self, mock_func):
        mock_func.side_effect = exceptions.FileStorageBackendHasNoMoveError()
        tasks.monthly_maintenances.delay().get()

        mock_func.assert_called_once()


class Convert_video_to_audio_tests(TestCase):

    @patch("moviepy.VideoFileClip")
    @patch("tempfile.mkstemp")
    @patch("vidar.helpers.file_helpers.ensure_file_is_local")
    def test_successful(self, mock_ensure, mock_mkstemp, mock_moviepy):
        clipper = MagicMock()
        mock_moviepy.return_value = clipper
        video = models.Video.objects.create(file="test.mp4")

        mock_mkstemp.return_value = ("", "output dir/test.mp3")

        output = tasks.convert_video_to_audio.delay(
            pk=video.pk,
            filepath=video.file.name,
            return_filepath=True
        ).get()

        self.assertEqual("output dir/test.mp3", output)

        mock_moviepy.assert_called_once_with("test.mp4")
        clipper.audio.write_audiofile.assert_called_once_with("output dir/test.mp3", logger=None)

        mock_ensure.assert_not_called()

        video.refresh_from_db()

        self.assertIn("convert_video_to_audio_started", video.system_notes)
        self.assertIn("convert_video_to_audio_finished", video.system_notes)

    @patch("os.unlink")
    @patch("moviepy.VideoFileClip")
    @patch("tempfile.mkstemp")
    @patch("vidar.helpers.file_helpers.ensure_file_is_local")
    def test_successful_when_not_passing_filepath(self, mock_ensure, mock_mkstemp, mock_moviepy, mock_unlink):
        clipper = MagicMock()
        mock_moviepy.return_value = clipper
        mock_ensure.return_value = "test.mp4", True
        video = models.Video.objects.create(file="test.mp4")

        mock_mkstemp.return_value = ("", "output dir/test.mp3")

        output = tasks.convert_video_to_audio.delay(pk=video.pk, return_filepath=True).get()

        self.assertEqual("output dir/test.mp3", output)

        mock_moviepy.assert_called_once_with("test.mp4")
        clipper.audio.write_audiofile.assert_called_once_with("output dir/test.mp3", logger=None)

        mock_ensure.assert_called_once()
        mock_unlink.assert_called_once()

    @patch("vidar.tasks.write_file_to_storage")
    @patch("vidar.tasks.delete_cached_file")
    @patch("moviepy.VideoFileClip")
    @patch("tempfile.mkstemp")
    @patch("vidar.helpers.file_helpers.ensure_file_is_local")
    def test_successful_writes_direct_to_drive(self, mock_ensure, mock_mkstemp, mock_moviepy, mock_delete, mock_write):
        clipper = MagicMock()
        mock_moviepy.return_value = clipper
        video = models.Video.objects.create(file="test.mp4")

        mock_mkstemp.return_value = ("", "output dir/test.mp3")

        output = tasks.convert_video_to_audio.delay(
            pk=video.pk,
            filepath=video.file.name,
        ).get()

        self.assertTrue(output)

        mock_moviepy.assert_called_once_with("test.mp4")
        clipper.audio.write_audiofile.assert_called_once_with("output dir/test.mp3", logger=None)

        mock_ensure.assert_not_called()
        mock_delete.s.assert_called_once()
        mock_write.s.assert_called_once()

        video.refresh_from_db()

        self.assertIn("convert_video_to_audio_started", video.system_notes)
        self.assertIn("convert_video_to_audio_finished", video.system_notes)


class Slow_full_archive_test(TestCase):

    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(
            slow_full_archive=True,
            index_videos=True,
            fully_indexed=True,
        )


    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.tasks.fully_index_channel")
    def test_channel_not_fully_indexed_calls_full_indexer(self, mock_task, mock_dl):
        self.channel.fully_indexed = False
        self.channel.save()

        output = tasks.slow_full_archive.delay().get()
        self.assertEqual(0, output)

        mock_task.delay.assert_called_with(pk=self.channel.pk)
        mock_dl.delay.assert_not_called()

    @override_settings(VIDAR_SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT=2)
    @patch("vidar.tasks.download_provider_video")
    def test_downloads_system_limit(self, mock_dl):
        v1 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        v2 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        v3 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        output = tasks.slow_full_archive.delay().get()
        self.assertEqual(2, output)

        mock_dl.delay.assert_has_calls([
            call(pk=v1.pk, task_source="automated_archiver - Channel Slow Full Archive", requested_by="Channel Slow Full Archive",),
            call(pk=v2.pk, task_source="automated_archiver - Channel Slow Full Archive", requested_by="Channel Slow Full Archive", ),
        ])

    @override_settings(VIDAR_SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT=2)
    @patch("vidar.tasks.download_provider_video")
    def test_downloads_skips_ones_with_errors(self, mock_dl):
        v1 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        v2 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        v3 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        v2.download_errors.create()

        output = tasks.slow_full_archive.delay().get()
        self.assertEqual(2, output)

        mock_dl.delay.assert_has_calls([
            call(pk=v1.pk, task_source="automated_archiver - Channel Slow Full Archive", requested_by="Channel Slow Full Archive",),
            call(pk=v3.pk, task_source="automated_archiver - Channel Slow Full Archive", requested_by="Channel Slow Full Archive", ),
        ])

    @override_settings(VIDAR_SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT=2)
    @patch("vidar.tasks.download_provider_video")
    def test_downloads_skips_celery_locked_objects(self, mock_dl):
        v1 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        v2 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        v3 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        celery_helpers.object_lock_acquire(obj=v1, timeout=1)

        output = tasks.slow_full_archive.delay().get()
        self.assertEqual(2, output)

        mock_dl.delay.assert_has_calls([
            call(pk=v2.pk, task_source="automated_archiver - Channel Slow Full Archive",
                 requested_by="Channel Slow Full Archive", ),
            call(pk=v3.pk, task_source="automated_archiver - Channel Slow Full Archive",
                 requested_by="Channel Slow Full Archive", ),
        ])

    @override_settings(VIDAR_SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT=2)
    @patch("vidar.tasks.download_provider_video")
    def test_downloads_videos_within_cutoff_period(self, mock_dl):

        self.channel.full_archive_cutoff = date_to_aware_date("2023-06-14")
        self.channel.save()

        v1 = self.channel.videos.create(upload_date=date_to_aware_date("2023-01-01"))
        v2 = self.channel.videos.create(upload_date=date_to_aware_date("2024-01-02"))
        v3 = self.channel.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        output = tasks.slow_full_archive.delay().get()
        self.assertEqual(2, output)

        mock_dl.delay.assert_has_calls([
            call(pk=v2.pk, task_source="automated_archiver - Channel Slow Full Archive",
                 requested_by="Channel Slow Full Archive", ),
            call(pk=v3.pk, task_source="automated_archiver - Channel Slow Full Archive",
                 requested_by="Channel Slow Full Archive", ),
        ])

    @override_settings(VIDAR_SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT=2)
    @patch("vidar.services.notification_services.full_archiving_completed")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_without_videos_to_download_finishes(self, mock_dl, mock_notif):
        output = tasks.slow_full_archive.delay().get()
        self.assertEqual(0, output)

        mock_dl.assert_not_called()
        mock_notif.assert_called_once()

        self.channel.refresh_from_db()

        self.assertFalse(self.channel.full_archive)
        self.assertFalse(self.channel.slow_full_archive)
        self.assertTrue(self.channel.send_download_notification)
        self.assertTrue(self.channel.fully_indexed)
