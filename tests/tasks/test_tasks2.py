import datetime
import logging
import pathlib

import celery.states
import requests.exceptions
import yt_dlp

from unittest.mock import call, patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from vidar import models, tasks, app_settings, exceptions
from vidar.helpers import channel_helpers, celery_helpers
from vidar.services import crontab_services
from vidar.storages import vidar_storage

from ..test_functions import date_to_aware_date

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
        ], any_order=True)

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


class Update_video_statuses_and_details(TestCase):

    @patch("vidar.tasks.update_video_details")
    def test_video_less_than_check_age_not_checked_again(self, mock_task):
        models.Video.objects.create(file="test.mp4")

        tasks.update_video_statuses_and_details()

        mock_task.apply_async.assert_not_called()

    @patch("vidar.tasks.update_video_details")
    def test_video_more_than_check_age_is_checked(self, mock_task):

        ts = timezone.now() - timezone.timedelta(days=33)
        with patch.object(timezone, "now", return_value=ts):
            video1 = models.Video.objects.create(file="test.mp4")

        ts = timezone.now() - timezone.timedelta(days=32)
        with patch.object(timezone, "now", return_value=ts):
            video2 = models.Video.objects.create(file="test.mp4")

        tasks.update_video_statuses_and_details()

        mock_task.apply_async.assert_called_once_with(
            kwargs=dict(pk=video1.pk, mode="auto"), countdown=0
        )

    @override_settings(VIDAR_PRIVACY_STATUS_CHECK_FORCE_CHECK_PER_CALL=2)
    @patch("vidar.tasks.update_video_details")
    def test_video_force_checking(self, mock_task):

        ts = timezone.now() - timezone.timedelta(days=33)
        with patch.object(timezone, "now", return_value=ts):
            video1 = models.Video.objects.create(file="test.mp4")

        ts = timezone.now() - timezone.timedelta(days=32)
        with patch.object(timezone, "now", return_value=ts):
            video2 = models.Video.objects.create(file="test.mp4")

        ts = timezone.now() - timezone.timedelta(days=31)
        with patch.object(timezone, "now", return_value=ts):
            video3 = models.Video.objects.create(file="test.mp4")

        tasks.update_video_statuses_and_details()

        self.assertEqual(2, mock_task.apply_async.call_count)


class Load_sponsorblock_data_tests(TestCase):

    @patch("vidar.services.video_services.load_live_sponsorblock_video_data_into_duration_skips")
    def test_requests_connectionerror_retries(self, mock_load):
        video = models.Video.objects.create()
        mock_load.side_effect = requests.exceptions.ConnectionError()

        with self.assertRaises(requests.exceptions.ConnectionError):
            tasks.load_sponsorblock_data.delay(video.pk).get()

        self.assertEqual(4, mock_load.call_count)

    @patch("vidar.services.video_services.load_live_sponsorblock_video_data_into_duration_skips")
    def test_requests_httperror_returns(self, mock_load):
        video = models.Video.objects.create()
        mock_load.side_effect = requests.exceptions.HTTPError("500 Server Error")

        tasks.load_sponsorblock_data.delay(video.pk).get()

        self.assertEqual(1, mock_load.call_count)

    @patch("vidar.services.video_services.load_live_sponsorblock_video_data_into_duration_skips")
    def test_requests_httperror_with_unknown_errors_raises(self, mock_load):
        video = models.Video.objects.create()
        mock_load.side_effect = requests.exceptions.HTTPError("505 Server Error")

        with self.assertRaises(requests.exceptions.HTTPError):
            tasks.load_sponsorblock_data.delay(video.pk).get()

        self.assertEqual(4, mock_load.call_count)

    @patch("vidar.services.video_services.load_live_sponsorblock_video_data_into_duration_skips")
    def test_returns_number_of_created_items(self, mock_load):
        video = models.Video.objects.create()
        mock_load.return_value = [1,2,3,4,5]

        output = tasks.load_sponsorblock_data.delay(video.pk).get()
        self.assertEqual(5, output)

        self.assertEqual(1, mock_load.call_count)


