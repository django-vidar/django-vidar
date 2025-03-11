import datetime
import json

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings, TestCase
from django.utils import timezone

from vidar import models, app_settings, exceptions


UserModel = get_user_model()


class ChannelTests(TestCase):
    def test_videos_at_max_quality(self):
        channel = models.Channel.objects.create()
        channel.videos.create(at_max_quality=True, file='test.mp4')
        self.assertEqual(1, channel.videos_at_max_quality.count())
        channel.videos.create(file='test.mp4')
        self.assertEqual(1, channel.videos_at_max_quality.count())

    def test_next_runtime(self):
        channel = models.Channel.objects.create(
            scanner_crontab='10 16 * * *',
        )
        ts = timezone.now().replace(hour=14, minute=59, second=0, microsecond=0)
        with patch.object(timezone, 'localtime', return_value=ts):
            output = channel.next_runtime

        expected_ts = ts.replace(hour=16, minute=10)

        self.assertEqual(expected_ts, output)

    def test_average_days_between_upload(self):
        channel = models.Channel.objects.create()
        channel.videos.create(upload_date='2024-05-17')
        channel.videos.create(upload_date='2025-01-01')
        channel.videos.create(upload_date='2025-01-10')
        channel.videos.create(upload_date='2025-01-20')
        channel.videos.create(upload_date='2025-01-30')
        channel.videos.create(upload_date='2025-02-09')
        channel.videos.create(upload_date='2025-02-19')
        self.assertEqual(10.0, channel.average_days_between_upload(limit_to_latest_videos=5))

    def test_average_days_between_upload_returns_none_with_too_few_videos(self):
        channel = models.Channel.objects.create()
        channel.videos.create(upload_date='2024-05-17')
        self.assertIsNone(channel.average_days_between_upload())

    def test_days_since_last_upload(self):
        ts = timezone.now()

        channel = models.Channel.objects.create()
        channel.videos.create(upload_date=ts.strftime('%Y-%m-%d'))
        channel.videos.create(upload_date=ts.strftime('%Y-%m-%d'))

        ts += timezone.timedelta(days=4)

        with patch.object(timezone, 'now', return_value=ts):
            self.assertEqual(4, channel.days_since_last_upload())

    def test_calculated_methods(self):
        channel = models.Channel.objects.create()
        channel.videos.create(file='test.mp4', file_size=100, duration=100)
        channel.videos.create(file='test.mp4', file_size=100, duration=100)
        channel.videos.create(file='test.mp4', file_size=100, duration=100)
        channel.videos.create(file='test.mp4', file_size=100, duration=100)
        channel.videos.create(file='test.mp4', file_size=100, duration=100)
        channel.videos.create(file='test.mp4', file_size=100, duration=100)
        channel.videos.create(duration=100)

        self.assertEqual(600, channel.calculated_file_size())
        self.assertEqual(700, channel.total_video_durations())
        self.assertEqual(600, channel.total_archived_video_durations())

    def test_existing_video_qualities(self):
        channel = models.Channel.objects.create()
        channel.videos.create(file='test.mp4', file_size=100, duration=100, quality=480)
        channel.videos.create(file='test.mp4', file_size=100, duration=100, quality=480)
        channel.videos.create(file='test.mp4', file_size=100, duration=100, quality=1440)
        channel.videos.create(file='test.mp4', file_size=100, duration=100, quality=720)
        channel.videos.create(file='test.mp4', file_size=100, duration=100, quality=720)
        channel.videos.create(file='test.mp4', file_size=100, duration=100, quality=1080, at_max_quality=True)
        channel.videos.create(duration=100)

        output = channel.existing_video_qualities()

        self.assertEqual(4, len(output))
        self.assertIn(480, output)
        self.assertIn(720, output)
        self.assertIn(1080, output)
        self.assertIn(1440, output)

        self.assertEqual((2, 200, 0), output[480])
        self.assertEqual((2, 200, 0), output[720])
        self.assertEqual((1, 100, 1), output[1080])
        self.assertEqual((1, 100, 0), output[1440])

    def test_all_video_privacy_statuses(self):
        channel = models.Channel.objects.create()
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.UNLISTED)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.UNLISTED)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.BLOCKED)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC)
        channel.videos.create(duration=100)

        output = channel.all_video_privacy_statuses()

        self.assertEqual(3, len(output))

        self.assertIn(models.Video.VideoPrivacyStatuses.PUBLIC, output)
        self.assertIn(models.Video.VideoPrivacyStatuses.UNLISTED, output)
        self.assertIn(models.Video.VideoPrivacyStatuses.BLOCKED, output)

        self.assertEqual((4, 300), output[models.Video.VideoPrivacyStatuses.PUBLIC])
        self.assertEqual((2, 200), output[models.Video.VideoPrivacyStatuses.UNLISTED])
        self.assertEqual((1, 100), output[models.Video.VideoPrivacyStatuses.BLOCKED])

    def test_existing_video_privacy_statuses(self):
        channel = models.Channel.objects.create()
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.UNLISTED)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.UNLISTED)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.BLOCKED)
        channel.videos.create(file='test.mp4', file_size=100, privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC)
        channel.videos.create()

        output = channel.existing_video_privacy_statuses()

        self.assertEqual(3, len(output))

        self.assertIn(models.Video.VideoPrivacyStatuses.PUBLIC, output)
        self.assertIn(models.Video.VideoPrivacyStatuses.UNLISTED, output)
        self.assertIn(models.Video.VideoPrivacyStatuses.BLOCKED, output)

        self.assertEqual((3, 300), output[models.Video.VideoPrivacyStatuses.PUBLIC])
        self.assertEqual((2, 200), output[models.Video.VideoPrivacyStatuses.UNLISTED])
        self.assertEqual((1, 100), output[models.Video.VideoPrivacyStatuses.BLOCKED])


