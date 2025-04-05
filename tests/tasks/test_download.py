import yt_dlp

from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from celery.exceptions import MaxRetriesExceededError

from vidar import models, tasks, app_settings, exceptions
from vidar.helpers import celery_helpers

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

    @patch("vidar.services.video_services.download_exception")
    @patch("vidar.interactor.video_download")
    def test_ytdlp_downloaderror_handled_no_retries(self, mock_dl, mock_dl_exc):
        mock_dl.side_effect = yt_dlp.DownloadError("Live event will be ready in x time.")
        mock_dl_exc.return_value = True

        video = models.Video.objects.create()
        tasks.download_provider_video.delay(pk=video.pk).get()

        mock_dl.assert_called_once()
        mock_dl_exc.assert_called_once()

    @patch("vidar.services.video_services.download_exception")
    @patch("vidar.interactor.video_download")
    def test_ytdlp_downloaderror_not_handled_has_retries(self, mock_dl, mock_dl_exc):
        mock_dl.side_effect = yt_dlp.DownloadError("Unknown error occurs")
        mock_dl_exc.return_value = False

        video = models.Video.objects.create()

        with self.assertRaises(MaxRetriesExceededError):
            tasks.download_provider_video.delay(pk=video.pk).get()

        self.assertEqual(4, mock_dl.call_count)
        self.assertEqual(4, mock_dl_exc.call_count)
        self.assertFalse(celery_helpers.is_object_locked(obj=video))

    @patch("vidar.services.video_services.download_exception")
    @patch("vidar.interactor.video_download")
    def test_ytdlp_other_error_releases_celery_lock(self, mock_dl, mock_dl_exc):
        mock_dl.side_effect = ValueError("Unknown error occurs")

        video = models.Video.objects.create()

        with self.assertRaises(ValueError):
            tasks.download_provider_video.delay(pk=video.pk).get()

        mock_dl.assert_called_once()
        mock_dl_exc.assert_not_called()

        self.assertFalse(celery_helpers.is_object_locked(obj=video))

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