class Sync_playlist_data_tests(TestCase):

    @patch("vidar.services.notification_services.playlist_disabled_due_to_errors")
    @patch("vidar.interactor.playlist_details")
    def test_one_failure_to_read_playlist_increments_counter(self, mock_inter, mock_notif):
        mock_inter.return_value = None

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        playlist.refresh_from_db()

        self.assertEqual(1, playlist.not_found_failures)

        mock_inter.assert_called_once()
        mock_notif.assert_not_called()

    @patch("vidar.services.notification_services.playlist_disabled_due_to_errors")
    @patch("vidar.interactor.playlist_details")
    def test_too_many_failures_to_read_playlist_disables_it(self, mock_inter, mock_notif):
        mock_inter.return_value = None

        playlist = models.Playlist.objects.create(crontab="* * * * *", provider_object_id="playlist-id")

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()
        tasks.sync_playlist_data.delay(pk=playlist.pk).get()
        tasks.sync_playlist_data.delay(pk=playlist.pk).get()
        tasks.sync_playlist_data.delay(pk=playlist.pk).get()
        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        playlist.refresh_from_db()

        self.assertEqual(5, playlist.not_found_failures)
        self.assertEqual("", playlist.crontab)

        self.assertEqual(5, mock_inter.call_count)
        mock_notif.assert_called_once_with(playlist=playlist)

    @patch("vidar.interactor.playlist_details")
    def test_with_some_failures_but_now_successful_clears_flags(self, mock_inter):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [],
        }

        playlist = models.Playlist.objects.create(
            crontab="* * * * *",
            not_found_failures=1,
        )

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        playlist.refresh_from_db()

        self.assertEqual(0, playlist.not_found_failures)

    @patch("vidar.interactor.playlist_details")
    def test_assigns_channel(self, mock_inter):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [],
        }

        channel = models.Channel.objects.create(provider_object_id="channel-id")

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        playlist.refresh_from_db()

        self.assertEqual(channel, playlist.channel)

    @patch("vidar.interactor.playlist_details")
    def test_does_not_reassign_channel(self, mock_inter):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [],
        }

        channel = models.Channel.objects.create(provider_object_id="channel-id")
        channel2 = models.Channel.objects.create(provider_object_id="channel-id-2")

        playlist = models.Playlist.objects.create(
            crontab="* * * * *",
            channel=channel2,
        )

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        playlist.refresh_from_db()

        self.assertEqual(channel2, playlist.channel)

    @patch("vidar.services.notification_services.video_added_to_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_skips_video_without_data(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [{},],
        }

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        self.assertFalse(playlist.videos.exists())

        mock_notif.assert_not_called()

    @patch("vidar.services.notification_services.video_added_to_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_skips_private_video(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [{
                "title": "[private video]",
            },],
        }

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        self.assertFalse(playlist.videos.exists())

        mock_notif.assert_not_called()

    @patch("vidar.services.notification_services.video_added_to_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_skips_deleted_video(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [{
                "title": "[deleted video]",
            },],
        }

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        self.assertFalse(playlist.videos.exists())

        mock_notif.assert_not_called()

    @patch("vidar.services.notification_services.video_added_to_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_video_blocked(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [
                {
                    "id": "video-id",
                    "title": "Test Video",
                },
            ],
        }

        playlist = models.Playlist.objects.create(crontab="* * * * *")
        models.VideoBlocked.objects.create(provider_object_id="video-id")

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        self.assertFalse(playlist.videos.exists())

        mock_notif.assert_not_called()

    @patch("vidar.services.notification_services.video_added_to_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_creates_videos(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [
                {
                    "uploader_id": "uploader-id",
                    "channel_id": "channel-id",
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ],
        }

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        self.assertTrue(playlist.videos.exists())

        mock_notif.assert_called_once()

    @patch("vidar.services.notification_services.video_readded_to_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_video_was_missing_but_now_found_live_clears_flag(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [
                {
                    "uploader_id": "uploader-id",
                    "channel_id": "channel-id",
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ],
        }

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        video = models.Video.objects.create(provider_object_id="video-id")

        pli = playlist.playlistitem_set.create(
            video=video,
            missing_from_playlist_on_provider=True
        )

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        pli.refresh_from_db()

        self.assertFalse(pli.missing_from_playlist_on_provider)

        mock_notif.assert_called_once()

    @patch("vidar.services.notification_services.video_readded_to_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_video_was_manually_added_but_now_found_live_clears_flag(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [
                {
                    "uploader_id": "uploader-id",
                    "channel_id": "channel-id",
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ],
        }

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        video = models.Video.objects.create(provider_object_id="video-id")

        pli = playlist.playlistitem_set.create(
            video=video,
            manually_added=True
        )

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        pli.refresh_from_db()

        self.assertFalse(pli.manually_added)
        mock_notif.assert_called_once()

    @patch("vidar.interactor.playlist_details")
    def test_video_not_permitted_to_download_sets_flag(self, mock_inter):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [
                {
                    "uploader_id": "uploader-id",
                    "channel_id": "channel-id",
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ],
        }

        playlist = models.Playlist.objects.create(crontab="* * * * *")

        video = models.Video.objects.create(provider_object_id="video-id", permit_download=False)

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        pli = playlist.playlistitem_set.get(video=video)

        self.assertFalse(pli.download)

    @patch("vidar.services.notification_services.playlist_disabled_due_to_string")
    @patch("vidar.interactor.playlist_details")
    def test_video_title_disables_playlist_crontab(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [
                {
                    "uploader_id": "uploader-id",
                    "channel_id": "channel-id",
                    "id": "video-id",
                    "title": "video title finale",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ],
        }

        playlist = models.Playlist.objects.create(
            provider_object_id="playlist-id",
            crontab="* * * * *",
            disable_when_string_found_in_video_title=" finale"
        )

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        playlist.refresh_from_db()

        self.assertEqual("", playlist.crontab)

        mock_notif.assert_called_once_with(playlist=playlist)

    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.interactor.playlist_details")
    def test_video_wants_comments_on_index(self, mock_inter, mock_dl):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [
                {
                    "uploader_id": "uploader-id",
                    "channel_id": "channel-id",
                    "id": "video-id",
                    "title": "video title",
                    "description": "video description",
                    "upload_date": "20250405",
                }
            ],
        }

        playlist = models.Playlist.objects.create()

        video = models.Video.objects.create(
            provider_object_id="video-id",
            download_comments_on_index=True,
        )

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        mock_dl.apply_async.assert_called_once_with(args=[video.pk], countdown=0)

    @patch("vidar.services.notification_services.video_removed_from_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_video_removed_from_live_flags_as_missing(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [],
        }

        playlist = models.Playlist.objects.create()

        video = models.Video.objects.create(provider_object_id="video-id")

        pli = playlist.playlistitem_set.create(video=video)

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        pli.refresh_from_db()

        self.assertTrue(pli.missing_from_playlist_on_provider)
        mock_notif.assert_called_once_with(video=video, playlist=playlist, removed=False)

    @patch("vidar.services.notification_services.video_removed_from_playlist")
    @patch("vidar.interactor.playlist_details")
    def test_video_removed_from_live_with_sync_deletions_removes_connection(self, mock_inter, mock_notif):
        mock_inter.return_value = {
            "title": "Test Playlist",
            "description": "Test Desc",
            "channel_id": "channel-id",
            "entries": [],
        }

        playlist = models.Playlist.objects.create(sync_deletions=True)

        video = models.Video.objects.create(provider_object_id="video-id")

        pli = playlist.playlistitem_set.create(video=video)

        tasks.sync_playlist_data.delay(pk=playlist.pk).get()

        self.assertFalse(playlist.playlistitem_set.exists())
        mock_notif.assert_called_once_with(video=video, playlist=playlist, removed=True)