class VideoMethodTests(TestCase):

    def test_set_and_get_latest_download_stats(self):
        video = models.Video.objects.create(title="test video")
        ts1 = timezone.now().isoformat()
        video.set_latest_download_stats(test_value=ts1)
        self.assertIn("downloads", video.system_notes)
        self.assertEqual(1, len(video.system_notes["downloads"]))

        ts2 = timezone.now().isoformat()
        video.set_latest_download_stats(test_value=ts2,)
        self.assertEqual(2, len(video.system_notes["downloads"]))

        latest_download = video.get_latest_download_stats()
        self.assertEqual({"test_value": ts2}, latest_download)

        with self.assertRaises(TypeError):
            video.set_latest_download_stats(test_value=video)

    def test_get_latest_download_stats_returns_dict_on_no_attmpt(self):
        video = models.Video.objects.create(title="test video")
        self.assertEqual({}, video.get_latest_download_stats())

    def test_append_to_latest_download_stats(self):
        video = models.Video.objects.create(title="test video")
        video.set_latest_download_stats(tester="here")

        self.assertIn("downloads", video.system_notes)
        self.assertEqual(1, len(video.system_notes["downloads"]))

        self.assertEqual({"tester": "here"}, video.get_latest_download_stats())

        video.append_to_latest_download_stats(another="test")

        self.assertEqual(1, len(video.system_notes["downloads"]))

        self.assertEqual({"tester": "here", "another": "test"}, video.get_latest_download_stats())

    def test_append_to_latest_download_stats_without_existing(self):
        video = models.Video.objects.create(title="test video")
        video.append_to_latest_download_stats(another="test")

        self.assertIn("downloads", video.system_notes)
        self.assertEqual(1, len(video.system_notes["downloads"]))

        self.assertEqual({"another": "test"}, video.get_latest_download_stats())

    def test_set_append_latest_download_stats_timezone_converts_to_isoformat_auto(self):
        video = models.Video.objects.create(title="test video")

        ts = timezone.now()

        try:
            video.set_latest_download_stats(test=ts)
        except TypeError:
            self.fail("set_latest_download_stats should have converted timezone.now to isoformat")

        latest = video.get_latest_download_stats()
        self.assertEqual(ts.isoformat(), latest["test"])

        ts2 = timezone.now()
        try:
            video.append_to_latest_download_stats(another=ts2)
        except TypeError:
            self.fail("append_to_latest_download_stats should have converted timezone.now to isoformat")

        latest = video.get_latest_download_stats()
        self.assertEqual(ts2.isoformat(), latest["another"])

    def test_get_or_create_from_ytdlp_response_creates(self):

        video, created = models.Video.get_or_create_from_ytdlp_response({
            "id": "provider-id",
            "title": "video title",
            "description": "video desc",
        })
        self.assertTrue(created)
        self.assertEqual("provider-id", video.provider_object_id)
        self.assertEqual("video title", video.title)
        self.assertEqual("video desc", video.description)

    def test_get_or_create_from_ytdlp_response_existing(self):

        models.Video.objects.create(provider_object_id="provider-id")

        video, created = models.Video.get_or_create_from_ytdlp_response({
            "id": "provider-id",
            "title": "video title",
            "description": "video desc",
        })
        self.assertFalse(created)
        self.assertEqual("provider-id", video.provider_object_id)
        self.assertEqual("video title", video.title)
        self.assertEqual("video desc", video.description)

    def test_set_details_from_yt_dlp_response(self):
        with open('vidar/tests/dlp_response.json') as fo:
            data = json.load(fo)
        with open('vidar/tests/dlp_formats.json') as fo:
            dlp_formats = json.load(fo)['formats']
            data['formats'] = dlp_formats

        video = models.Video.objects.create(title="here")
        video.set_details_from_yt_dlp_response(data=data)

        self.assertEqual(data['channel_id'], video.channel_provider_object_id)
        self.assertEqual(data['title'], video.title)
        self.assertEqual(data['description'], video.description)
        self.assertEqual(data["view_count"], video.view_count)
        self.assertEqual(data["like_count"], video.like_count)
        self.assertEqual(data["duration"], video.duration)
        self.assertEqual(data["width"], video.width)
        self.assertEqual(data["height"], video.height)
        self.assertEqual(data["fps"], video.fps)
        self.assertIsNotNone(video.upload_date)
        self.assertEqual(models.Video.VideoPrivacyStatuses.PUBLIC, video.privacy_status)
        self.assertIsNotNone(video.last_privacy_status_check)
        self.assertCountEqual(dlp_formats, video.dlp_formats)

    def test_set_details_from_yt_dlp_response_locked_title(self):
        video = models.Video.objects.create(
            title="here",
            title_locked=True,
            description="old desc",
            description_locked=False,
        )
        video.set_details_from_yt_dlp_response(data={
            "title": "a new title",
            "description": "a new description",
        })

        self.assertEqual("here", video.title)
        self.assertEqual("a new description", video.description)

    def test_set_details_from_yt_dlp_response_locked_description(self):
        video = models.Video.objects.create(
            title="old title",
            title_locked=False,
            description="here 2",
            description_locked=True,
        )
        video.set_details_from_yt_dlp_response(data={
            "title": "a new title",
            "description": "a new description",
        })

        self.assertEqual("a new title", video.title)
        self.assertEqual("here 2", video.description)

    def test_set_details_from_yt_dlp_response_unlocked_fields_missing_data(self):
        video = models.Video.objects.create(
            title_locked=False,
            description_locked=False,
        )
        video.set_details_from_yt_dlp_response(data={
            "title": "a new title",
            "description": "a new description",
        })

        self.assertEqual("a new title", video.title)
        self.assertEqual("a new description", video.description)

    def test_set_details_from_yt_dlp_response_availability_options(self):
        video = models.Video.objects.create()
        video.set_details_from_yt_dlp_response(data={"availability": "unlisted"})
        self.assertEqual(models.Video.VideoPrivacyStatuses.UNLISTED, video.privacy_status)

        video.set_details_from_yt_dlp_response(data={"title": "here", "description": "here", "availability": "new status"})
        self.assertEqual(models.Video.VideoPrivacyStatuses.PUBLIC, video.privacy_status)

        video.set_details_from_yt_dlp_response(data={"title": "here", "description": "", "availability": "new status"})
        self.assertEqual("new status", video.privacy_status)

    def test_set_details_from_yt_dlp_response_shorts(self):
        video = models.Video.objects.create()
        video.set_details_from_yt_dlp_response(data={
            "original_url": "/shorts/blah"
        })
        self.assertTrue(video.is_short)
        self.assertFalse(video.is_livestream)
        self.assertFalse(video.is_video)

    def test_set_details_from_yt_dlp_response_livestreams(self):
        video = models.Video.objects.create()
        video.set_details_from_yt_dlp_response(data={
            "was_live": True,
        })
        self.assertFalse(video.is_short)
        self.assertTrue(video.is_livestream)
        self.assertFalse(video.is_video)

    def test_set_details_from_yt_dlp_response_videos(self):
        video = models.Video.objects.create()
        video.set_details_from_yt_dlp_response(data={})
        self.assertFalse(video.is_short)
        self.assertFalse(video.is_livestream)
        self.assertTrue(video.is_video)

    def test_qualities_available(self):
        with open('vidar/tests/dlp_formats.json') as fo:
            dlp_formats = json.load(fo)['formats']

        video = models.Video.objects.create(dlp_formats=dlp_formats)
        self.assertEqual([144, 240, 360, 480, 720, 1080, 1440, 2160], video.qualities_available())

        video = models.Video.objects.create()
        self.assertEqual([app_settings.DEFAULT_QUALITY], video.qualities_available())

        video = models.Video.objects.create(quality=480)
        self.assertEqual([480], video.qualities_available())

    def test_qualities_upgradable(self):
        with open('vidar/tests/dlp_formats.json') as fo:
            dlp_formats = json.load(fo)['formats']

        video = models.Video.objects.create(quality=480, dlp_formats=dlp_formats)
        self.assertEqual(
            {720, 1080, 1440, 2160},
            video.qualities_upgradable(),
            "Should have returned only qualities above current video quality",
        )

        video = models.Video.objects.create(dlp_formats=dlp_formats)
        self.assertEqual(
            [144, 240, 360, 480, 720, 1080, 1440, 2160],
            video.qualities_upgradable(),
            "Should have returned all available qualities"
        )

        video = models.Video.objects.create(quality=480)
        self.assertEqual([480], video.qualities_upgradable())

    def test_channel_page_number(self):
        channel = models.Channel.objects.create(name='test channel')

        ts = timezone.now() - timezone.timedelta(days=2)
        for x in range(20):
            channel.videos.create(upload_date=ts)
            ts += timezone.timedelta(days=1)

        first_video = channel.videos.first()
        self.assertEqual(0, first_video.channel_page_number())

        last_video = channel.videos.last()
        self.assertEqual(2, last_video.channel_page_number())

    def test_save_download_kwargs_does_not_save_progress_hooks(self):

        video = models.Video.objects.create()
        video.save_download_kwargs({
            'progress_hooks': [self],
            'second': 'here',
        })
        self.assertNotIn("progress_hooks", video.download_kwargs)
        self.assertIn("second", video.download_kwargs)
        self.assertEqual("here", video.download_kwargs['second'])

    def test_save_system_notes(self):
        video = models.Video.objects.create()
        video.save_system_notes({"proxy": "proxy addy"})
        self.assertIn("proxies_attempted", video.system_notes)
        self.assertEqual(1, len(video.system_notes["proxies_attempted"]))
        self.assertIn("proxy addy", video.system_notes["proxies_attempted"])
        video.save_system_notes({"proxy": "proxy addy"})
        self.assertEqual(2, video.system_notes["proxies_attempted"].count('proxy addy'))

    def test_apply_privacy_status_based_on_dlp_exception_message(self):
        video = models.Video.objects.create()
        video.apply_privacy_status_based_on_dlp_exception_message("This video is blocked in yor country")
        self.assertEqual(models.Video.VideoPrivacyStatuses.BLOCKED, video.privacy_status)

        video.apply_privacy_status_based_on_dlp_exception_message("This video is private video")
        self.assertEqual(models.Video.VideoPrivacyStatuses.PRIVATE, video.privacy_status)

        video.apply_privacy_status_based_on_dlp_exception_message("This video unavailable")
        self.assertEqual(models.Video.VideoPrivacyStatuses.UNAVAILABLE, video.privacy_status)

        video.apply_privacy_status_based_on_dlp_exception_message("This video is not unavailable")
        self.assertEqual(models.Video.VideoPrivacyStatuses.UNAVAILABLE, video.privacy_status)

        msgs = [
            "This is a deleted video",
            "Video pulled for copyright claim",
            "The account has been terminated",
            "The account has been closed",
            "Video removed for harassment",
            "Video removed for bullying",
        ]
        for msg in msgs:
            video.apply_privacy_status_based_on_dlp_exception_message(msg)
            self.assertEqual(models.Video.VideoPrivacyStatuses.DELETED, video.privacy_status)

        video.apply_privacy_status_based_on_dlp_exception_message("This is a deleted video")
        self.assertEqual(models.Video.VideoPrivacyStatuses.DELETED, video.privacy_status)

    def test_is_at_max_quality(self):
        video = models.Video.objects.create(at_max_quality=True)
        self.assertTrue(video.is_at_max_quality())

        with open('vidar/tests/dlp_formats.json') as fo:
            dlp_formats = json.load(fo)['formats']
        video = models.Video.objects.create(dlp_formats=dlp_formats, quality=2160)
        self.assertFalse(video.at_max_quality)
        self.assertTrue(video.is_at_max_quality())
        self.assertTrue(video.at_max_quality)

    def test_save_title_description_changes_logs_to_history(self):
        video = models.Video.objects.create(
            title='old title',
            description='old description',
            privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC,
        )

        self.assertEqual(0, video.change_history.count())

        video.title = 'new title'
        video.description = 'new description'
        video.privacy_status = models.Video.VideoPrivacyStatuses.UNLISTED
        video.save()

        self.assertEqual(1, video.change_history.count())

        history = video.change_history.get()

        self.assertEqual("old title", history.old_title)
        self.assertEqual("new title", history.new_title)
        self.assertEqual("old description", history.old_description)
        self.assertEqual("new description", history.new_description)
        self.assertEqual(models.Video.VideoPrivacyStatuses.PUBLIC, history.old_privacy_status)
        self.assertEqual(models.Video.VideoPrivacyStatuses.UNLISTED, history.new_privacy_status)

    def test_direct_delete_not_permitted(self):
        video = models.Video.objects.create()

        with self.assertRaises(exceptions.UnauthorizedVideoDeletionError):
            video.delete()

        num, obj_types_and_num = video.delete(deletion_permitted=True)
        self.assertEqual(1, num)
        self.assertEqual({"vidar.Video": 1}, obj_types_and_num)

    def test_duration_as_timedelta(self):
        video = models.Video.objects.create(duration=500)
        self.assertEqual(datetime.timedelta(seconds=500), video.duration_as_timedelta())

    def test_check_and_add_video_to_playlists_based_on_title_matching(self):
        video = models.Video.objects.create(title="testing professional kitchen equipment")

        models.Playlist.objects.create(
            title="Pro kitchen stuffs",
            video_indexing_add_by_title="professional kitchen",
        )

        self.assertEqual(0, video.playlists.count())

        video.check_and_add_video_to_playlists_based_on_title_matching()

        self.assertEqual(1, video.playlists.count())

    def test_check_and_add_video_to_playlists_based_on_title_matching_channel_limited(self):
        channel = models.Channel.objects.create(name='test channel')
        video = models.Video.objects.create(title="testing professional kitchen equipment", channel=channel)

        playlist = models.Playlist.objects.create(
            title="Pro kitchen stuffs",
            video_indexing_add_by_title="professional kitchen",
        )
        playlist.video_indexing_add_by_title_limit_to_channels.add(channel)

        self.assertEqual(0, video.playlists.count())

        video.check_and_add_video_to_playlists_based_on_title_matching()

        self.assertEqual(1, video.playlists.count())

    def test_check_and_add_video_to_playlists_based_on_title_matching_channel_limited_no_match_video_has_channel(self):
        channel1 = models.Channel.objects.create(name='test channel 1')
        channel2 = models.Channel.objects.create(name='test channel 2')

        video = models.Video.objects.create(title="testing professional kitchen equipment", channel=channel2)

        playlist = models.Playlist.objects.create(
            title="Pro kitchen stuffs",
            video_indexing_add_by_title="professional kitchen",
        )
        playlist.video_indexing_add_by_title_limit_to_channels.add(channel1)

        self.assertEqual(0, video.playlists.count())

        video.check_and_add_video_to_playlists_based_on_title_matching()

        self.assertEqual(0, video.playlists.count())

    def test_check_and_add_video_to_playlists_based_on_title_matching_channel_limited_no_match_video_without_channel(self):
        channel1 = models.Channel.objects.create(name='test channel 1')

        video = models.Video.objects.create(title="testing professional kitchen equipment")

        playlist = models.Playlist.objects.create(
            title="Pro kitchen stuffs",
            video_indexing_add_by_title="professional kitchen",
        )
        playlist.video_indexing_add_by_title_limit_to_channels.add(channel1)

        self.assertEqual(0, video.playlists.count())

        video.check_and_add_video_to_playlists_based_on_title_matching()

        self.assertEqual(0, video.playlists.count())

    def test_search_description_for_related_videos(self):
        video = models.Video.objects.create(
            provider_object_id='id0-original',
            description="""
        This is my videos description with 4 links to videos of which 2 should 
            be found in the system and related to this video
        
        https://www.youtube.com/watch?v=id1-related - episode 1
        https://www.youtube.com/watch?v=id2-related episode 2
        https://youtube.com/watch?v=something-not-related another channels video that sponsored this one
        https://www.youtube.com/watch?v=something-else-not-related another unrelated video not in the system
        https://www.youtube.com/watch?v=id0-original for reasons unknown some people link back to their own video!
        https://www.google.com a link to somewhere else
        """,
        )

        v1 = models.Video.objects.create(provider_object_id='id1-related')
        v2 = models.Video.objects.create(provider_object_id='id2-related')
        v3 = models.Video.objects.create(provider_object_id='id3-not-related')
        v4 = models.Video.objects.create(provider_object_id='id4-not-related')

        video.search_description_for_related_videos()

        self.assertEqual(2, video.related.count())

        self.assertTrue(video.related.filter(pk=v1.pk))
        self.assertTrue(video.related.filter(pk=v2.pk))
        self.assertFalse(video.related.filter(pk=v3.pk))
        self.assertFalse(video.related.filter(pk=v4.pk))

        v3.search_description_for_related_videos()

        if v3.related.exists():
            self.fail("v3 should not have been related to anything.")

    @override_settings(VIDAR_VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS=2)
    def test_at_max_download_errors_for_period(self):
        video = models.Video.objects.create()
        self.assertFalse(video.at_max_download_errors_for_period())

        ts = timezone.now() - timezone.timedelta(hours=48)
        with patch.object(timezone, 'now', return_value=ts):
            video.download_errors.create()

        ts = timezone.now() - timezone.timedelta(hours=48)
        with patch.object(timezone, 'now', return_value=ts):
            video.download_errors.create()

        self.assertEqual(2, video.download_errors.count())

        self.assertFalse(video.at_max_download_errors_for_period())

        video.download_errors.create()
        video.download_errors.create()

        self.assertTrue(video.at_max_download_errors_for_period())

    def test_log_to_scanhistory_no_history_without_channel(self):
        video = models.Video.objects.create(provider_object_id='id')
        self.assertIsNone(video.log_to_scanhistory())

    def test_log_to_scanhistory_exists_before_logging(self):
        channel = models.Channel.objects.create(name='channel')
        video = models.Video.objects.create(provider_object_id='id', channel=channel)
        self.assertIsNone(video.log_to_scanhistory())

        channel.scan_history.create()

        self.assertTrue(video.log_to_scanhistory())


