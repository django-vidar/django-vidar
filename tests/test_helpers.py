import datetime
import io
import pathlib

from unittest.mock import patch, MagicMock
from celery import states
from celery.exceptions import Ignore

from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.contrib.sessions.middleware import SessionMiddleware

from vidar import models, app_settings, helpers
from vidar.helpers import (
    channel_helpers,
    json_safe_kwargs,
    extrafile_helpers,
    celery_helpers,
    video_helpers,
    statistics_helpers,
    file_helpers,
)

from tests.test_functions import date_to_aware_date


class GeneralHelpersTests(TestCase):

    def test_json_safe_kwargs(self):
        dt = datetime.datetime.now()
        kwargs = {
            "progress_hooks": [],
            "timezone": dt,
            "io": io.StringIO("test io"),
            "untouched": "here",
            "cookiefile": "cookie file here",
            "cookies": "",
        }

        output = json_safe_kwargs(kwargs)

        self.assertNotIn("progress_hooks", output)
        self.assertNotIn("cookiefile", output)
        self.assertNotIn("cookies", output)

        self.assertIn("timezone", output)
        self.assertEqual(str, type(output["timezone"]))
        self.assertEqual(dt.isoformat(), output["timezone"])

        self.assertIn("io", output)
        self.assertEqual(str, type(output["io"]))
        self.assertEqual("test io", output["io"])

        self.assertIn("untouched", output)
        self.assertEqual(str, type(output["untouched"]))
        self.assertEqual("here", output["untouched"])

    def test_json_safe_kwargs_with_dicts(self):
        kwargs = {
            "subdict": {
                "io": io.StringIO("test 2 io"),
            }
        }

        output = json_safe_kwargs(kwargs)

        self.assertIn("subdict", output)
        self.assertIn("io", output["subdict"])
        self.assertEqual(str, type(output["subdict"]["io"]))
        self.assertEqual("test 2 io", output["subdict"]["io"])

    def test_next_day_of_week_is_valid(self):
        self.assertEqual(1, helpers.convert_to_next_day_of_week(0))
        self.assertEqual(2, helpers.convert_to_next_day_of_week(1))
        self.assertEqual(3, helpers.convert_to_next_day_of_week(2))
        self.assertEqual(4, helpers.convert_to_next_day_of_week(3))
        self.assertEqual(5, helpers.convert_to_next_day_of_week(4))
        self.assertEqual(6, helpers.convert_to_next_day_of_week(5))
        self.assertEqual(0, helpers.convert_to_next_day_of_week(6))
        self.assertEqual(1, helpers.convert_to_next_day_of_week(7))

    def test_unauthenticated_unable_to_access_vidar_video(self):
        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda x: x)
        middleware.process_request(request)
        request.session.save()
        self.assertFalse(helpers.unauthenticated_check_if_can_view_video(request, "video-id"))

    def test_unauthenticated_able_to_access_vidar_video(self):
        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda x: x)
        middleware.process_request(request)
        request.session.save()

        self.assertEqual([], helpers.unauthenticated_permitted_videos(request))

        helpers.unauthenticated_allow_view_video(request, "video-id")
        self.assertTrue(helpers.unauthenticated_check_if_can_view_video(request, "video-id"))
        self.assertEqual(["video-id"], helpers.unauthenticated_permitted_videos(request))

        helpers.unauthenticated_allow_view_video(request, "video-id2")
        self.assertEqual(["video-id", "video-id2"], helpers.unauthenticated_permitted_videos(request))

    def test_redirect_next_or_obj(self):
        request = RequestFactory().get("/")

        video = models.Video.objects.create()

        output = helpers.redirect_next_or_obj(request, video)
        self.assertEqual(video.get_absolute_url(), output.url)

        request = RequestFactory().get("/?next=/admin/")
        output = helpers.redirect_next_or_obj(request, video)
        self.assertEqual("/admin/", output.url)