class Automated_video_quality_upgrades_tests(TestCase):

    @patch("vidar.tasks.download_provider_video")
    def test_channel_allows_upgrade(self, mock_dl):
        channel = models.Channel.objects.create(index_videos=True, allow_library_quality_upgrade=True, quality=1080)

        video = channel.videos.create(quality=480, file="test.mp4")

        tasks.automated_video_quality_upgrades()

        mock_dl.delay.assert_called_once()

    @override_settings(VIDAR_AUTOMATED_QUALITY_UPGRADES_PER_TASK_LIMIT=2)
    @patch("vidar.tasks.download_provider_video")
    def test_channel_respects_download_limit(self, mock_dl):
        channel = models.Channel.objects.create(index_videos=True, allow_library_quality_upgrade=True, quality=1080)

        video = channel.videos.create(quality=480, file="test.mp4")
        video = channel.videos.create(quality=480, file="test.mp4")
        video = channel.videos.create(quality=480, file="test.mp4")
        video = channel.videos.create(quality=480, file="test.mp4")

        tasks.automated_video_quality_upgrades()

        self.assertEqual(2, mock_dl.delay.call_count)

    @patch("vidar.tasks.download_provider_video")
    def test_channel_video_above_channel_quality_does_nothing(self, mock_dl):
        channel = models.Channel.objects.create(index_videos=True, allow_library_quality_upgrade=True, quality=1080)

        video = channel.videos.create(quality=2160, file="test.mp4")

        tasks.automated_video_quality_upgrades()

        mock_dl.delay.assert_not_called()

    @patch("vidar.services.ytdlp_services.is_quality_at_highest_quality_from_dlp_formats")
    @patch("vidar.tasks.download_provider_video")
    def test_channel_video_amq_based_on_formats_and_does_nothing(self, mock_dl, mock_amq):
        mock_amq.return_value = True
        channel = models.Channel.objects.create(index_videos=True, allow_library_quality_upgrade=True, quality=1080)

        video = channel.videos.create(quality=2160, file="test.mp4", dlp_formats={"here": "test"})

        tasks.automated_video_quality_upgrades()

        mock_dl.delay.assert_not_called()

        video.refresh_from_db()
        self.assertTrue(video.at_max_quality)

    @patch("vidar.tasks.download_provider_video")
    def test_playlist_allows_upgrade(self, mock_dl):
        playlist = models.Playlist.objects.create(quality=1080)

        playlist.videos.create(quality=480, file="test.mp4")

        tasks.automated_video_quality_upgrades()

        mock_dl.delay.assert_called_once()

    @override_settings(VIDAR_AUTOMATED_QUALITY_UPGRADES_PER_TASK_LIMIT=2)
    @patch("vidar.tasks.download_provider_video")
    def test_playlist_respects_download_limit(self, mock_dl):
        playlist = models.Playlist.objects.create(quality=1080)

        playlist.videos.create(quality=480, file="test.mp4")
        playlist.videos.create(quality=480, file="test.mp4")
        playlist.videos.create(quality=480, file="test.mp4")
        playlist.videos.create(quality=480, file="test.mp4")

        tasks.automated_video_quality_upgrades()

        self.assertEqual(2, mock_dl.delay.call_count)

    @patch("vidar.tasks.download_provider_video")
    def test_playlist_video_above_playlist_quality_does_nothing(self, mock_dl):
        playlist = models.Playlist.objects.create(quality=1080)

        playlist.videos.create(quality=2160, file="test.mp4")

        tasks.automated_video_quality_upgrades()

        mock_dl.delay.assert_not_called()

    @patch("vidar.services.ytdlp_services.is_quality_at_highest_quality_from_dlp_formats")
    @patch("vidar.tasks.download_provider_video")
    def test_playlist_video_amq_based_on_formats_and_does_nothing(self, mock_dl, mock_amq):
        mock_amq.return_value = True
        playlist = models.Playlist.objects.create(quality=1080)

        video = playlist.videos.create(quality=2160, file="test.mp4", dlp_formats={"here": "test"})

        tasks.automated_video_quality_upgrades()

        mock_dl.delay.assert_not_called()

        video.refresh_from_db()
        self.assertTrue(video.at_max_quality)