class VideoBlockedTests(TestCase):
    def test_is_local(self):
        vb = models.VideoBlocked.objects.create(provider_object_id='blocked-id')
        self.assertFalse(vb.is_still_local())

        models.Video.objects.create(provider_object_id='blocked-id')
        self.assertTrue(vb.is_still_local())


class VideoDownloadErrorTests(TestCase):

    def test_save_kwargs_does_not_save_progress_hooks(self):

        video = models.Video.objects.create()
        de = video.download_errors.create(
            video=video,
        )
        de.save_kwargs(dict(inside="here", progress_hooks=['here', 'two']))
        self.assertNotIn("progress_hooks", de.kwargs)
        self.assertIn("inside", de.kwargs)
        self.assertEqual("here", de.kwargs['inside'])


class VideoHistoryTests(TestCase):

    def test_all_fields_changed(self):
        video = models.Video.objects.create(
            title='old title',
            description='old description',
            privacy_status=models.Video.VideoPrivacyStatuses.PUBLIC,
        )

        video.title = 'new title'
        video.description = 'new description'
        video.privacy_status = models.Video.VideoPrivacyStatuses.UNLISTED
        video.save()

        history = video.change_history.get()

        self.assertTrue(history.title_changed())
        self.assertTrue(history.description_changed())
        self.assertTrue(history.privacy_status_changed())

        expected_diff = "<h3>Title</h3>\n- old title\n+ new title\n<h3>Description</h3>\n- old " \
                        "description\n? ^^^\n\n+ new description\n? ^^^\n\n<h3>Status</h3>\n- Public\n+ Unlisted"
        output = history.diff()
        self.assertEqual(expected_diff, output)

    def test_only_title_changed(self):
        video = models.Video.objects.create(
            title='old title',
            description='old description',
        )

        video.title = 'new title'
        video.description = 'old description'
        video.save()

        history = video.change_history.get()

        self.assertTrue(history.title_changed())
        self.assertFalse(history.description_changed())
        self.assertFalse(history.privacy_status_changed())

        expected_diff = "- old title\n+ new title"
        output = history.diff()
        self.assertEqual(expected_diff, output)


