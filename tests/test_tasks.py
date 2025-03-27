import datetime

import yt_dlp

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from django_celery_results.models import TaskResult

from vidar import models, tasks, app_settings
from vidar.helpers import channel_helpers
from vidar.services import crontab_services


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