class Post_download_processing_tests(TestCase):

    @patch("vidar.tasks.convert_video_to_audio")
    @patch("vidar.tasks.convert_video_to_mp4")
    @patch("vidar.tasks.write_file_to_storage")
    @patch("vidar.tasks.delete_cached_file")
    @patch("vidar.tasks.video_downloaded_successfully")
    def test_basics(self, mock_success, mock_delete, mock_write, mock_mkv, mock_audio):
        video = models.Video.objects.create(file="test.mp4")

        tasks.post_download_processing.delay(pk=video.pk, filepath="test.mp4").get()

        mock_write.si.assert_called_once_with(pk=video.pk, filepath="test.mp4", field_name="file")
        mock_delete.s.assert_called_once()
        mock_success.si.assert_called_once_with(pk=video.pk)

        mock_mkv.si.assert_not_called()
        mock_audio.si.assert_not_called()

    @patch("vidar.tasks.convert_video_to_audio")
    @patch("vidar.tasks.convert_video_to_mp4")
    @patch("vidar.tasks.write_file_to_storage")
    @patch("vidar.tasks.delete_cached_file")
    @patch("vidar.tasks.video_downloaded_successfully")
    def test_with_convert_to_audio(self, mock_success, mock_delete, mock_write, mock_mkv, mock_audio):
        filepath = "test.mp4"
        video = models.Video.objects.create(file=filepath, convert_to_audio=True)

        tasks.post_download_processing.delay(pk=video.pk, filepath=filepath).get()

        mock_audio.si.assert_called_once_with(pk=video.pk, filepath=filepath, return_filepath=True)
        mock_write.s.assert_called_once_with(pk=video.pk, field_name="audio")

        mock_write.si.assert_called_once_with(pk=video.pk, filepath=filepath, field_name="file")
        self.assertEqual(2, mock_delete.s.call_count)
        mock_success.si.assert_called_once_with(pk=video.pk)

        mock_mkv.si.assert_not_called()

    @patch("vidar.tasks.convert_video_to_audio")
    @patch("vidar.tasks.convert_video_to_mp4")
    @patch("vidar.tasks.write_file_to_storage")
    @patch("vidar.tasks.delete_cached_file")
    @patch("vidar.tasks.video_downloaded_successfully")
    def test_with_convert_to_audio_and_mp4(self, mock_success, mock_delete, mock_write, mock_mkv, mock_audio):
        filepath = "test.mkv"
        video = models.Video.objects.create(file=filepath, convert_to_audio=True)

        tasks.post_download_processing.delay(pk=video.pk, filepath=filepath).get()

        self.assertEqual(1, mock_audio.si.call_count)
        self.assertEqual(1, mock_mkv.si.call_count)
        self.assertEqual(2, mock_write.s.call_count)
        self.assertEqual(2, mock_delete.s.call_count)
        self.assertEqual(1, mock_delete.si.call_count)

        mock_success.si.assert_called_once_with(pk=video.pk)

    @patch("vidar.tasks.convert_video_to_audio")
    @patch("vidar.tasks.convert_video_to_mp4")
    @patch("vidar.tasks.write_file_to_storage")
    @patch("vidar.tasks.delete_cached_file")
    @patch("vidar.tasks.video_downloaded_successfully")
    def test_with_convert_to_mp4(self, mock_success, mock_delete, mock_write, mock_mkv, mock_audio):
        filepath = "test.mkv"
        video = models.Video.objects.create(file=filepath)

        tasks.post_download_processing.delay(pk=video.pk, filepath=filepath).get()

        self.assertEqual(0, mock_audio.si.call_count)
        self.assertEqual(1, mock_mkv.si.call_count)
        self.assertEqual(1, mock_write.s.call_count)
        self.assertEqual(1, mock_delete.s.call_count)
        self.assertEqual(1, mock_delete.si.call_count)

        mock_success.si.assert_called_once_with(pk=video.pk)