class UserPlaybackHistoryTests(TestCase):
    def test_completion_percentage(self):
        video = models.Video.objects.create(duration=500)
        user = UserModel.objects.create(username='test')

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=125)
        self.assertEqual(25.0, history.completion_percentage())

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=250)
        self.assertEqual(50.0, history.completion_percentage())

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=375)
        self.assertEqual(75.0, history.completion_percentage())

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=500)
        self.assertEqual(100.0, history.completion_percentage())

    def test_considered_fully_played_user_value_seventy_five_percent(self):
        video = models.Video.objects.create(duration=500)
        user = UserModel.objects.create(username='test', vidar_playback_completion_percentage="0.75")

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=250)
        self.assertEqual(50.0, history.completion_percentage())
        self.assertFalse(history.considered_fully_played())

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=375)
        self.assertEqual(75.0, history.completion_percentage())
        self.assertTrue(history.considered_fully_played())

    def test_considered_fully_played_user_value_ninty_five_percent(self):
        video = models.Video.objects.create(duration=100)
        user = UserModel.objects.create(username='test', vidar_playback_completion_percentage="0.95")

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=75)
        self.assertEqual(75.0, history.completion_percentage())
        self.assertFalse(history.considered_fully_played())

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=89)
        self.assertEqual(89.0, history.completion_percentage())
        self.assertFalse(history.considered_fully_played())

        history = models.UserPlaybackHistory.objects.create(user=user, video=video, seconds=95)
        self.assertEqual(95.0, history.completion_percentage())
        self.assertTrue(history.considered_fully_played())