class CeleryHelpersTests(TestCase):

    def test_object_locks(self):
        video = models.Video.objects.create()
        self.assertFalse(celery_helpers.is_object_locked(video))

        celery_helpers.object_lock_acquire(video)
        self.assertTrue(celery_helpers.is_object_locked(video))

        celery_helpers.object_lock_release(video)
        self.assertFalse(celery_helpers.is_object_locked(video))

    def test_prevent_asynchronous_task_execution_basics(self):
        celery_request = MagicMock()

        @celery_helpers.prevent_asynchronous_task_execution()
        def my_function(self):
            pass

        my_function(celery_request)

        celery_request.retry.assert_not_called()
        celery_request.update_state.assert_not_called()

    def test_prevent_asynchronous_task_execution_with_custom_lock_key(self):
        celery_request = MagicMock()

        @celery_helpers.prevent_asynchronous_task_execution(lock_key="lock-key")
        def my_function(self):
            pass

        my_function(celery_request)

        celery_request.retry.assert_not_called()
        celery_request.update_state.assert_not_called()

    def test_prevent_asynchronous_task_execution_retries(self):

        celery_request = MagicMock()

        @celery_helpers.prevent_asynchronous_task_execution(lock_key="lock-key", retry=True, retry_countdown=1)
        def my_function(self):
            pass

        cache.add("lock-key", True, 1)

        my_function(celery_request)

        cache.delete("lock-key")

        celery_request.retry.assert_called_with(countdown=1)
        celery_request.update_state.assert_not_called()

    def test_prevent_asynchronous_task_execution_fails_ignore_result(self):

        celery_request = MagicMock()

        @celery_helpers.prevent_asynchronous_task_execution(lock_key="lock-key", retry=False)
        def my_function(self):
            pass

        cache.add("lock-key", True, 1)

        with self.assertRaises(Ignore):
            my_function(celery_request)

        cache.delete("lock-key")

        celery_request.retry.assert_not_called()
        celery_request.update_state.assert_called_with(state=states.FAILURE, meta="Task failed to acquire lock.")

    def test_prevent_asynchronous_task_execution_fails_quietly(self):

        celery_request = MagicMock()

        @celery_helpers.prevent_asynchronous_task_execution(lock_key="lock-key", retry=False, mark_result_failed_on_lock_failure=False)
        def my_function(self):
            pass

        cache.add("lock-key", True, 1)

        self.assertIsNone(my_function(celery_request))

        cache.delete("lock-key")

        celery_request.retry.assert_not_called()
        celery_request.update_state.assert_not_called()


