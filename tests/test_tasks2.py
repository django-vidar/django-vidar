import datetime
import logging

import celery.states
import requests.exceptions
import yt_dlp

from unittest.mock import call, patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model

from vidar import models, tasks, app_settings, exceptions
from vidar.helpers import channel_helpers, celery_helpers
from vidar.services import crontab_services

from .test_functions import date_to_aware_date

User = get_user_model()


class Automated_archiver_tests(TestCase):

    @patch("vidar.tasks.fully_index_channel")
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.services.notification_services.full_archiving_started")
    def test_channel_full_archive_enabled_with_full_archive_after(self, mock_notif, mock_dl, mock_indexer):
        channel = models.Channel.objects.create(
            full_archive_after=date_to_aware_date("2024-05-06"),
        )

        tasks.automated_archiver.delay().get()

        channel.refresh_from_db()

        self.assertIsNone(channel.full_archive_after)
        self.assertTrue(channel.full_archive)
        self.assertFalse(channel.slow_full_archive)
        self.assertFalse(channel.send_download_notification)

        mock_notif.assert_called_once()
        mock_dl.delay.assert_not_called()
        mock_indexer.delay.assert_called_once_with(pk=channel.pk)

    @patch("vidar.tasks.fully_index_channel")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_full_index_with_full_index_after(self, mock_dl, mock_task):
        channel = models.Channel.objects.create(
            full_index_after=date_to_aware_date("2024-05-06"),
        )

        tasks.automated_archiver.delay().get()

        channel.refresh_from_db()

        self.assertIsNone(channel.full_index_after)

        mock_task.delay.assert_called_with(pk=channel.pk)
        mock_dl.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video")
    def test_channel_sets_index_videos_with_swap_index_videos_after(self, mock_dl):
        channel = models.Channel.objects.create(
            swap_index_videos_after=date_to_aware_date("2024-05-06"),
            index_videos=False,
        )

        tasks.automated_archiver.delay().get()

        channel.refresh_from_db()

        self.assertIsNone(channel.swap_index_videos_after)
        self.assertTrue(channel.index_videos)

        mock_dl.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video")
    def test_channel_sets_index_shorts_with_swap_index_shorts_after(self, mock_dl):
        channel = models.Channel.objects.create(
            swap_index_shorts_after=date_to_aware_date("2024-05-06"),
            index_shorts=False,
        )

        tasks.automated_archiver.delay().get()

        channel.refresh_from_db()

        self.assertIsNone(channel.swap_index_shorts_after)
        self.assertTrue(channel.index_shorts)

        mock_dl.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video")
    def test_channel_sets_index_livestreams_with_swap_index_livestreams_after(self, mock_dl):
        channel = models.Channel.objects.create(
            swap_index_livestreams_after=date_to_aware_date("2024-05-06"),
            index_livestreams=False,
        )

        tasks.automated_archiver.delay().get()

        channel.refresh_from_db()

        self.assertIsNone(channel.swap_index_livestreams_after)
        self.assertTrue(channel.index_livestreams)

        mock_dl.delay.assert_not_called()

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=2,
    )
    @patch("vidar.tasks.fully_index_channel")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_at_max_downloads_for_the_day(self, mock_dl, mock_indexer):
        channel = models.Channel.objects.create(
            fully_indexed=True,
            full_archive=True,
        )

        channel.videos.create(date_downloaded=timezone.now(), file="test.mp4")
        channel.videos.create(date_downloaded=timezone.now(), file="test.mp4")
        channel.videos.create()

        with self.assertLogs("vidar.tasks") as logger:
            tasks.automated_archiver.delay().get()
            expected_log_msg = "Max daily automated downloads reached."
            log_has_line = any([True for x in logger.output if expected_log_msg in x])
            self.assertTrue(log_has_line, "automated_archiver downloaded more videos than system config allows")

        mock_indexer.delay.assert_not_called()
        mock_dl.delay.assert_not_called()

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=2,
    )
    @patch("vidar.tasks.fully_index_channel")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_downloads_limit_per_call(self, mock_dl, mock_indexer):
        channel = models.Channel.objects.create(fully_indexed=True, full_archive=True)

        video1 = channel.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = channel.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = channel.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        tasks.automated_archiver.delay().get()

        mock_indexer.delay.assert_not_called()
        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}",),
            call(pk=video2.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}", )
        ])

        mock_dl.reset_mock()

        video1.file = "test.mp4"
        video1.date_downloaded = timezone.now()
        video1.save()
        video2.file = "test.mp4"
        video2.date_downloaded = timezone.now()
        video2.save()

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_called_once_with(
            pk=video3.pk,
            task_source="automated_archiver - Channel Full Archive",
            requested_by=f"Full Archive: {channel!r}",
        )

    @patch("vidar.tasks.fully_index_channel")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_downloads_videos_after_full_archive_cutoff(self, mock_dl, mock_indexer):
        channel = models.Channel.objects.create(
            fully_indexed=True, full_archive=True,
            full_archive_cutoff=date_to_aware_date("2024-01-01")
        )

        video1 = channel.videos.create(upload_date=date_to_aware_date("2023-01-01"))
        video2 = channel.videos.create(upload_date=date_to_aware_date("2024-06-02"))
        video3 = channel.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        tasks.automated_archiver.delay().get()

        mock_indexer.delay.assert_not_called()
        mock_dl.delay.assert_has_calls([
            call(pk=video2.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}",),
            call(pk=video3.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}", )
        ])

    @patch("vidar.tasks.fully_index_channel")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_video_with_download_errors_skipped(self, mock_dl, mock_indexer):
        channel = models.Channel.objects.create(fully_indexed=True, full_archive=True)

        video1 = channel.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = channel.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = channel.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        video2.download_errors.create()

        tasks.automated_archiver.delay().get()

        mock_indexer.delay.assert_not_called()
        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}",),
            call(pk=video3.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}", )
        ])

    @patch("vidar.tasks.fully_index_channel")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_video_with_celery_lock_skipped(self, mock_dl, mock_indexer):
        channel = models.Channel.objects.create(fully_indexed=True, full_archive=True)

        video1 = channel.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = channel.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = channel.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        celery_helpers.object_lock_acquire(obj=video2, timeout=1)

        tasks.automated_archiver.delay().get()

        mock_indexer.delay.assert_not_called()
        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}",),
            call(pk=video3.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}", )
        ])

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=6,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT=30
    )
    @patch("vidar.tasks.download_provider_video")
    def test_channel_downloads_limit_halved_with_video_duration_too_long(self, mock_dl):
        channel = models.Channel.objects.create(fully_indexed=True, full_archive=True)

        video1 = channel.videos.create(upload_date=date_to_aware_date("2025-01-01"), duration=100)
        video2 = channel.videos.create(upload_date=date_to_aware_date("2025-01-02"), duration=100)
        video3 = channel.videos.create(upload_date=date_to_aware_date("2025-01-03"), duration=100)
        video4 = channel.videos.create(upload_date=date_to_aware_date("2025-01-04"), duration=100)

        with self.assertLogs("vidar.utils") as logger:
            tasks.automated_archiver.delay().get()
            expected_log_msg = "Halving max automated downloads"
            log_has_line = any([True for x in logger.output if expected_log_msg in x])
            self.assertTrue(log_has_line, "automated_archiver should have divided the download limit in half")

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}",),
            call(pk=video2.pk, task_source="automated_archiver - Channel Full Archive", requested_by=f"Full Archive: {channel!r}", )
        ])

    @patch("vidar.services.notification_services.full_archiving_completed")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_full_archive_disabled_after_all_videos_done(self, mock_dl, mock_notif):
        channel = models.Channel.objects.create(fully_indexed=True, full_archive=True)

        tasks.automated_archiver.delay().get()

        channel.refresh_from_db()

        self.assertFalse(channel.full_archive)
        self.assertFalse(channel.slow_full_archive)
        self.assertTrue(channel.send_download_notification)
        self.assertTrue(channel.fully_indexed)

        mock_dl.delay.assert_not_called()
        mock_notif.assert_called_once()


    ########################## PLAYLIST ###########################

    @override_settings(VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=2)
    @patch("vidar.tasks.download_provider_video")
    def test_playlist_at_max_downloads_for_the_day(self, mock_dl):
        playlist = models.Playlist.objects.create()

        playlist.videos.create(date_downloaded=timezone.now(), file="test.mp4")
        playlist.videos.create(date_downloaded=timezone.now(), file="test.mp4")
        playlist.videos.create()

        with self.assertLogs("vidar.tasks") as logger:
            tasks.automated_archiver.delay().get()
            expected_log_msg = "Max daily automated downloads reached."
            log_has_line = any([True for x in logger.output if expected_log_msg in x])
            self.assertTrue(log_has_line, "automated_archiver downloaded more videos than system config allows")

        mock_dl.delay.assert_not_called()

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=2,
    )
    @patch("vidar.tasks.download_provider_video")
    def test_playlist_downloads_limit_per_call(self, mock_dl):
        playlist = models.Playlist.objects.create()

        video1 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",),
            call(pk=video2.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",)
        ])

        mock_dl.reset_mock()

        video1.file = "test.mp4"
        video1.date_downloaded = timezone.now()
        video1.save()
        video2.file = "test.mp4"
        video2.date_downloaded = timezone.now()
        video2.save()

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_called_once_with(
            pk=video3.pk,
            task_source=f"automated_archiver - Playlist Scanner: {playlist}",
            requested_by=f"Playlist: {playlist!r}",
        )

    @patch("vidar.tasks.download_provider_video")
    def test_playlist_video_with_download_errors_skipped(self, mock_dl):
        playlist = models.Playlist.objects.create()

        video1 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        video2.download_errors.create()

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",),
            call(pk=video3.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",)
        ])

    @patch("vidar.tasks.download_provider_video")
    def test_playlist_video_with_celery_lock_skipped(self, mock_dl):
        playlist = models.Playlist.objects.create()

        video1 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        celery_helpers.object_lock_acquire(obj=video2, timeout=1)

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",),
            call(pk=video3.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",),
        ])

    @patch("vidar.tasks.download_provider_video")
    def test_playlist_video_with_title_skip_matches_skipped(self, mock_dl):
        playlist = models.Playlist.objects.create(title_skips="kitchens")

        video1 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = playlist.videos.create(title="New kitchens", upload_date=date_to_aware_date("2025-01-02"))
        video3 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",),
            call(pk=video3.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",),
        ])

        pli = playlist.playlistitem_set.get(video=video2)

        self.assertFalse(pli.download)

    @patch("vidar.tasks.download_provider_video")
    def test_playlist_with_channel_restrictions_wont_download_others(self, mock_dl):
        channel1 = models.Channel.objects.create()
        channel2 = models.Channel.objects.create()

        playlist = models.Playlist.objects.create(
            restrict_to_assigned_channel=True,
            channel=channel1
        )

        video1 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-01"), channel=channel1)
        video2 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-03"))

        celery_helpers.object_lock_acquire(obj=video2, timeout=1)

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_called_once_with(
            pk=video1.pk,
            task_source=f"automated_archiver - Playlist Scanner: {playlist}",
            requested_by=f"Playlist: {playlist!r}",
        )

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=6,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT=30
    )
    @patch("vidar.tasks.download_provider_video")
    def test_playlist_downloads_limit_halved_with_video_duration_too_long(self, mock_dl):
        playlist = models.Playlist.objects.create()

        video1 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-01"), duration=100)
        video2 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-02"), duration=100)
        video3 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-03"), duration=100)
        video4 = playlist.videos.create(upload_date=date_to_aware_date("2025-01-04"), duration=100)

        with self.assertLogs("vidar.utils") as logger:
            tasks.automated_archiver.delay().get()
            expected_log_msg = "Halving max automated downloads"
            log_has_line = any([True for x in logger.output if expected_log_msg in x])
            self.assertTrue(log_has_line, "automated_archiver should have divided the download limit in half")

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",),
            call(pk=video2.pk, task_source=f"automated_archiver - Playlist Scanner: {playlist}", requested_by=f"Playlist: {playlist!r}",)
        ])


    ########################## VIDEO DOWNLOAD ERRORS ###########################


    @override_settings(VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=2)
    @patch("vidar.tasks.download_provider_video")
    def test_videos_with_dl_errors_at_max_downloads_for_the_day(self, mock_dl):

        models.Video.objects.create(date_downloaded=timezone.now(), file="test.mp4")
        models.Video.objects.create(date_downloaded=timezone.now(), file="test.mp4")
        models.Video.objects.create()

        with self.assertLogs("vidar.tasks") as logger:
            tasks.automated_archiver.delay().get()
            expected_log_msg = "Max daily automated downloads reached."
            log_has_line = any([True for x in logger.output if expected_log_msg in x])
            self.assertTrue(log_has_line, "automated_archiver downloaded more videos than system config allows")

        mock_dl.delay.assert_not_called()

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=2,
        VIDAR_VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD=1,
    )
    @patch("vidar.tasks.download_provider_video")
    def test_videos_with_dl_errors_downloads_limit_per_call(self, mock_dl):

        video1 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-03"))

        for v in [video1, video2, video3]:
            ts = timezone.now() - timezone.timedelta(minutes=5)
            with patch.object(timezone, "now", return_value=ts):
                v.download_errors.create()

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Video Download Errors Attempts"),
            call(pk=video2.pk, task_source="automated_archiver - Video Download Errors Attempts")
        ])

        mock_dl.reset_mock()

        video1.file = "test.mp4"
        video1.date_downloaded = timezone.now()
        video1.save()
        video2.file = "test.mp4"
        video2.date_downloaded = timezone.now()
        video2.save()

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_called_once_with(
            pk=video3.pk,
            task_source="automated_archiver - Video Download Errors Attempts"
        )

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=2,
        VIDAR_VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD=1,
    )
    @patch("vidar.tasks.download_provider_video")
    def test_videos_with_dl_errors_skips_video_with_file(self, mock_dl):

        video1 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-02"), file="test.mp4")
        video3 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-03"))

        for v in [video1, video2, video3]:
            ts = timezone.now() - timezone.timedelta(minutes=5)
            with patch.object(timezone, "now", return_value=ts):
                v.download_errors.create()

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Video Download Errors Attempts"),
            call(pk=video3.pk, task_source="automated_archiver - Video Download Errors Attempts")
        ])

        self.assertFalse(video2.download_errors.exists())

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=2,
        VIDAR_VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD=1,
    )
    @patch("vidar.tasks.download_provider_video")
    def test_videos_with_dl_errors_skips_video_with_celery_lock(self, mock_dl):

        video1 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-03"))

        for v in [video1, video2, video3]:
            ts = timezone.now() - timezone.timedelta(minutes=5)
            with patch.object(timezone, "now", return_value=ts):
                v.download_errors.create()

        celery_helpers.object_lock_acquire(obj=video2, timeout=1)

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Video Download Errors Attempts"),
            call(pk=video3.pk, task_source="automated_archiver - Video Download Errors Attempts")
        ])

        self.assertTrue(video2.download_errors.exists())

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=2,
        VIDAR_VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD=1,
        VIDAR_VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS=2,
    )
    @patch("vidar.tasks.download_provider_video")
    def test_videos_with_dl_errors_skips_video_at_max_errors_for_period(self, mock_dl):

        video1 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-01"))
        video2 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-02"))
        video3 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-03"))

        for v in [video1, video3]:
            ts = timezone.now() - timezone.timedelta(minutes=5)
            with patch.object(timezone, "now", return_value=ts):
                v.download_errors.create()
        ts = timezone.now() - timezone.timedelta(minutes=5)
        with patch.object(timezone, "now", return_value=ts):
            video2.download_errors.create()
            video2.download_errors.create()
            video2.download_errors.create()

        with self.assertLogs("vidar.tasks", logging.DEBUG) as logger:
            tasks.automated_archiver.delay().get()
            expected_log_msg = "at max daily errors"
            log_has_line = any([True for x in logger.output if expected_log_msg in x])
            self.assertTrue(log_has_line, "video 2 should have been at max errors for the day.")

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Video Download Errors Attempts"),
            call(pk=video3.pk, task_source="automated_archiver - Video Download Errors Attempts")
        ])

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT=30,
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=6,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=4,
        VIDAR_VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD=1,
        VIDAR_VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS=2,
    )
    @patch("vidar.tasks.download_provider_video")
    def test_videos_with_dl_errors_halves_downloads_based_on_duration(self, mock_dl):

        video1 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-01"), duration=100)
        video2 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-02"), duration=100)
        video3 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-03"), duration=100)
        video4 = models.Video.objects.create(upload_date=date_to_aware_date("2025-01-04"), duration=100)

        for v in [video1, video2, video3, video4]:
            ts = timezone.now() - timezone.timedelta(minutes=5)
            with patch.object(timezone, "now", return_value=ts):
                v.download_errors.create()

        with self.assertLogs("vidar.utils") as logger:
            tasks.automated_archiver.delay().get()
            expected_log_msg = "Halving max automated downloads"
            log_has_line = any([True for x in logger.output if expected_log_msg in x])
            self.assertTrue(log_has_line, "automated_archiver should have divided the download limit in half")

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Video Download Errors Attempts"),
            call(pk=video2.pk, task_source="automated_archiver - Video Download Errors Attempts")
        ])


    ########################## VIDEO WAS LIVE LAST CHECK ###########################

    @patch("vidar.tasks.download_provider_video")
    def test_video_was_live_celery_locked(self, mock_dl):

        ts = timezone.now() - timezone.timedelta(hours=7)
        with patch.object(timezone, "now", return_value=ts):
            video = models.Video.objects.create(system_notes={"video_was_live_at_last_attempt": True})

        celery_helpers.object_lock_acquire(obj=video, timeout=1)

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video")
    def test_video_was_live_has_file_now(self, mock_dl):

        ts = timezone.now() - timezone.timedelta(hours=7)
        with patch.object(timezone, "now", return_value=ts):
            video = models.Video.objects.create(system_notes={"video_was_live_at_last_attempt": True}, file="test.mp4")

        tasks.automated_archiver.delay().get()

        video.refresh_from_db()
        self.assertNotIn("video_was_live_at_last_attempt", video.system_notes)

        mock_dl.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video")
    def test_video_was_live_retries_download(self, mock_dl):

        ts = timezone.now() - timezone.timedelta(hours=7)
        with patch.object(timezone, "now", return_value=ts):
            video = models.Video.objects.create(system_notes={"video_was_live_at_last_attempt": True})

        tasks.automated_archiver.delay().get()

        mock_dl.apply_async.assert_called_once_with(
            kwargs=dict(
                pk=video.pk,
                task_source="Live Download - Reattempt",
            ),
            countdown=10,
        )

        video.refresh_from_db()
        self.assertNotIn("video_was_live_at_last_attempt", video.system_notes)

    @patch("vidar.tasks.download_provider_video")
    def test_video_was_live_within_window_does_nothing(self, mock_dl):

        ts = timezone.now() - timezone.timedelta(hours=2)
        with patch.object(timezone, "now", return_value=ts):
            video = models.Video.objects.create(system_notes={"video_was_live_at_last_attempt": True})

        tasks.automated_archiver.delay().get()

        mock_dl.apply_async.assert_not_called()
        mock_dl.delay.assert_not_called()

        video.refresh_from_db()
        self.assertIn("video_was_live_at_last_attempt", video.system_notes)


    ########################## VIDEO WAS LIVE LAST CHECK ###########################

    @patch("vidar.services.ytdlp_services.get_highest_quality_from_video_dlp_formats")
    @patch("vidar.tasks.download_provider_video")
    def test_video_live_amq_changed_redownloads_amq(self, mock_dl, mock_hq):
        mock_hq.return_value = 1080
        video = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=480,
            file="test.mp4",
        )

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_called_once_with(
            pk=video.pk, task_source="automated_archiver - Video Quality Changed Afterwards"
        )

        video.refresh_from_db()

        self.assertIn("max_quality_upgraded", video.system_notes)

    @patch("vidar.services.ytdlp_services.get_highest_quality_from_video_dlp_formats")
    @patch("vidar.tasks.download_provider_video")
    def test_video_live_amq_changed_celery_locked(self, mock_dl, mock_hq):
        mock_hq.return_value = 1080
        video = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=480,
            file="test.mp4",
        )

        celery_helpers.object_lock_acquire(obj=video, timeout=1)

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_not_called()

        video.refresh_from_db()

        self.assertNotIn("max_quality_upgraded", video.system_notes)

    @patch("vidar.services.ytdlp_services.get_highest_quality_from_video_dlp_formats")
    @patch("vidar.tasks.download_provider_video")
    def test_video_live_amq_changed_current_quality_matches_max(self, mock_dl, mock_hq):
        mock_hq.return_value = 1080
        video = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=1080,
            file="test.mp4",
        )

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_not_called()

        video.refresh_from_db()

        self.assertNotIn("max_quality_upgraded", video.system_notes)

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=4,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=2,
        VIDAR_VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD=1,
    )
    @patch("vidar.services.ytdlp_services.get_highest_quality_from_video_dlp_formats")
    @patch("vidar.tasks.download_provider_video")
    def test_video_live_amq_hits_task_call_download_limits(self, mock_dl, mock_hq):
        mock_hq.return_value = 1080
        video1 = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=480,
            file="test.mp4",
        )
        video2 = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=480,
            file="test.mp4",
        )
        video3 = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=480,
            file="test.mp4",
        )

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Video Quality Changed Afterwards"),
            call(pk=video2.pk, task_source="automated_archiver - Video Quality Changed Afterwards"),
        ])

    @override_settings(
        VIDAR_AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT=30,
        VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT=6,
        VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT=4,
    )
    @patch("vidar.services.ytdlp_services.get_highest_quality_from_video_dlp_formats")
    @patch("vidar.tasks.download_provider_video")
    def test_video_live_amq_halves_download_limit(self, mock_dl, mock_hq):
        mock_hq.return_value = 1080
        video1 = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=480,
            file="test.mp4",
            duration=100,
        )
        video2 = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=480,
            file="test.mp4",
            duration=100,
        )
        video3 = models.Video.objects.create(
            requested_max_quality=True,
            at_max_quality=False,
            date_downloaded=timezone.now() - timezone.timedelta(days=5),
            quality=480,
            file="test.mp4",
            duration=100,
        )

        tasks.automated_archiver.delay().get()

        mock_dl.delay.assert_has_calls([
            call(pk=video1.pk, task_source="automated_archiver - Video Quality Changed Afterwards"),
            call(pk=video2.pk, task_source="automated_archiver - Video Quality Changed Afterwards"),
        ])