class PlaylistTests(TestCase):

    def test_save_without_provider_id_clears_crontab(self):
        playlist = models.Playlist.objects.create(crontab='* * * * *')
        playlist.save()
        self.assertEqual('', playlist.crontab, "crontab cannot scan without a link to a live provider playlist")

    def test_save_with_provider_id_clears_indexing_values(self):
        channel = models.Channel.objects.create(name='test channel')
        playlist = models.Playlist.objects.create(
            provider_object_id='test',
            crontab='* * * * *',
            video_indexing_add_by_title='kitchen'
        )
        self.assertEqual(0, playlist.video_indexing_add_by_title_limit_to_channels.count())
        playlist.video_indexing_add_by_title_limit_to_channels.add(channel)
        self.assertEqual(1, playlist.video_indexing_add_by_title_limit_to_channels.count())
        playlist.save()
        self.assertEqual(0, playlist.video_indexing_add_by_title_limit_to_channels.count())
        self.assertEqual('* * * * *', playlist.crontab)
        self.assertEqual(
            '',
            playlist.video_indexing_add_by_title,
            "playlist with provider cannot manually add videos as they would be cleared out on next scan",
        )

    def test_save_when_hidden_disables_cron_and_indexing(self):
        playlist = models.Playlist.objects.create(
            crontab='* * * * *',
            video_indexing_add_by_title='kitchen',
            disable_when_string_found_in_video_title=' finale',
            hidden=True,
        )
        playlist.save()
        self.assertEqual('', playlist.crontab, "hidden playlists cannot be scanned")
        self.assertEqual('', playlist.video_indexing_add_by_title, "hidden playlists cannot add based on indexing")
        self.assertEqual('', playlist.disable_when_string_found_in_video_title, "hidden playlists cannot be disabled")

    def test_get_user_watch_later(self):
        user = UserModel.objects.create(username='test')
        self.assertEqual(0, models.Playlist.objects.count())

        wl = models.Playlist.get_user_watch_later(user=user)
        self.assertEqual(1, models.Playlist.objects.count())

        self.assertEqual(user, wl.user)
        self.assertEqual('', wl.provider_object_id)
        self.assertEqual("Watch Later", wl.title)

    def test_next_runtime(self):
        playlist = models.Playlist.objects.create(
            provider_object_id='test',
            crontab='10 16 * * *',
        )
        ts = timezone.now().replace(hour=14, minute=59, second=0, microsecond=0)
        with patch.object(timezone, 'localtime', return_value=ts):
            output = playlist.next_runtime

        expected_ts = ts.replace(hour=16, minute=10)

        self.assertEqual(expected_ts, output)

    def test_next_runtime_without_cron_returns_none(self):
        playlist = models.Playlist.objects.create(provider_object_id='test')
        self.assertIsNone(playlist.next_runtime)

    def test_apply_display_ordering_to_queryset(self):
        playlist = models.Playlist.objects.create(
            provider_object_id='test',
            videos_display_ordering=models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            videos_playback_ordering=models.Playlist.PlaylistVideoOrderingChoices.DEFAULT_REVERSED,
        )
        qs = playlist.playlistitem_set.all()
        output = playlist.apply_display_ordering_to_queryset(qs)
        self.assertTrue(output.ordered)
        self.assertEqual(1, len(output.query.order_by))
        self.assertIn('display_order', output.query.order_by)

        playlist.videos_display_ordering = models.Playlist.PlaylistVideoOrderingChoices.DEFAULT_REVERSED
        output = playlist.apply_display_ordering_to_queryset(qs)
        self.assertTrue(output.ordered)
        self.assertEqual(1, len(output.query.order_by))
        self.assertIn('-display_order', output.query.order_by)

        playlist.videos_display_ordering = models.Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_ASC
        output = playlist.apply_display_ordering_to_queryset(qs)
        self.assertTrue(output.ordered)
        self.assertEqual(1, len(output.query.order_by))
        self.assertIn('video__upload_date', output.query.order_by)

        playlist.videos_display_ordering = models.Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_DESC
        output = playlist.apply_display_ordering_to_queryset(qs)
        self.assertTrue(output.ordered)
        self.assertEqual(1, len(output.query.order_by))
        self.assertIn('-video__upload_date', output.query.order_by)

    def test_apply_playback_ordering_to_queryset(self):
        playlist = models.Playlist.objects.create(
            provider_object_id='test',
            videos_display_ordering=models.Playlist.PlaylistVideoOrderingChoices.DEFAULT_REVERSED,
            videos_playback_ordering=models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
        )
        qs = playlist.playlistitem_set.all()

        playlist.videos_playback_ordering = models.Playlist.PlaylistVideoOrderingChoices.DEFAULT_REVERSED
        output = playlist.apply_playback_ordering_to_queryset(qs)
        self.assertTrue(output.ordered)
        self.assertEqual(1, len(output.query.order_by))
        self.assertIn('-pk', output.query.order_by)

        playlist.videos_playback_ordering = models.Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_ASC
        output = playlist.apply_playback_ordering_to_queryset(qs)
        self.assertTrue(output.ordered)
        self.assertEqual(1, len(output.query.order_by))
        self.assertIn('video__upload_date', output.query.order_by)

        playlist.videos_playback_ordering = models.Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_DESC
        output = playlist.apply_playback_ordering_to_queryset(qs)
        self.assertTrue(output.ordered)
        self.assertEqual(1, len(output.query.order_by))
        self.assertIn('-video__upload_date', output.query.order_by)

    def test_calculated_methods(self):
        playlist = models.Playlist.objects.create(provider_object_id='test')
        v1 = models.Video.objects.create(file='test.mp4', duration=100, file_size=200)
        v2 = models.Video.objects.create(file='test.mp4', duration=100, file_size=200)
        v3 = models.Video.objects.create(file='test.mp4', duration=100, file_size=200)
        v4 = models.Video.objects.create(duration=100, file_size=200)
        v5 = models.Video.objects.create(duration=100, file_size=200)
        playlist.videos.add(v1, v2, v3)

        self.assertEqual(300, playlist.calculated_duration())
        self.assertEqual(600, playlist.calculated_file_size())
        self.assertEqual(datetime.timedelta(seconds=300), playlist.calculated_duration_as_timedelta())

    def test_missing_archived(self):
        playlist = models.Playlist.objects.create(provider_object_id='test')
        v1 = models.Video.objects.create(file='test.mp4')
        v2 = models.Video.objects.create(file='test.mp4')
        v3 = models.Video.objects.create(file='test.mp4')
        v4 = models.Video.objects.create()
        v5 = models.Video.objects.create()
        playlist.videos.add(v1, v2, v3, v4, v5)

        missing = playlist.missing_videos().values_list('video', flat=True)
        archived = playlist.archived_videos().values_list('video', flat=True)

        self.assertIn(v1.pk, archived)
        self.assertIn(v2.pk, archived)
        self.assertIn(v3.pk, archived)
        self.assertNotIn(v4.pk, archived)
        self.assertNotIn(v5.pk, archived)

        self.assertNotIn(v1.pk, missing)
        self.assertNotIn(v2.pk, missing)
        self.assertNotIn(v3.pk, missing)
        self.assertIn(v4.pk, missing)
        self.assertIn(v5.pk, missing)

    def test_latest_video_by_upload_date(self):
        playlist = models.Playlist.objects.create(provider_object_id='test')
        v1 = models.Video.objects.create(upload_date="2025-01-01")
        v2 = models.Video.objects.create(upload_date="2025-01-02")
        v3 = models.Video.objects.create(upload_date="2025-01-03")
        playlist.videos.add(v1, v2, v3)

        self.assertEqual(v3, playlist.latest_video_by_upload_date())

    def test_latest_video_by_upload_date_without_videos_returns_none(self):
        playlist = models.Playlist.objects.create(provider_object_id='test')
        self.assertIsNone(playlist.latest_video_by_upload_date())
