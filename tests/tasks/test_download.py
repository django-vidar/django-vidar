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


class Download_provider_video_tests(TestCase):

    @patch("vidar.services.ytdlp_services.get_video_downloader_args")
    def test_celery_locked(self, mock_get):
        # if something changes and this point is reached, block it from going any farther.
        mock_get.side_effect = ValueError()
        video = models.Video.objects.create()
        celery_helpers.object_lock_acquire(obj=video, timeout=1)
        tasks.download_provider_video.delay(pk=video.pk).get()

    @patch("vidar.helpers.celery_helpers.object_lock_acquire")
    @patch("vidar.helpers.celery_helpers.is_object_locked")
    def test_celery_fails_to_acquire(self, mock_is_locked, mock_acquire):
        mock_is_locked.return_value = False
        mock_acquire.return_value = False
        video = models.Video.objects.create()
        with self.assertRaises(SystemError):
            tasks.download_provider_video.delay(pk=video.pk).get()

    @patch("vidar.interactor.video_download")
    def test_video_is_live_and_cannot_be_downloaded(self, mock_dl):
        mock_dl.side_effect = yt_dlp.DownloadError("Live event will be ready in x time.")

        video = models.Video.objects.create()
        tasks.download_provider_video.delay(pk=video.pk).get()

        video.refresh_from_db()
        self.assertIn("video_was_live_at_last_attempt", video.system_notes)
        self.assertTrue(video.system_notes["video_was_live_at_last_attempt"])

    @patch("vidar.interactor.video_download")
    def test_video_is_live_and_cannot_be_downloaded_stop_playlist_requesting_it(self, mock_dl):
        mock_dl.side_effect = yt_dlp.DownloadError("Live event will be ready in x time.")

        playlist = models.Playlist.objects.create()

        video = models.Video.objects.create(system_notes={
            "downloads_live_exc": [1, 2, 3, 4, 5],
        })

        pli = playlist.playlistitem_set.create(video=video)

        tasks.download_provider_video.delay(pk=video.pk).get()

        pli.refresh_from_db()
        self.assertFalse(pli.download)

    @patch("vidar.interactor.video_download")
    def test_video_is_blocked_in_country(self, mock_dl):
        mock_dl.side_effect = yt_dlp.DownloadError("Video is blocked in your country")

        video = models.Video.objects.create(provider_object_id="video-id")

        tasks.download_provider_video.delay(pk=video.pk).get()

        video.refresh_from_db()
        self.assertEqual(models.Video.VideoPrivacyStatuses.BLOCKED, video.privacy_status)

    @patch("vidar.interactor.video_download")
    def test_video_downloaded_invalid_data(self, mock_dl):
        mock_dl.side_effect = yt_dlp.DownloadError("Invalid data found when processing input")

        file = pathlib.Path(app_settings.MEDIA_CACHE) / "video-id.mp4"
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open('wb') as fw:
            fw.write(b'test data')

        video = models.Video.objects.create(provider_object_id="video-id")

        tasks.download_provider_video.delay(pk=video.pk).get()

        self.assertFalse(file.exists())

    @patch("vidar.services.ytdlp_services.get_video_downloader_args")
    @patch("vidar.interactor.video_download")
    def test_quality_selection_default(self, mock_dl, mock_args):
        mock_dl.side_effect = exceptions.YTDLPCalledDuringTests()

        video = models.Video.objects.create(quality=480)

        with self.assertRaises(exceptions.YTDLPCalledDuringTests):
            tasks.download_provider_video.delay(pk=video.pk).get()

        mock_args.assert_called_once_with(
            quality=480,
            cache_folder=app_settings.MEDIA_CACHE,
            retries=0,
            video=video,
        )

    @patch("vidar.services.ytdlp_services.get_video_downloader_args")
    @patch("vidar.interactor.video_download")
    def test_quality_selection_given_to_task(self, mock_dl, mock_args):
        mock_dl.side_effect = exceptions.YTDLPCalledDuringTests()

        video = models.Video.objects.create(quality=480)

        with self.assertRaises(exceptions.YTDLPCalledDuringTests):
            tasks.download_provider_video.delay(pk=video.pk, quality=1080).get()

        mock_args.assert_called_once_with(
            quality=1080,
            cache_folder=app_settings.MEDIA_CACHE,
            retries=0,
            video=video,
        )

    @patch("vidar.services.ytdlp_services.get_video_downloader_args")
    @patch("vidar.interactor.video_download")
    def test_quality_zero_after_many_errors(self, mock_dl, mock_args):
        mock_dl.side_effect = exceptions.YTDLPCalledDuringTests()

        video = models.Video.objects.create(quality=480)
        for x in range(6):
            video.download_errors.create()

        with self.assertRaises(exceptions.YTDLPCalledDuringTests):
            tasks.download_provider_video.delay(pk=video.pk, quality=1080).get()

        mock_args.assert_called_once_with(
            quality=0,
            cache_folder=app_settings.MEDIA_CACHE,
            retries=0,
            video=video,
        )

    @patch("vidar.tasks.post_download_processing")
    @patch("vidar.services.video_services.save_infojson_file")
    @patch("vidar.services.ytdlp_services.is_video_at_highest_quality_from_dlp_response")
    @patch("vidar.services.ytdlp_services.get_video_downloaded_quality_from_dlp_response")
    @patch("vidar.interactor.video_download")
    def test_download_sets_information(self, mock_dl, mock_quality_dld, mock_is_amq, mock_save_json, mock_proc):
        filepath = app_settings.MEDIA_CACHE / "test.mp4"
        mock_quality_dld.return_value = 1080
        mock_is_amq.return_value = True
        mock_dl.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
            "format_id": "612",
            "format_note": "1080p",
            "requested_downloads": [{
                "filepath": filepath,
            },]
        }, {}

        video = models.Video.objects.create(quality=480)
        video.download_errors.create()

        tasks.download_provider_video.delay(pk=video.pk).get()

        mock_save_json.assert_called_once()
        mock_proc.apply_async.assert_called_once_with(kwargs=dict(pk=video.pk, filepath=str(filepath)), countdown=1)

        video.refresh_from_db()
        self.assertFalse(video.download_errors.exists())
        self.assertFalse(video.force_download)
        self.assertIn("downloads", video.system_notes)

    @patch("vidar.tasks.post_download_processing")
    @patch("vidar.services.video_services.save_infojson_file")
    @patch("vidar.services.ytdlp_services.is_video_at_highest_quality_from_dlp_response")
    @patch("vidar.services.ytdlp_services.get_video_downloaded_quality_from_dlp_response")
    @patch("vidar.interactor.video_download")
    def test_download_fails_to_determine_amq_status(self, mock_dl, mock_quality_dld, mock_is_amq, mock_save_json, mock_proc):
        filepath = app_settings.MEDIA_CACHE / "test.mp4"
        mock_quality_dld.return_value = 1080
        mock_is_amq.side_effect = ValueError("failure to obtain amq")
        mock_dl.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
            "format_id": "612",
            "format_note": "1080p",
            "requested_downloads": [{
                "filepath": filepath,
            },]
        }, {}

        video = models.Video.objects.create(quality=480)
        video.download_errors.create()

        tasks.download_provider_video.delay(pk=video.pk).get()

        mock_save_json.assert_called_once()
        mock_proc.apply_async.assert_called_once_with(kwargs=dict(pk=video.pk, filepath=str(filepath)), countdown=1)

        video.refresh_from_db()
        self.assertFalse(video.download_errors.exists())
        self.assertFalse(video.force_download)
        self.assertIn("downloads", video.system_notes)

    @patch("vidar.tasks.post_download_processing")
    @patch("vidar.services.video_services.save_infojson_file")
    @patch("vidar.services.ytdlp_services.is_video_at_highest_quality_from_dlp_response")
    @patch("vidar.services.ytdlp_services.get_video_downloaded_quality_from_dlp_response")
    @patch("vidar.interactor.video_download")
    def test_download_sets_requested_by(self, mock_dl, mock_quality_dld, mock_is_amq, mock_save_json, mock_proc):
        filepath = app_settings.MEDIA_CACHE / "test.mp4"
        mock_quality_dld.return_value = 1080
        mock_is_amq.side_effect = ValueError("failure to obtain amq")
        mock_dl.return_value = {
            "title": "Test Video",
            "id": "video-id",
            "description": "Video desc",
            "format_id": "612",
            "format_note": "1080p",
            "requested_downloads": [{
                "filepath": filepath,
            },]
        }, {}

        video = models.Video.objects.create(quality=480)
        video.download_errors.create()

        tasks.download_provider_video.delay(pk=video.pk, requested_by="tests.test_download_sets_requested_by").get()

        mock_save_json.assert_called_once()
        mock_proc.apply_async.assert_called_once_with(kwargs=dict(pk=video.pk, filepath=str(filepath)), countdown=1)

        video.refresh_from_db()
        self.assertFalse(video.download_errors.exists())
        self.assertFalse(video.force_download)
        self.assertIn("downloads", video.system_notes)
        self.assertEqual("tests.test_download_sets_requested_by", video.download_requested_by)