class VideoHelpersTests(TestCase):
    def test_get_video_upload_to_directory_without_channel_with_upload_date(self):
        video = models.Video.objects.create(title="test video 1", upload_date=date_to_aware_date('2023-01-01'))
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual('public/2023', str(output))

    def test_get_video_upload_to_directory_without_channel_uses_custom_directory_schema(self):
        video = models.Video.objects.create(
            title="test video 1",
            directory_schema="test video/{{video.upload_date.year}}",
            upload_date=date_to_aware_date("2024-05-24")
        )
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual(f'test video/2024', str(output))

    def test_get_video_upload_to_directory_without_channel_nor_upload_date(self):
        video = models.Video.objects.create(title="test video 1")
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual(f'public/{timezone.now().year}', str(output))

    def test_get_video_upload_to_directory_with_channel_year_sep_with_upload_date_and_vids_in_sep_dir(self):
        channel = models.Channel.objects.create(
            name="Test Channel",
            store_videos_by_year_separation=True,
            store_videos_in_separate_directories=True,
        )
        video = models.Video.objects.create(
            channel=channel,
            provider_object_id="video-id-1",
            title="test video 1",
            upload_date=date_to_aware_date('2023-01-01')
        )
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual('Test Channel/2023/2023-01-01 - test video 1 [video-id-1]', str(output))

    def test_get_video_upload_to_directory_with_channel_year_sep_without_upload_date_and_vids_in_sep_dir(self):
        channel = models.Channel.objects.create(
            name="Test Channel",
            store_videos_by_year_separation=True,
            store_videos_in_separate_directories=True,
        )
        video = models.Video.objects.create(
            channel=channel,
            provider_object_id="video-id-1",
            title="test video 1",
        )
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual(f'Test Channel/{timezone.now().year}/- test video 1 [video-id-1]', str(output))

    def test_get_video_upload_to_directory_with_channel_not_year_sep_with_upload_date_and_vids_in_sep_dir(self):
        channel = models.Channel.objects.create(
            name="Test Channel",
            store_videos_by_year_separation=False,
            store_videos_in_separate_directories=True,
        )
        video = models.Video.objects.create(
            channel=channel,
            provider_object_id="video-id-1",
            title="test video 1",
            upload_date=date_to_aware_date('2023-01-01')
        )
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual('Test Channel/2023-01-01 - test video 1 [video-id-1]', str(output))

    def test_get_video_upload_to_directory_with_channel_not_year_sep_with_upload_date_and_not_vids_in_sep_dir(self):
        channel = models.Channel.objects.create(
            name="Test Channel",
            store_videos_by_year_separation=False,
            store_videos_in_separate_directories=False,
        )
        video = models.Video.objects.create(
            channel=channel,
            provider_object_id="video-id-1",
            title="test video 1",
            upload_date=date_to_aware_date('2023-01-01')
        )
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual('Test Channel', str(output))

    def test_get_video_upload_to_directory_with_channel_year_sep_with_upload_date_and_not_vids_in_sep_dir(self):
        channel = models.Channel.objects.create(
            name="Test Channel",
            store_videos_by_year_separation=True,
            store_videos_in_separate_directories=False,
        )
        video = models.Video.objects.create(
            channel=channel,
            provider_object_id="video-id-1",
            title="test video 1",
            upload_date=date_to_aware_date('2023-01-01')
        )
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual('Test Channel/2023', str(output))

    def test_get_video_upload_to_directory_with_channel_year_sep_without_upload_date_and_not_vids_in_sep_dir(self):
        channel = models.Channel.objects.create(
            name="Test Channel",
            store_videos_by_year_separation=True,
            store_videos_in_separate_directories=False,
        )
        video = models.Video.objects.create(
            channel=channel,
            provider_object_id="video-id-1",
            title="test video 1",
        )
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual(f'Test Channel/{timezone.now().year}', str(output))

    def test_video_playlist_custom_directory_schema_returns_pathlib(self):
        video = models.Video.objects.create(
            provider_object_id="video-id-1",
            title="test video 1",
        )
        playlist = models.Playlist.objects.create(
            directory_schema="test playlist dir/"
        )
        playlist.playlistitem_set.create(video=video)
        output = video_helpers.get_video_upload_to_directory(instance=video)
        self.assertEqual(pathlib.PurePosixPath, type(output))
        self.assertEqual(pathlib.PurePosixPath("test playlist dir/"), output)

    def test_video_upload_to_side_by_side(self):
        video = models.Video.objects.create(title="Test Video 1")
        output = video_helpers.video_upload_to_side_by_side(instance=video, filename="test.mp4")
        self.assertEqual(f"public/{timezone.now().year}/test.mp4", str(output))

        channel = models.Channel.objects.create(name="test channel")
        video = models.Video.objects.create(
            title="Test Video 1", channel=channel, provider_object_id="test-id",
            upload_date=date_to_aware_date('2025-01-01')
        )
        output = video_helpers.video_upload_to_side_by_side(instance=video, filename="test.mp4")
        self.assertEqual("test channel/2025/2025-01-01 - Test Video 1 [test-id]/test.mp4", str(output))

    def test_upload_to_file_and_infojson_and_thumbnail(self):
        video = models.Video.objects.create(title="Test Video 1", upload_date=date_to_aware_date('2025-01-01'))

        output = video_helpers.upload_to_file(instance=video, filename="test.mp4")
        self.assertEqual("public/2025/test.mp4", str(output))
        output = video_helpers.upload_to_infojson(instance=video, filename="test.info.json")
        self.assertEqual("public/2025/test.info.json", str(output))
        output = video_helpers.upload_to_thumbnail(instance=video, filename="test.jpg")
        self.assertEqual("public/2025/test.jpg", str(output))

        channel = models.Channel.objects.create(name="test channel")
        video = models.Video.objects.create(
            title="Test Video 1",
            channel=channel,
            provider_object_id="test-id",
            upload_date=date_to_aware_date('2025-01-01'))

        output = video_helpers.upload_to_file(instance=video, filename="test.mp4")
        self.assertEqual("test channel/2025/2025-01-01 - Test Video 1 [test-id]/test.mp4", str(output))

        output = video_helpers.upload_to_infojson(instance=video, filename="test.info.json")
        self.assertEqual("test channel/2025/2025-01-01 - Test Video 1 [test-id]/test.info.json", str(output))

        output = video_helpers.upload_to_thumbnail(instance=video, filename="test.jpg")
        self.assertEqual("test channel/2025/2025-01-01 - Test Video 1 [test-id]/test.jpg", str(output))

    def test_default_quality(self):
        self.assertEqual(app_settings.DEFAULT_QUALITY, video_helpers.default_quality())

    def test_upload_to_audio_without_channel_with_upload_date(self):
        video = models.Video.objects.create(title="test video 1", upload_date=date_to_aware_date('2023-01-01'))
        output = video_helpers.upload_to_audio(instance=video, filename="test.mp3")
        self.assertEqual('public/2023/test.mp3', str(output))

    def test_upload_to_audio_without_channel_nor_upload_date(self):
        video = models.Video.objects.create(title="test video 1")
        output = video_helpers.upload_to_audio(instance=video, filename="test.mp3")
        self.assertEqual(f'public/{timezone.now().year}/test.mp3', str(output))

    def test_upload_to_audio_with_channel_with_upload_date(self):
        channel = models.Channel.objects.create(name="Test Channel")
        video = models.Video.objects.create(
            channel=channel,
            title="test video 1",
            upload_date=date_to_aware_date('2023-01-01'),
        )
        output = video_helpers.upload_to_audio(instance=video, filename="test.mp3")
        self.assertEqual('Test Channel/2023/2023-01-01 - test video 1 []/test.mp3', str(output))

    def test_upload_to_audio_with_channel_nor_upload_date(self):
        channel = models.Channel.objects.create(name="Test Channel")
        video = models.Video.objects.create(title="test video 1", channel=channel)
        output = video_helpers.upload_to_audio(instance=video, filename="test.mp3")
        self.assertEqual(f'Test Channel/{timezone.now().year}/- test video 1 []/test.mp3', str(output))