class Write_file_to_storage_tests(TestCase):

    def test_basics_file(self):

        video = models.Video.objects.create(
            title="test video",
            provider_object_id="video-id",
            file="test.mp4",
        )
        opener = SimpleUploadedFile("test.mp4", b"here")
        with patch.object(pathlib.Path, "open", return_value=opener):
            tasks.write_file_to_storage(filepath="test.mp4", pk=video.pk, field_name="file")

    def test_basics_audio(self):

        video = models.Video.objects.create(
            title="test video",
            provider_object_id="video-id",
            audio="test.mp3",
        )
        opener = SimpleUploadedFile("test.mp3", b"here")
        with patch.object(pathlib.Path, "open", return_value=opener):
            tasks.write_file_to_storage(filepath="test.mp3", pk=video.pk, field_name="audio")


class Delete_cached_file_tests(TestCase):

    @override_settings(VIDAR_DELETE_DOWNLOAD_CACHE=False)
    def test_system_keeps_cache(self):
        output = tasks.delete_cached_file("test.mp4")
        self.assertIsNone(output)

    @override_settings(VIDAR_DELETE_DOWNLOAD_CACHE=True)
    @patch("os.unlink")
    def test_system_deletes_keeps_cache(self, mock_unlink):
        output = tasks.delete_cached_file("test.mp4")
        self.assertTrue(output)
        mock_unlink.assert_called_once_with("test.mp4")