class ExtraFileHelpersTests(TestCase):

    def test_extrafile_file_upload_to_without_channel_with_upload_date(self):
        video = models.Video.objects.create(title="test video 1", upload_date=date_to_aware_date('2023-01-01'))
        ef = models.ExtraFile.objects.create(video=video)
        output = extrafile_helpers.extrafile_file_upload_to(instance=ef, filename="test.mp3")
        self.assertEqual('public/2023/test.mp3', str(output))

    def test_extrafile_file_upload_to_without_channel_nor_upload_date(self):
        video = models.Video.objects.create(title="test video 1")
        ef = models.ExtraFile.objects.create(video=video)
        output = extrafile_helpers.extrafile_file_upload_to(instance=ef, filename="test.mp3")
        self.assertEqual(f'public/{timezone.now().year}/test.mp3', str(output))

    def test_extrafile_file_upload_to_with_channel_with_upload_date(self):
        channel = models.Channel.objects.create(name="Test Channel")
        video = models.Video.objects.create(
            channel=channel,
            title="test video 1",
            upload_date=date_to_aware_date('2023-01-01'),
        )
        ef = models.ExtraFile.objects.create(video=video)
        output = extrafile_helpers.extrafile_file_upload_to(instance=ef, filename="test.mp3")
        self.assertEqual('Test Channel/2023/2023-01-01 - test video 1 []/test.mp3', str(output))

    def test_extrafile_file_upload_to_with_channel_nor_upload_date(self):
        channel = models.Channel.objects.create(name="Test Channel")
        video = models.Video.objects.create(title="test video 1", channel=channel)
        ef = models.ExtraFile.objects.create(video=video)
        output = extrafile_helpers.extrafile_file_upload_to(instance=ef, filename="test.mp3")
        self.assertEqual(f'Test Channel/{timezone.now().year}/- test video 1 []/test.mp3', str(output))


class StatisticsHelpersTests(TestCase):

    def test_channel_most_common_date_weekday_returns_zero_through_six_only(self):
        channel = models.Channel.objects.create(
            provider_object_id='tests',
        )
        channel.videos.create(provider_object_id='tests', upload_date='2024-09-01')

        self.assertEqual(0, statistics_helpers.most_common_date_weekday(queryset=channel.videos))

        models.Video.objects.all().update(upload_date='2024-09-02')
        self.assertEqual(1, statistics_helpers.most_common_date_weekday(queryset=channel.videos))

        models.Video.objects.all().update(upload_date='2024-09-03')
        self.assertEqual(2, statistics_helpers.most_common_date_weekday(queryset=channel.videos))

        models.Video.objects.all().update(upload_date='2024-09-04')
        self.assertEqual(3, statistics_helpers.most_common_date_weekday(queryset=channel.videos))

        models.Video.objects.all().update(upload_date='2024-09-05')
        self.assertEqual(4, statistics_helpers.most_common_date_weekday(queryset=channel.videos))

        models.Video.objects.all().update(upload_date='2024-09-06')
        self.assertEqual(5, statistics_helpers.most_common_date_weekday(queryset=channel.videos))

        models.Video.objects.all().update(upload_date='2024-09-07')
        self.assertEqual(6, statistics_helpers.most_common_date_weekday(queryset=channel.videos))

        models.Video.objects.all().update(upload_date='2024-09-08')
        self.assertEqual(0, statistics_helpers.most_common_date_weekday(queryset=channel.videos))

    def test_channel_most_common_date_day_of_month(self):
        channel = models.Channel.objects.create(
            provider_object_id='tests',
        )
        channel.videos.create(provider_object_id='tests', upload_date='2024-09-19')

        self.assertEqual(19, statistics_helpers.most_common_date_day_of_month(queryset=channel.videos))

    def test_channel_most_common_date_day_of_month_with_multiple_videos_on_separate_days(self):
        channel = models.Channel.objects.create(
            provider_object_id='tests',
        )
        channel.videos.create(provider_object_id='tests', upload_date='2024-09-19')
        channel.videos.create(provider_object_id='tests', upload_date='2024-08-18')

        self.assertEqual(19, statistics_helpers.most_common_date_day_of_month(queryset=channel.videos))

    def test_channel_most_common_date_day_of_month_with_multiple_videos_on_same_days(self):
        channel = models.Channel.objects.create(
            provider_object_id='tests',
        )
        channel.videos.create(provider_object_id='tests', upload_date='2024-09-19')
        channel.videos.create(provider_object_id='tests', upload_date='2024-08-18')
        channel.videos.create(provider_object_id='tests', upload_date='2024-08-19')

        self.assertEqual(19, statistics_helpers.most_common_date_day_of_month(queryset=channel.videos))

    def test_channel_most_common_date_day_of_month_with_31st_as_most_common_returns_30(self):
        channel = models.Channel.objects.create(
            provider_object_id='tests',
        )
        channel.videos.create(provider_object_id='tests', upload_date='2024-08-31')
        channel.videos.create(provider_object_id='tests', upload_date='2024-08-18')
        channel.videos.create(provider_object_id='tests', upload_date='2024-08-31')

        self.assertEqual(30, statistics_helpers.most_common_date_day_of_month(queryset=channel.videos))

    def test_channel_most_common_date_week_of_year(self):
        channel = models.Channel.objects.create(provider_object_id='tests')
        channel.videos.create(provider_object_id='tests1', upload_date='2024-09-19')
        channel.videos.create(provider_object_id='tests2', upload_date='2024-09-20')
        channel.videos.create(provider_object_id='tests3', upload_date='2024-12-20')

        self.assertEqual(38, statistics_helpers.most_common_date_week_of_year(queryset=channel.videos))