class Load_video_thumbnail_tests(TestCase):

    @patch("vidar.services.video_services.set_thumbnail")
    def test_basics(self, mock_set):
        video = models.Video.objects.create()
        tasks.load_video_thumbnail.delay(pk=video.pk, url="url").get()

        mock_set.assert_called_with(video=video, url="url")

    @patch("vidar.services.video_services.set_thumbnail")
    def test_no_url_raises(self, mock_set):
        video = models.Video.objects.create()

        with self.assertRaises(ValueError):
            tasks.load_video_thumbnail.delay(pk=video.pk, url="").get()

    @patch("vidar.services.video_services.set_thumbnail")
    def test_connerror_retries(self, mock_set):
        mock_set.side_effect = requests.exceptions.ConnectionError
        video = models.Video.objects.create()

        with self.assertRaises(requests.exceptions.ConnectionError):
            tasks.load_video_thumbnail.delay(pk=video.pk, url="url").get()

        self.assertEqual(4, mock_set.call_count)


class Update_video_details_tests(TestCase):

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.interactor.video_details")
    def test_video_with_file_missing_info_json_ytdlp_kwargs_adds_write_info_json(self, mock_details):
        mock_details.return_value = {}
        video = models.Video.objects.create(file="test.mp4")

        with self.assertRaises(ValueError, msg="No output from yt-dlp"):
            tasks.update_video_details.delay(pk=video.pk).get()

        mock_details.assert_called_once_with(
            video.url,
            quiet=True,
            instance=video,
            writeinfojson=True,
        )

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=False)
    @patch("vidar.interactor.video_details")
    def test_video_with_file_missing_info_json_system_false_does_not_add_write_info_json(self, mock_details):
        mock_details.return_value = {}
        video = models.Video.objects.create(file="test.mp4")

        with self.assertRaises(ValueError, msg="No output from yt-dlp"):
            tasks.update_video_details.delay(pk=video.pk).get()

        mock_details.assert_called_once_with(
            video.url,
            quiet=True,
            instance=video,
        )

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.interactor.video_details")
    def test_video_without_file_does_not_add_ytdlp_kwargs_write_info_json(self, mock_details):
        mock_details.return_value = {}
        video = models.Video.objects.create()

        with self.assertRaises(ValueError, msg="No output from yt-dlp"):
            tasks.update_video_details.delay(pk=video.pk).get()

        mock_details.assert_called_once_with(
            video.url,
            quiet=True,
            instance=video,
        )

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_ytdlp_dl_error_updates_status(self, mock_detail, mock_log):
        mock_detail.side_effect = yt_dlp.DownloadError("blocked in your country")

        video = models.Video.objects.create()

        tasks.update_video_details.delay(pk=video.pk, mode="auto").get()

        video.refresh_from_db()
        self.assertEqual(video.privacy_status, models.Video.VideoPrivacyStatuses.BLOCKED)

        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="Privacy Status Changed")

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_ytdlp_dl_error_confirm_age_logs_result(self, mock_detail, mock_log):
        mock_detail.side_effect = yt_dlp.DownloadError("signin to confirm your age")

        video = models.Video.objects.create()

        tasks.update_video_details.delay(pk=video.pk, mode="auto").get()

        video.refresh_from_db()
        self.assertEqual(video.privacy_status, models.Video.VideoPrivacyStatuses.PUBLIC)

        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="Sign in to confirm age")

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_ytdlp_dl_error_unknown_reason_retries(self, mock_detail, mock_log):
        mock_detail.side_effect = yt_dlp.DownloadError("some unknown reason")

        video = models.Video.objects.create()

        with self.assertRaises(yt_dlp.DownloadError):
            tasks.update_video_details.delay(pk=video.pk, mode="auto").get()

        video.refresh_from_db()
        self.assertEqual(video.privacy_status, models.Video.VideoPrivacyStatuses.PUBLIC)

        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="4th attempt retry in 1 hour")

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_video_title_changed_to_private_video(self, mock_detail, mock_log):
        mock_detail.return_value = {
            "title": "[private video]"
        }

        video = models.Video.objects.create()

        tasks.update_video_details.delay(pk=video.pk, mode="auto").get()

        video.refresh_from_db()
        self.assertEqual(video.privacy_status, models.Video.VideoPrivacyStatuses.PRIVATE)

        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="Success")

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_video_title_changed_to_deleted_video(self, mock_detail, mock_log):
        mock_detail.return_value = {
            "title": "[deleted video]"
        }

        video = models.Video.objects.create()

        tasks.update_video_details.delay(pk=video.pk, mode="auto").get()

        video.refresh_from_db()
        self.assertEqual(video.privacy_status, models.Video.VideoPrivacyStatuses.DELETED)

        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="Success")

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_video_sets_updated_details(self, mock_detail, mock_log):
        mock_detail.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
        }

        video = models.Video.objects.create(
            provider_object_id="video-id",
            quality=720,
        )

        tasks.update_video_details.delay(pk=video.pk, mode="auto").get()
        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="Success")

        video.refresh_from_db()

        self.assertEqual("Test Video", video.title)
        self.assertEqual("Video desc", video.description)

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.ytdlp_services.get_highest_quality_from_video_dlp_formats")
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_video_quality_zero_gets_set_to_max_based_on_highest_in_dlp_formats(self, mock_detail, mock_log, mock_high):
        mock_detail.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
        }
        mock_high.return_value = 1080

        video = models.Video.objects.create(provider_object_id="video-id", quality=0)

        tasks.update_video_details.delay(pk=video.pk, mode="auto").get()
        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="Success")

        video.refresh_from_db()

        self.assertEqual(1080, video.quality)

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.ytdlp_services.get_highest_quality_from_video_dlp_formats")
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_video_quality_is_still_at_max_quality(self, mock_detail, mock_log, mock_high):
        mock_detail.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
        }
        mock_high.return_value = 1080

        video = models.Video.objects.create(provider_object_id="video-id", quality=1080, at_max_quality=True)

        tasks.update_video_details.delay(pk=video.pk, mode="auto").get()
        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="Success")

        video.refresh_from_db()

        self.assertTrue(video.at_max_quality)

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.services.ytdlp_services.get_highest_quality_from_video_dlp_formats")
    @patch("vidar.services.video_services.log_update_video_details_called")
    @patch("vidar.interactor.video_details")
    def test_video_quality_is_no_longer_at_max_quality_sets_flag(self, mock_detail, mock_log, mock_high):
        mock_detail.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
        }
        mock_high.return_value = 2160

        video = models.Video.objects.create(provider_object_id="video-id", quality=1080, at_max_quality=True)

        tasks.update_video_details.delay(pk=video.pk, mode="auto").get()
        mock_log.assert_called_once_with(video=video, mode="auto", commit=True, result="Success")

        video.refresh_from_db()

        self.assertFalse(video.at_max_quality)
        self.assertIn("uvd_max_quality_changed", video.system_notes)

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.tasks.download_provider_video")
    @patch("vidar.interactor.video_details")
    def test_download_true_missing_file_calls_download(self, mock_detail, mock_dl):
        mock_detail.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
        }

        video = models.Video.objects.create(provider_object_id="video-id")

        output = tasks.update_video_details.delay(pk=video.pk, mode="auto", download_file=True).get()
        self.assertEqual("Video should have had file but does not. Downloading now.", output)

        mock_dl.delay.assert_called_once_with(pk=video.pk, task_source="update_video_details missing file")

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.tasks.rename_video_files")
    @patch("vidar.tasks.load_sponsorblock_data")
    @patch("vidar.services.video_services.load_chapters_from_info_json")
    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.load_video_thumbnail")
    @patch("vidar.services.video_services.save_infojson_file")
    @patch("vidar.interactor.video_details")
    @patch("vidar.tasks.download_provider_video")
    def test_download_true_with_file_updates_the_rest(self, mock_dl, mock_detail, mock_json, mock_thumb, mock_comm, mock_chapters, mock_sb, mock_rename):
        mock_detail.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
            "requested_downloads": [{},]
        }

        video = models.Video.objects.create(
            provider_object_id="video-id",
            file="test.mp4",
            upload_date=date_to_aware_date("2025-01-02"),
        )

        with patch.object(vidar_storage, "exists", return_value=True):
            output = tasks.update_video_details.delay(pk=video.pk, mode="auto", download_file=True).get()
        self.assertEqual("Success", output)

        mock_dl.delay.assert_not_called()

        mock_json.assert_called_once()
        mock_thumb.apply_async.assert_called_once()
        mock_comm.delay.assert_not_called()
        mock_chapters.assert_called_once()
        mock_sb.apply_async.assert_called_once()
        mock_rename.apply_async.assert_called_once()

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.tasks.rename_video_files")
    @patch("vidar.tasks.load_sponsorblock_data")
    @patch("vidar.services.video_services.load_chapters_from_info_json")
    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.load_video_thumbnail")
    @patch("vidar.services.video_services.save_infojson_file")
    @patch("vidar.interactor.video_details")
    @patch("vidar.tasks.download_provider_video")
    def test_download_true_with_max_sponsorblock_checks_not_called(self, mock_dl, mock_detail, mock_json, mock_thumb, mock_comm, mock_chapters, mock_sb, mock_rename):
        mock_detail.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
            "requested_downloads": [{},]
        }

        video = models.Video.objects.create(
            provider_object_id="video-id",
            file="test.mp4",
            upload_date=date_to_aware_date("2025-01-02"),
            system_notes={
                "sponsorblock-loaded": [
                    timezone.now().isoformat(), timezone.now().isoformat(), timezone.now().isoformat()
                ]
            }
        )

        with patch.object(vidar_storage, "exists", return_value=True):
            output = tasks.update_video_details.delay(pk=video.pk, mode="auto", download_file=True).get()
        self.assertEqual("Success", output)

        mock_dl.delay.assert_not_called()

        mock_json.assert_called_once()
        mock_thumb.apply_async.assert_called_once()
        mock_comm.delay.assert_not_called()
        mock_chapters.assert_called_once()
        mock_sb.apply_async.assert_not_called()
        mock_rename.apply_async.assert_called_once()

    @override_settings(VIDAR_SAVE_INFO_JSON_FILE=True)
    @patch("vidar.tasks.rename_video_files")
    @patch("vidar.tasks.load_sponsorblock_data")
    @patch("vidar.services.video_services.load_chapters_from_info_json")
    @patch("vidar.tasks.download_provider_video_comments")
    @patch("vidar.tasks.load_video_thumbnail")
    @patch("vidar.services.video_services.save_infojson_file")
    @patch("vidar.interactor.video_details")
    @patch("vidar.tasks.download_provider_video")
    def test_download_true_with_file_gets_comments(self, mock_dl, mock_detail, mock_json, mock_thumb, mock_comm, mock_chapters, mock_sb, mock_rename):
        mock_detail.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
            "requested_downloads": [{},]
        }

        video = models.Video.objects.create(
            provider_object_id="video-id",
            file="test.mp4",
            upload_date=date_to_aware_date("2025-01-02"),
            download_comments_on_index=True,
        )

        with patch.object(vidar_storage, "exists", return_value=True):
            output = tasks.update_video_details.delay(pk=video.pk, mode="auto", download_file=True).get()
        self.assertEqual("Success", output)

        mock_dl.delay.assert_not_called()

        mock_json.assert_called_once()
        mock_thumb.apply_async.assert_called_once()
        mock_comm.delay.assert_called_once()
        mock_chapters.assert_called_once()
        mock_sb.apply_async.assert_called_once()
        mock_rename.apply_async.assert_called_once()