class FileHelpersTests(TestCase):

    def test_is_field_using_local_storage(self):
        video = models.Video.objects.create()
        self.assertTrue(file_helpers.is_field_using_local_storage(video.file))

    def test_is_field_using_local_storage_custom(self):
        video = models.Video.objects.create()
        class CustomStorage:
            pass
        video.file.storage = CustomStorage()
        self.assertFalse(file_helpers.is_field_using_local_storage(video.file))

    def test_can_file_be_moved(self):
        video = models.Video.objects.create()
        self.assertTrue(file_helpers.can_file_be_moved(video.file))

    def test_can_file_be_moved_other_storage(self):
        video = models.Video.objects.create()
        class CustomStorage:
            pass
        video.file.storage = CustomStorage()
        self.assertFalse(file_helpers.can_file_be_moved(video.file))

    def test_ensure_file_is_local(self):
        video = models.Video.objects.create(file="test.mp4")
        local_filepath, was_remote = file_helpers.ensure_file_is_local(video.file)
        self.assertFalse(was_remote)

    @patch("os.fdopen")
    @patch("tempfile.mkstemp")
    def test_ensure_file_is_local_other_storage(self, mock_temp, mock_fdopen):
        mock_temp.return_value = (1, "path value")
        video = models.Video.objects.create(file="test.mp4")
        class CustomStorage:
            def open(self, *args, **kwargs):
                return self
            def read(self, *args, **kwargs):
                return ""
            def close(self, *args, **kwargs):
                return ""
        video.file.storage = CustomStorage()
        local_filepath, was_remote = file_helpers.ensure_file_is_local(video.file)
        self.assertTrue(was_remote)

        mock_fdopen.assert_called_once()
        mock_temp.assert_called_once()

    def test_should_should_convert_to_html_playable_format(self):
        filepath = '/test/file.mkv'
        self.assertTrue(file_helpers.should_convert_to_html_playable_format(filepath=filepath))

    def test_should_should_convert_to_html_playable_format_as_pathlib(self):
        filepath = pathlib.Path('/test/file.mkv')
        self.assertTrue(file_helpers.should_convert_to_html_playable_format(filepath=filepath))

    def test_should_should_convert_to_html_playable_format_as_mp4(self):
        filepath = pathlib.Path('/test/file.mp4')
        self.assertFalse(file_helpers.should_convert_to_html_playable_format(filepath=filepath))

    @patch("moviepy.VideoFileClip")
    @patch("tempfile.mkstemp")
    def test_convert_to_html_playable_format(self, mock_mkstemp, mock_moviepy):
        mock_mkstemp.return_value = ("", "output dir/test.mp4")

        clipper = MagicMock()
        mock_moviepy.return_value = clipper

        filepath = pathlib.Path("/test/file.mkv")
        output = file_helpers.convert_to_html_playable_format(filepath=filepath)

        mock_moviepy.assert_called_once_with(filepath)
        clipper.write_videofile.assert_called_once_with("output dir/test.mp4")

        self.assertEqual("output dir/test.mp4", output)

    @patch("moviepy.VideoFileClip")
    @patch("tempfile.mkstemp")
    def test_convert_to_audio_format(self, mock_mkstemp, mock_moviepy):
        mock_mkstemp.return_value = ("", "output dir/test.mp3")

        clipper = MagicMock()
        mock_moviepy.return_value = clipper

        filepath = pathlib.Path("/test/file.mkv")
        output = file_helpers.convert_to_audio_format(filepath=filepath)

        mock_moviepy.assert_called_once_with(filepath)
        clipper.audio.write_audiofile.assert_called_once_with("output dir/test.mp3", logger=None)

        self.assertEqual("output dir/test.mp3", output)


class ChannelHelpersTests(TestCase):
    def test_watched_percentage_minimum(self):
        with self.assertRaises(ValidationError):
            channel_helpers.watched_percentage_minimum(0)
        self.assertIsNone(channel_helpers.watched_percentage_minimum(1))

    def test_watched_percentage_maximum(self):
        with self.assertRaises(ValidationError):
            channel_helpers.watched_percentage_maximum(101)
        self.assertIsNone(channel_helpers.watched_percentage_maximum(100))

    def test_upload_to_fields(self):
        channel = models.Channel.objects.create(name="Test Channel")

        output = channel_helpers.upload_to_banner(instance=channel, filename="banner.jpg")
        self.assertEqual("Test Channel/banner.jpg", str(output))

        output = channel_helpers.upload_to_thumbnail(instance=channel, filename="thumbnail.jpg")
        self.assertEqual("Test Channel/thumbnail.jpg", str(output))

        output = channel_helpers.upload_to_tvart(instance=channel, filename="tvart.jpg")
        self.assertEqual("Test Channel/tvart.jpg", str(output))
