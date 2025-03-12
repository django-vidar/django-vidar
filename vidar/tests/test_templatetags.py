# flake8: noqa

from django.core.paginator import Paginator
from django.core.exceptions import FieldDoesNotExist
from django.contrib.auth import get_user_model
from django.db.utils import NotSupportedError
from django.test import TestCase

from vidar import models, pagination
from vidar.templatetags import video_tools, pagination_helpers, playlist_tools

UserModel = get_user_model()


class TemplateTagsVideoToolsTests(TestCase):

    def test_display_ordering_creates_correctly(self):
        channel = models.Channel.objects.create(name='Test Channel')

        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        video2 = models.Video.objects.create(title='video 2', channel=channel, file='test')
        video3 = models.Video.objects.create(title='video 3', channel=channel, file='test')
        video4 = models.Video.objects.create(title='video 4', channel=channel, file='test')
        video5 = models.Video.objects.create(title='video 5', channel=channel, file='test')

        self.assertEqual(1, video1.sort_ordering)
        self.assertEqual(2, video2.sort_ordering)
        self.assertEqual(3, video3.sort_ordering)
        self.assertEqual(4, video4.sort_ordering)
        self.assertEqual(5, video5.sort_ordering)

    def test_display_ordering_by_playlist_upload_date_asc(self):
        playlist = models.Playlist.objects.create(
            title='Test Playlist',
            videos_playback_ordering=models.Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_ASC,
        )

        video1 = models.Video.objects.create(title='video 1', upload_date='2024-06-01')
        video2 = models.Video.objects.create(title='video 2', upload_date='2024-06-02')
        video3 = models.Video.objects.create(title='video 3', upload_date='2024-06-03')
        video4 = models.Video.objects.create(title='video 4', upload_date='2024-06-04')
        video5 = models.Video.objects.create(title='video 5', upload_date='2024-06-05')
        video6 = models.Video.objects.create(title='video 6', upload_date='2024-06-06')
        video7 = models.Video.objects.create(title='video 7', upload_date='2024-06-07')

        playlist.videos.add(video3, video4, video5)

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video3))
        self.assertEqual(video4, video_tools.next_by_playlist(playlist, video3))

        self.assertEqual(video3, video_tools.previous_by_playlist(playlist, video4))
        self.assertEqual(video5, video_tools.next_by_playlist(playlist, video4))

        self.assertEqual(video4, video_tools.previous_by_playlist(playlist, video5))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video5))

    def test_display_ordering_by_playlist_upload_date_desc(self):
        playlist = models.Playlist.objects.create(
            title='Test Playlist',
            videos_playback_ordering=models.Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_DESC,
        )

        video1 = models.Video.objects.create(title='video 1', upload_date='2024-06-01')
        video2 = models.Video.objects.create(title='video 2', upload_date='2024-06-02')
        video3 = models.Video.objects.create(title='video 3', upload_date='2024-06-03')
        video4 = models.Video.objects.create(title='video 4', upload_date='2024-06-04')
        video5 = models.Video.objects.create(title='video 5', upload_date='2024-06-05')
        video6 = models.Video.objects.create(title='video 6', upload_date='2024-06-06')
        video7 = models.Video.objects.create(title='video 7', upload_date='2024-06-07')

        playlist.videos.add(video3, video4, video5)

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video5))
        self.assertEqual(video4, video_tools.next_by_playlist(playlist, video5))

        self.assertEqual(video5, video_tools.previous_by_playlist(playlist, video4))
        self.assertEqual(video3, video_tools.next_by_playlist(playlist, video4))

        self.assertEqual(video4, video_tools.previous_by_playlist(playlist, video3))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video3))

    def test_display_ordering_by_playlist_returns_none_without_audio_on_audio_playlist(self):
        playlist = models.Playlist.objects.create(title='Test Playlist')
        video3 = models.Video.objects.create(title='video 3', upload_date='2024-06-03')

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video3))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video3))

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video3, view="audio"))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video3, view="audio"))

    def test_display_ordering_by_playlist_with_audio_on_audio_playlist(self):
        playlist = models.Playlist.objects.create(title='Test Playlist')

        video1 = models.Video.objects.create(title='video 1', upload_date='2024-06-01')
        video2 = models.Video.objects.create(title='video 2', upload_date='2024-06-02', audio='test/test.mp3')
        video3 = models.Video.objects.create(title='video 3', upload_date='2024-06-03')
        video4 = models.Video.objects.create(title='video 4', upload_date='2024-06-04')
        video5 = models.Video.objects.create(title='video 5', upload_date='2024-06-05', audio='test/test.mp3')
        video6 = models.Video.objects.create(title='video 6', upload_date='2024-06-06', audio='test/test.mp3')
        video7 = models.Video.objects.create(title='video 7', upload_date='2024-06-07')

        playlist.videos.add(video1)
        playlist.videos.add(video2)
        playlist.videos.add(video3)
        playlist.videos.add(video4)
        playlist.videos.add(video5)
        playlist.videos.add(video6)
        playlist.videos.add(video7)

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video1, view="audio"))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video1, view="audio"))

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video3, view="audio"))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video3, view="audio"))

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video4, view="audio"))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video4, view="audio"))

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video7, view="audio"))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video7, view="audio"))

        self.assertIsNone(video_tools.previous_by_playlist(playlist, video2, view="audio"))
        self.assertEqual(video5, video_tools.next_by_playlist(playlist, video2, view="audio"))

        self.assertEqual(video2, video_tools.previous_by_playlist(playlist, video5, view="audio"))
        self.assertEqual(video6, video_tools.next_by_playlist(playlist, video5, view="audio"))

        self.assertEqual(video5, video_tools.previous_by_playlist(playlist, video6, view="audio"))
        self.assertIsNone(video_tools.next_by_playlist(playlist, video6, view="audio"))

    def test_get_playlist_position(self):
        playlist = models.Playlist.objects.create(title='Test Playlist')

        video1 = models.Video.objects.create(title='video 1')
        video2 = models.Video.objects.create(title='video 2')
        video3 = models.Video.objects.create(title='video 3')
        video4 = models.Video.objects.create(title='video 4')
        video5 = models.Video.objects.create(title='video 5')

        playlist.videos.add(video1)
        playlist.videos.add(video2)
        playlist.videos.add(video3)
        playlist.videos.add(video4)

        self.assertEqual(1, video_tools.get_playlist_position(video=video1, playlist=playlist))
        self.assertEqual(2, video_tools.get_playlist_position(video=video2, playlist=playlist))
        self.assertEqual(3, video_tools.get_playlist_position(video=video3, playlist=playlist))
        self.assertEqual(4, video_tools.get_playlist_position(video=video4, playlist=playlist))
        self.assertIsNone(video_tools.get_playlist_position(video=video5, playlist=playlist))

    def test_next_and_previous_by_channel(self):
        channel = models.Channel.objects.create(name='Test Channel')

        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        video2 = models.Video.objects.create(title='video 2', channel=channel, file='test')
        video3 = models.Video.objects.create(title='video 3', channel=channel, file='test')
        video4 = models.Video.objects.create(title='video 4', channel=channel, file='test')
        video5 = models.Video.objects.create(title='video 5', channel=channel, file='test')
        video6 = models.Video.objects.create(title='video 6', file='test')

        self.assertIsNone(video_tools.next_by_channel(video1))
        self.assertEqual(video2, video_tools.previous_by_channel(video1))

        self.assertEqual(video1, video_tools.next_by_channel(video2))
        self.assertEqual(video3, video_tools.previous_by_channel(video2))

        self.assertEqual(video2, video_tools.next_by_channel(video3))
        self.assertEqual(video4, video_tools.previous_by_channel(video3))

        self.assertEqual(video3, video_tools.next_by_channel(video4))
        self.assertEqual(video5, video_tools.previous_by_channel(video4))

        self.assertIsNone(video_tools.next_by_channel(video6))
        self.assertIsNone(video_tools.previous_by_channel(video6))

    def test_display_ordering_by_upload_date(self):
        video1 = models.Video.objects.create(title='video 1', upload_date='2024-06-01')
        video2 = models.Video.objects.create(title='video 2', upload_date='2024-06-02', file='test.mp4')
        video3 = models.Video.objects.create(title='video 3', upload_date='2024-06-03', file='test.mp4')
        video4 = models.Video.objects.create(title='video 4', upload_date='2024-06-04', file='test.mp4')
        video5 = models.Video.objects.create(title='video 5', upload_date='2024-06-05', file='test.mp4')
        video6 = models.Video.objects.create(title='video 6', upload_date='2024-06-06', file='test.mp4')
        video7 = models.Video.objects.create(title='video 7', upload_date='2024-06-07', file='test.mp4')

        self.assertIsNone(video_tools.previous_by_upload_date(video7))
        self.assertEqual(video6, video_tools.next_by_upload_date(video7))

        self.assertEqual(video7, video_tools.previous_by_upload_date(video6))
        self.assertEqual(video5, video_tools.next_by_upload_date(video6))

        self.assertEqual(video6, video_tools.previous_by_upload_date(video5))
        self.assertEqual(video4, video_tools.next_by_upload_date(video5))

        self.assertEqual(video5, video_tools.previous_by_upload_date(video4))
        self.assertEqual(video3, video_tools.next_by_upload_date(video4))

        self.assertEqual(video4, video_tools.previous_by_upload_date(video3))
        self.assertEqual(video2, video_tools.next_by_upload_date(video3))

        self.assertEqual(video3, video_tools.previous_by_upload_date(video2))
        self.assertIsNone(video_tools.next_by_upload_date(video2))

    def test_display_ordering_by_upload_date_with_audio_true(self):
        video1 = models.Video.objects.create(title='video 1', upload_date='2024-06-01', file='test.mp4')
        video2 = models.Video.objects.create(title='video 2', upload_date='2024-06-02', file='test.mp4', audio='test/test.mp3')
        video3 = models.Video.objects.create(title='video 3', upload_date='2024-06-03', file='test.mp4')
        video4 = models.Video.objects.create(title='video 4', upload_date='2024-06-04', file='test.mp4')
        video5 = models.Video.objects.create(title='video 5', upload_date='2024-06-05', file='test.mp4', audio='test/test.mp3')
        video6 = models.Video.objects.create(title='video 6', upload_date='2024-06-06', file='test.mp4', audio='test/test.mp3')
        video7 = models.Video.objects.create(title='video 7', upload_date='2024-06-07', file='test.mp4')

        self.assertIsNone(video_tools.previous_by_upload_date(video7, view="audio"))
        self.assertEqual(video6, video_tools.next_by_upload_date(video7, view="audio"))

        self.assertIsNone(video_tools.previous_by_upload_date(video6, view="audio"))
        self.assertEqual(video5, video_tools.next_by_upload_date(video6, view="audio"))

        self.assertEqual(video6, video_tools.previous_by_upload_date(video5, view="audio"))
        self.assertEqual(video2, video_tools.next_by_upload_date(video5, view="audio"))

        self.assertEqual(video5, video_tools.previous_by_upload_date(video2, view="audio"))
        self.assertIsNone(video_tools.next_by_upload_date(video2, view="audio"))

        self.assertIsNone(video_tools.next_by_upload_date(video1, view="audio"))
        self.assertEqual(video2, video_tools.previous_by_upload_date(video1, view="audio"))

    def test_display_ordering_by_date_downloaded(self):
        video1 = models.Video.objects.create(title='video 1', date_downloaded='2024-06-01')
        video2 = models.Video.objects.create(title='video 2', date_downloaded='2024-06-02', file='test.mp4')
        video3 = models.Video.objects.create(title='video 3', date_downloaded='2024-06-03', file='test.mp4')
        video4 = models.Video.objects.create(title='video 4', date_downloaded='2024-06-04', file='test.mp4')
        video6 = models.Video.objects.create(title='video 6', date_downloaded='2024-06-06', file='test.mp4')
        video7 = models.Video.objects.create(title='video 7', date_downloaded='2024-06-07', file='test.mp4')
        video5 = models.Video.objects.create(title='video 5', date_downloaded='2024-06-08', file='test.mp4')

        self.assertIsNone(video_tools.previous_by_date_downloaded(video5))
        self.assertEqual(video7, video_tools.next_by_date_downloaded(video5))

        self.assertEqual(video5, video_tools.previous_by_date_downloaded(video7))
        self.assertEqual(video6, video_tools.next_by_date_downloaded(video7))

        self.assertEqual(video7, video_tools.previous_by_date_downloaded(video6))
        self.assertEqual(video4, video_tools.next_by_date_downloaded(video6))

        self.assertEqual(video6, video_tools.previous_by_date_downloaded(video4))
        self.assertEqual(video3, video_tools.next_by_date_downloaded(video4))

        self.assertEqual(video4, video_tools.previous_by_date_downloaded(video3))
        self.assertEqual(video2, video_tools.next_by_date_downloaded(video3))

        self.assertEqual(video3, video_tools.previous_by_date_downloaded(video2))
        self.assertIsNone(video_tools.next_by_date_downloaded(video2))

    def test_display_ordering_by_date_downloaded_with_audio_true(self):
        video1 = models.Video.objects.create(title='video 1', date_downloaded='2024-06-01', file='test.mp4')
        video2 = models.Video.objects.create(title='video 2', date_downloaded='2024-06-02', file='test.mp4', audio='test/test.mp3')
        video3 = models.Video.objects.create(title='video 3', date_downloaded='2024-06-03', file='test.mp4')
        video4 = models.Video.objects.create(title='video 4', date_downloaded='2024-06-04', file='test.mp4')
        video6 = models.Video.objects.create(title='video 6', date_downloaded='2024-06-06', file='test.mp4', audio='test/test.mp3')
        video7 = models.Video.objects.create(title='video 7', date_downloaded='2024-06-07', file='test.mp4')
        video5 = models.Video.objects.create(title='video 5', date_downloaded='2024-06-08', file='test.mp4', audio='test/test.mp3')

        self.assertIsNone(video_tools.previous_by_date_downloaded(video5, view="audio"))
        self.assertEqual(video6, video_tools.next_by_date_downloaded(video5, view="audio"))

        self.assertEqual(video5, video_tools.previous_by_date_downloaded(video6, view="audio"))
        self.assertEqual(video2, video_tools.next_by_date_downloaded(video6, view="audio"))

        self.assertEqual(video6, video_tools.previous_by_date_downloaded(video2, view="audio"))
        self.assertIsNone(video_tools.next_by_date_downloaded(video2, view="audio"))

        self.assertIsNone(video_tools.next_by_date_downloaded(video1, view="audio"))
        self.assertEqual(video2, video_tools.previous_by_date_downloaded(video1, view="audio"))

    def test_display_ordering_by_starred(self):
        video1 = models.Video.objects.create(title='video 1', starred='2024-06-01')
        video2 = models.Video.objects.create(title='video 2', starred='2024-06-02', file='test.mp4')
        video3 = models.Video.objects.create(title='video 3', starred='2024-06-03', file='test.mp4')
        video4 = models.Video.objects.create(title='video 4', starred='2024-06-04', file='test.mp4')
        video6 = models.Video.objects.create(title='video 6', starred='2024-06-06', file='test.mp4')
        video7 = models.Video.objects.create(title='video 7', starred='2024-06-07', file='test.mp4')
        video5 = models.Video.objects.create(title='video 5', starred='2024-06-08', file='test.mp4')

        self.assertIsNone(video_tools.previous_by_starred(video5))
        self.assertEqual(video7, video_tools.next_by_starred(video5))

        self.assertEqual(video5, video_tools.previous_by_starred(video7))
        self.assertEqual(video6, video_tools.next_by_starred(video7))

        self.assertEqual(video7, video_tools.previous_by_starred(video6))
        self.assertEqual(video4, video_tools.next_by_starred(video6))

        self.assertEqual(video6, video_tools.previous_by_starred(video4))
        self.assertEqual(video3, video_tools.next_by_starred(video4))

        self.assertEqual(video4, video_tools.previous_by_starred(video3))
        self.assertEqual(video2, video_tools.next_by_starred(video3))

        self.assertEqual(video3, video_tools.previous_by_starred(video2))
        self.assertIsNone(video_tools.next_by_starred(video2))

    def test_display_ordering_by_starred_with_audio_true(self):
        video1 = models.Video.objects.create(title='video 1', starred='2024-06-01', file='test.mp4')
        video2 = models.Video.objects.create(title='video 2', starred='2024-06-02', file='test.mp4', audio='test/test.mp3')
        video3 = models.Video.objects.create(title='video 3', starred='2024-06-03', file='test.mp4')
        video4 = models.Video.objects.create(title='video 4', starred='2024-06-04', file='test.mp4')
        video6 = models.Video.objects.create(title='video 6', starred='2024-06-06', file='test.mp4', audio='test/test.mp3')
        video7 = models.Video.objects.create(title='video 7', starred='2024-06-07', file='test.mp4')
        video5 = models.Video.objects.create(title='video 5', starred='2024-06-08', file='test.mp4', audio='test/test.mp3')

        self.assertIsNone(video_tools.previous_by_starred(video5, view="audio"))
        self.assertEqual(video6, video_tools.next_by_starred(video5, view="audio"))

        self.assertEqual(video5, video_tools.previous_by_starred(video6, view="audio"))
        self.assertEqual(video2, video_tools.next_by_starred(video6, view="audio"))

        self.assertEqual(video6, video_tools.previous_by_starred(video2, view="audio"))
        self.assertIsNone(video_tools.next_by_starred(video2, view="audio"))

        self.assertIsNone(video_tools.next_by_starred(video1, view="audio"))
        self.assertEqual(video2, video_tools.previous_by_starred(video1, view="audio"))

    def test_get_playback_speed_default(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        user = UserModel.objects.create(username='test')

        output = video_tools.get_playback_speed(user=user, video=video1)
        self.assertEqual(1.0, output, "speed should be from user")

    def test_get_lowest_playback_speed_from_channel(self):
        class Req:
            user = UserModel.objects.create(username='test')
            GET = {}

        context = {"request": Req()}
        channel = models.Channel.objects.create(name='Test Channel', playback_speed='1.25')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        output = video_tools.get_lowest_playback_speed(context=context, video=video1)
        self.assertEqual(1.25, output)

    def test_get_lowest_playback_speed_from_playlist(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        playlist = models.Playlist.objects.create(title='Test Playlist', playback_speed='1.25')
        playlist.videos.add(video1)

        class Req:
            user = UserModel.objects.create(username='test')

        context = {"request": Req()}

        output = video_tools.get_lowest_playback_speed(context=context, video=video1, playlist=playlist)
        self.assertEqual(1.25, output)

    def test_get_playback_volume_default(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        playlist = models.Playlist.objects.create(title='Test Playlist')
        playlist.videos.add(video1)

        class Req:
            user = UserModel.objects.create(username='test')

        context = {"request": Req()}

        output = video_tools.get_playback_volume(context=context, video=video1, playlist=playlist)
        self.assertEqual(1.0, output, "Volume should be from default 1.0")

    def test_convert_seconds_to_hh_mm_ss(self):
        self.assertEqual('', video_tools.convert_seconds_to_hh_mm_ss(None))
        self.assertEqual('0s', video_tools.convert_seconds_to_hh_mm_ss(0))
        self.assertEqual('2s', video_tools.convert_seconds_to_hh_mm_ss(2))
        self.assertEqual('60s', video_tools.convert_seconds_to_hh_mm_ss(60))
        self.assertEqual('01:01', video_tools.convert_seconds_to_hh_mm_ss(61))
        self.assertEqual('05:00', video_tools.convert_seconds_to_hh_mm_ss(300))
        self.assertEqual('1:00:00', video_tools.convert_seconds_to_hh_mm_ss(60*60))
        self.assertEqual('336:00:00', video_tools.convert_seconds_to_hh_mm_ss(60*60*24*14))

    def test_get_lowest_playback_speed_basic(self):
        class Req:
            user = UserModel.objects.create(username='test')
            GET = {}

        context = {"request": Req()}
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        output = video_tools.get_lowest_playback_speed(context=context, video=video1)
        self.assertEqual(1.0, output)

    def test_get_lowest_playback_volume_basic(self):
        class Req:
            user = UserModel.objects.create(username='test')
            GET = {}

        context = {"request": Req()}
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        output = video_tools.get_lowest_playback_volume(context=context, video=video1)
        self.assertEqual(1.0, output)

    def test_get_lowest_playback_volume_from_channel(self):
        class Req:
            user = UserModel.objects.create(username='test')
            GET = {}

        context = {"request": Req()}
        channel = models.Channel.objects.create(name='Test Channel', playback_volume='0.25')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        output = video_tools.get_lowest_playback_volume(context=context, video=video1)
        self.assertEqual(0.25, output)

    def test_get_lowest_playback_volume_from_playlist(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        playlist = models.Playlist.objects.create(title='Test Playlist', playback_volume='0.25')
        playlist.videos.add(video1)

        class Req:
            user = UserModel.objects.create(username='test')

        context = {"request": Req()}

        output = video_tools.get_lowest_playback_volume(context=context, video=video1, playlist=playlist)
        self.assertEqual(0.25, output)

    def test_get_playback_speed_audio_view_default(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        user = UserModel.objects.create(username='test')

        output = video_tools.get_playback_speed(user=user, video=video1, audio=True)
        self.assertEqual(1.0, output, "speed should be from user")

    def test_user_watched_video_unauthenticated(self):
        video1 = models.Video.objects.create(title='video 1', duration=100)

        class UnauthedUser:
            is_authenticated = False

        class Req:
            user = UnauthedUser()

        context = {"request": Req()}

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertIsNone(output, "User is not authenticated, func should return None")

    def test_description_with_linked_timestamps(self):
        description = """This is my video

        1:05 is section 1
        4:50 is section 2
        1:45:50 is final area
        This line contains a semi colon : that should not be linked"""

        output = video_tools.description_with_linked_timestamps(description)

        expected = """This is my video

        <a href="javascript:;" onclick="setVideoTime(65)">1:05</a> is section 1
        <a href="javascript:;" onclick="setVideoTime(290)">4:50</a> is section 2
        <a href="javascript:;" onclick="setVideoTime(6350)">1:45:50</a> is final area
        This line contains a semi colon : that should not be linked"""

        self.assertEqual(expected, output)

    def test_description_with_linked_timestamps_with_bad_hour(self):
        description = """This is my video

        1:05 is section 1
        4:50 is section 2
        h:45:50 is final area
        This line contains a semi colon : that should not be linked"""

        output = video_tools.description_with_linked_timestamps(description)

        expected = """This is my video

        <a href="javascript:;" onclick="setVideoTime(65)">1:05</a> is section 1
        <a href="javascript:;" onclick="setVideoTime(290)">4:50</a> is section 2
        h:45:50 is final area
        This line contains a semi colon : that should not be linked"""

        self.assertEqual(expected, output)

    def test_is_on_watch_later(self):
        user = UserModel.objects.create(username='test')
        playlist = models.Playlist.get_user_watch_later(user=user)

        v = models.Video.objects.create(title=f"Video 1")

        self.assertFalse(video_tools.is_on_watch_later(video=v, user=user))

        playlist.videos.add(v)

        self.assertTrue(video_tools.is_on_watch_later(video=v, user=user))


class TemplateTagsVideoToolsWithCustomUserFieldsTests(TestCase):

    def setUp(self) -> None:
        # This only works for now as the tests within the class need access to this field.
        try:
            UserModel._meta.get_field('vidar_playback_speed')
        except FieldDoesNotExist:
            self.skipTest('User model has no vidar_playback_speed')

    def test_get_playback_volume_from_video(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test', playback_volume='1.5')

        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_volume='0.25')

        context = {"request": Req()}

        output = video_tools.get_playback_volume(context=context, video=video1)
        self.assertEqual(1.5, output, "Volume should be from video")

    def test_get_playback_volume_from_playlist(self):
        channel = models.Channel.objects.create(name='Test Channel', playback_volume='1.0')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        playlist = models.Playlist.objects.create(title='Test Playlist', playback_volume='0.5')
        playlist.videos.add(video1)

        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_volume='0.25')

        context = {"request": Req()}

        output = video_tools.get_playback_volume(context=context, video=video1, playlist=playlist)
        self.assertEqual(0.5, output, "Volume should be from playlist")

    def test_get_playback_volume_from_channel(self):
        channel = models.Channel.objects.create(name='Test Channel', playback_volume='1.0')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_volume='0.25')

        context = {"request": Req()}

        output = video_tools.get_playback_volume(context=context, video=video1)
        self.assertEqual(1.0, output, "Volume should be from channel")

    def test_get_playback_speed_from_playlist(self):
        channel = models.Channel.objects.create(name='Test Channel', playback_speed='1.0')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        user = UserModel.objects.create(username='test', vidar_playback_speed='0.25')

        playlist = models.Playlist.objects.create(title='Test Playlist', playback_speed='0.5')
        playlist.videos.add(video1)

        output = video_tools.get_playback_speed(user=user, video=video1, playlist=playlist)
        self.assertEqual(0.5, output, "speed should be from playlist")

    def test_get_playback_speed_from_channel(self):
        channel = models.Channel.objects.create(name='Test Channel', playback_speed='1.0')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        user = UserModel.objects.create(username='test', vidar_playback_speed='0.25')

        output = video_tools.get_playback_speed(user=user, video=video1)
        self.assertEqual(1.0, output, "speed should be from channel")

    def test_get_playback_speed_from_video(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test', playback_speed='1.5')
        user = UserModel.objects.create(username='test', vidar_playback_speed='0.25')

        output = video_tools.get_playback_speed(user=user, video=video1)
        self.assertEqual(1.5, output, "speed should be from video")

    def test_get_lowest_playback_speed_from_video(self):
        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_speed='1.25')
            GET = {}

        context = {"request": Req()}
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test', playback_speed='0.25')

        output = video_tools.get_lowest_playback_speed(context=context, video=video1)
        self.assertEqual(0.25, output)

    def test_get_lowest_playback_speed_from_user(self):
        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_speed='1.25')
            GET = {}

        context = {"request": Req()}
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        output = video_tools.get_lowest_playback_speed(context=context, video=video1)
        self.assertEqual(1.25, output)

    def test_get_lowest_playback_speed_as_lowest(self):
        channel = models.Channel.objects.create(name='Test Channel', playback_speed='1.5')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        playlist = models.Playlist.objects.create(title='Test Playlist', playback_speed='1.0')
        playlist.videos.add(video1)

        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_speed='1.25')

        context = {"request": Req()}

        output = video_tools.get_lowest_playback_speed(context=context, video=video1, playlist=playlist)
        self.assertEqual(1.0, output)

    def test_get_lowest_playback_volume_from_user(self):
        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_volume='1.25')
            GET = {}

        context = {"request": Req()}
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        output = video_tools.get_lowest_playback_volume(context=context, video=video1)
        self.assertEqual(1.25, output)

    def test_get_lowest_playback_volume_from_video(self):
        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_volume='1.25')
            GET = {}

        context = {"request": Req()}
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test', playback_volume='0.25')

        output = video_tools.get_lowest_playback_volume(context=context, video=video1)
        self.assertEqual(0.25, output)

    def test_get_lowest_playback_volume_as_lowest(self):
        channel = models.Channel.objects.create(name='Test Channel', playback_volume='1.0')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        playlist = models.Playlist.objects.create(title='Test Playlist', playback_volume='0.5')
        playlist.videos.add(video1)

        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_volume='0.25')

        context = {"request": Req()}

        output = video_tools.get_lowest_playback_volume(context=context, video=video1, playlist=playlist)
        self.assertEqual(0.25, output)

    def test_get_playback_volume_from_user(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')

        class Req:
            user = UserModel.objects.create(username='test', vidar_playback_volume='0.25')

        context = {"request": Req()}

        output = video_tools.get_playback_volume(context=context, video=video1)
        self.assertEqual(0.25, output, "Volume should be from user")

    def test_get_playback_speed_from_user(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        user = UserModel.objects.create(username='test', vidar_playback_speed='0.25')

        output = video_tools.get_playback_speed(user=user, video=video1)
        self.assertEqual(0.25, output, "speed should be from user")

    def test_get_playback_speed_audio_view_from_playlist(self):
        channel = models.Channel.objects.create(name='Test Channel', playback_speed='1.0')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        user = UserModel.objects.create(username='test', vidar_playback_speed_audio='0.25')

        playlist = models.Playlist.objects.create(title='Test Playlist', playback_speed='0.5')
        playlist.videos.add(video1)

        output = video_tools.get_playback_speed(user=user, video=video1, playlist=playlist, audio=True)
        self.assertEqual(0.5, output, "speed should be from playlist")

    def test_get_playback_speed_audio_view_from_channel(self):
        channel = models.Channel.objects.create(name='Test Channel', playback_speed='1.0')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        user = UserModel.objects.create(username='test', vidar_playback_speed_audio='0.25')

        output = video_tools.get_playback_speed(user=user, video=video1, audio=True)
        self.assertEqual(1.0, output, "speed should be from channel")

    def test_get_playback_speed_audio_view_from_user(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test')
        user = UserModel.objects.create(username='test', vidar_playback_speed_audio='0.25')

        output = video_tools.get_playback_speed(user=user, video=video1, audio=True)
        self.assertEqual(0.25, output, "speed should be from user")

    def test_get_playback_speed_audio_view_from_video(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video1 = models.Video.objects.create(title='video 1', channel=channel, file='test', playback_speed='1.5')
        user = UserModel.objects.create(username='test', vidar_playback_speed_audio='0.25')

        output = video_tools.get_playback_speed(user=user, video=video1, audio=True)
        self.assertEqual(1.5, output, "speed should be from video")

    def test_user_watched_video(self):
        video1 = models.Video.objects.create(title='video 1', duration=100)

        class Req:
            user = UserModel.objects.create(username='test')

        context = {"request": Req()}

        models.UserPlaybackHistory.objects.create(
            video=video1,
            user=Req.user,
            seconds=50
        )

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertFalse(output, "User didn't fully watch video at 50%")

        models.UserPlaybackHistory.objects.create(
            video=video1,
            user=Req.user,
            seconds=74
        )

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertFalse(output, "User didn't fully watch video at 74%")

        models.UserPlaybackHistory.objects.create(
            video=video1,
            user=Req.user,
            seconds=75
        )

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertTrue(output, "User fully watch video at 75+%")

        models.UserPlaybackHistory.objects.create(
            video=video1,
            user=Req.user,
            seconds=96
        )

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertTrue(output, "User fully watch video at 96%")

    def test_user_watched_video_user_configurable(self):
        video1 = models.Video.objects.create(title='video 1', duration=100)

        class Req:
            user = UserModel.objects.create(
                username='test',
                vidar_playback_completion_percentage='0.95',
            )

        context = {"request": Req()}

        models.UserPlaybackHistory.objects.create(
            video=video1,
            user=Req.user,
            seconds=50
        )

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertFalse(output, "User didn't fully watch video at 50%")

        models.UserPlaybackHistory.objects.create(
            video=video1,
            user=Req.user,
            seconds=75
        )

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertFalse(output, "User didn't fully watch video at 75%")

        models.UserPlaybackHistory.objects.create(
            video=video1,
            user=Req.user,
            seconds=94
        )

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertFalse(output, "User didn't fully watch video at 94%")

        models.UserPlaybackHistory.objects.create(
            video=video1,
            user=Req.user,
            seconds=96
        )

        output = video_tools.user_watched_video(context=context, video=video1)
        self.assertTrue(output, "User fully watch video at 96%")


class PaginationHelperTests(TestCase):
    def setUp(self) -> None:
        for x in range(100):
            models.Video.objects.create(title=x)

    def test_base_pagination_settings(self):

        context_key = 'object_list_key'
        output = pagination.paginator_helper(
            context_key=context_key,
            queryset=models.Video.objects.all().order_by('id'),
            requested_page=1,
            limit=2,
        )

        self.assertIn(context_key, output)
        self.assertEqual(2, output[context_key].count())
        self.assertTrue(output['is_paginated'])
        self.assertEqual('?', output['pagination_base_url'])
        self.assertEqual(1, output['page_obj'].number)

    def test_pagination_with_request_params(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            request_params={'page': 1, 'limit': 2, 'search': 'search text'},
        )

        self.assertEqual('?limit=2&search=search+text&', output['pagination_base_url'])

    def test_pagination_with_params_depreciated(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            request_params={'page': 1, 'limit': 2, 'search': 'search text'},
        )

        self.assertEqual('?limit=2&search=search+text&', output['pagination_base_url'])

    def test_pagination_requested_page_too_high(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            requested_page=100,
        )
        self.assertEqual(7, output['page_obj'].number)

    def test_pagination_requested_page_too_low(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            requested_page=-2,
        )
        self.assertEqual(1, output['page_obj'].number)

    def test_pagination_requested_page_is_invalid(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            requested_page='2nd',
        )
        self.assertEqual(1, output['page_obj'].number)

    def test_pagination_custom_limit_url_param(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            limit=2,
            limit_url_param='limiter',
            request_params={'limiter': 15},
        )
        self.assertEqual(7, output['paginator'].num_pages)

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            limit=2,
            limit_url_param='limiter',
            request_params={'limiter': 30},
        )
        self.assertEqual(4, output['paginator'].num_pages)

    def test_pagination_custom_page_url_param(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            page_url_param='page_id',
            limit=3,
            request_params={'page_id': 15},
        )
        self.assertEqual(15, output['page_obj'].number)

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            page_url_param='page_id',
            limit=2,
            request_params={'page_id': 15},
        )
        self.assertEqual(15, output['page_obj'].number)

    def test_pagination_last_first_true(self):

        output = pagination.paginator_helper(
            context_key='object_list_key', queryset=models.Video.objects.all().order_by('id'), limit=2, last_first=True
        )
        self.assertEqual(50, output['page_obj'].number)

        output = pagination.paginator_helper(
            context_key='object_list_key',
            queryset=models.Video.objects.all().order_by('id'),
            limit=2,
            requested_page=7,
            last_first=True,
        )
        self.assertEqual(7, output['page_obj'].number)

    def test_pagination_with_default_context_pre(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
        )

        self.assertIn('objects', output)
        self.assertIn('paginator', output)
        self.assertIn('page_obj', output)
        self.assertIn('pagination_base_url', output)
        self.assertIn('is_paginated', output)

    def test_pagination_with_custom_context_pre(self):

        output = pagination.paginator_helper(
            context_key='objects',
            queryset=models.Video.objects.all().order_by('id'),
            context_keys_prefix='blahs_',
        )

        self.assertIn('blahs_objects', output)
        self.assertIn('blahs_paginator', output)
        self.assertIn('blahs_page_obj', output)
        self.assertIn('blahs_pagination_base_url', output)
        self.assertIn('blahs_is_paginated', output)


class TemplateTagsProperPaginationTests(TestCase):
    def setUp(self) -> None:
        for x in range(100):
            models.Video.objects.create(title=x)

    def test_default_pagination_settings_with_low_number_of_pages(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 10), current_page=1
        )
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9], output)

    def test_default_pagination_settings_with_high_number_of_pages(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 2), current_page=8
        )
        self.assertEqual([4, 5, 6, 7, 8, 9, 10, 11, 12], output)

    def test_default_pagination_settings_with_large_neighbors(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 2), current_page=15, neighbors=10
        )
        self.assertEqual([5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25], output)

    def test_proper_pagination_settings_with_first(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 2),
            current_page=12,
            include_first=2,
        )
        self.assertEqual([1, 2, 8, 9, 10, 11, 12, 13, 14, 15, 16], output)

    def test_proper_pagination_settings_with_last(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 2),
            current_page=12,
            include_last=2,
        )
        self.assertEqual([8, 9, 10, 11, 12, 13, 14, 15, 16, 49, 50], output)

    def test_proper_pagination_settings_with_first_and_last(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 2),
            current_page=12,
            include_first=2,
            include_last=2,
        )
        self.assertEqual([1, 2, 8, 9, 10, 11, 12, 13, 14, 15, 16, 49, 50], output)

    def test_proper_pagination_settings_with_first_and_last_and_separator(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 2),
            current_page=12,
            include_first=2,
            include_last=2,
            include_separator='...',
        )
        self.assertEqual([1, 2, '...', 8, 9, 10, 11, 12, 13, 14, 15, 16, '...', 49, 50], output)

    def test_proper_pagination_settings_with_first_last_separator_and_small_neighbors(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 2),
            neighbors=2,
            current_page=12,
            include_first=2,
            include_last=2,
            include_separator='...',
        )
        self.assertEqual([1, 2, '...', 10, 11, 12, 13, 14, '...', 49, 50], output)

    def test_proper_pagination_settings_with_first_last_separator_and_large_neighbors(self):
        output = pagination_helpers.proper_pagination(
            paginator=Paginator(models.Video.objects.all().order_by('id'), 2),
            neighbors=10,
            current_page=12,
            include_first=2,
            include_last=2,
            include_separator='...',
        )
        self.assertEqual(
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, '...', 49, 50], output
        )


class TemplateTagsPlaylistToolsWithUserCustomFieldsTests(TestCase):

    def setUp(self) -> None:
        # This only works for now as the tests within the class need access to this field.
        try:
            UserModel._meta.get_field('vidar_playback_completion_percentage')
        except FieldDoesNotExist:
            self.skipTest('User model has no vidar_playback_completion_percentage')

    def test_user_has_not_watched_entire_playlist(self):
        video1 = models.Video.objects.create(title='video 1', duration=100)
        video2 = models.Video.objects.create(title='video 2', duration=100)
        playlist = models.Playlist.objects.create(title='playlist 1')

        playlist.videos.add(video1, video2)

        user = UserModel.objects.create(username='test')

        models.UserPlaybackHistory.objects.create(video=video1, user=user, seconds=96)

        output = playlist_tools.user_played_entire_playlist(playlist=playlist, user=user)
        self.assertFalse(output, "User has not watched the entire playlist yet")

    def test_user_not_watched_entire_playlist(self):
        video1 = models.Video.objects.create(title='video 1', duration=100)
        video2 = models.Video.objects.create(title='video 2', duration=100)
        playlist = models.Playlist.objects.create(title='playlist 1')

        playlist.videos.add(video1, video2)

        user = UserModel.objects.create(username='test')

        models.UserPlaybackHistory.objects.create(video=video1, user=user, seconds=96)
        models.UserPlaybackHistory.objects.create(video=video2, user=user, seconds=96)

        try:
            output = playlist_tools.user_played_entire_playlist(playlist=playlist, user=user, raise_error=True)
            self.assertTrue(output, "User has watched the entire playlist")
        except NotSupportedError:
            self.skipTest('DB does not support distinct on fields.')

    def test_user_not_watched_entire_playlist_without_videos(self):
        playlist = models.Playlist.objects.create(title='playlist 1')

        user = UserModel.objects.create(username='test')

        output = playlist_tools.user_played_entire_playlist(playlist=playlist, user=user)
        self.assertFalse(output, "Playlist has no videos, it should not have been identified as watched")

    def test_multi_user_doesnt_clash(self):
        video1 = models.Video.objects.create(title='video 1', duration=100)
        video2 = models.Video.objects.create(title='video 2', duration=100)
        playlist = models.Playlist.objects.create(title='playlist 1')

        playlist.videos.add(video1, video2)

        user1 = UserModel.objects.create(username='test 1', email='email 1')
        user2 = UserModel.objects.create(username='test 2', email='email 2')

        models.UserPlaybackHistory.objects.create(video=video1, user=user1, seconds=96)
        models.UserPlaybackHistory.objects.create(video=video2, user=user2, seconds=96)

        output = playlist_tools.user_played_entire_playlist(playlist=playlist, user=user1)
        self.assertFalse(output, "User has not watched the entire playlist")

    def test_next_unwatched_video(self):
        video1 = models.Video.objects.create(title='video 1', duration=100, file='tests')
        video2 = models.Video.objects.create(title='video 2', duration=100, file='tests')
        video3 = models.Video.objects.create(title='video 3', duration=100, file='tests')
        playlist = models.Playlist.objects.create(title='playlist 1')

        pi1 = playlist.playlistitem_set.create(video=video1)
        pi2 = playlist.playlistitem_set.create(video=video2)
        pi3 = playlist.playlistitem_set.create(video=video3)

        user = UserModel.objects.create(username='test 1', email='email 1')

        models.UserPlaybackHistory.objects.create(video=video1, user=user, seconds=96)
        models.UserPlaybackHistory.objects.create(video=video2, user=user, seconds=96)

        self.assertEqual(pi3, playlist_tools.get_next_unwatched_video_on_playlist(playlist=playlist, user=user))

    def test_next_unwatched_video_with_partial_watched(self):
        video1 = models.Video.objects.create(title='video 1', duration=100, file='tests')
        video2 = models.Video.objects.create(title='video 2', duration=100, file='tests')
        video3 = models.Video.objects.create(title='video 3', duration=100, file='tests')
        playlist = models.Playlist.objects.create(title='playlist 1')

        pi1 = playlist.playlistitem_set.create(video=video1)
        pi2 = playlist.playlistitem_set.create(video=video2)
        pi3 = playlist.playlistitem_set.create(video=video3)

        user = UserModel.objects.create(username='test 1', email='email 1')

        models.UserPlaybackHistory.objects.create(video=video1, user=user, seconds=96)
        models.UserPlaybackHistory.objects.create(video=video2, user=user, seconds=50)

        self.assertEqual(pi2, playlist_tools.get_next_unwatched_video_on_playlist(playlist=playlist, user=user))

    def test_next_unwatched_video_skips_without_file(self):
        video1 = models.Video.objects.create(title='video 1', duration=100, file='tests')
        video2 = models.Video.objects.create(title='video 2', duration=100, audio='tests')
        video3 = models.Video.objects.create(title='video 3', duration=100, file='tests')
        playlist = models.Playlist.objects.create(title='playlist 1')

        pi1 = playlist.playlistitem_set.create(video=video1)
        pi2 = playlist.playlistitem_set.create(video=video2)
        pi3 = playlist.playlistitem_set.create(video=video3)

        user = UserModel.objects.create(username='test 1', email='email 1')

        models.UserPlaybackHistory.objects.create(video=video1, user=user, seconds=96)

        self.assertEqual(pi3, playlist_tools.get_next_unwatched_video_on_playlist(playlist=playlist, user=user))

    def test_next_unwatched_audio(self):
        video1 = models.Video.objects.create(title='video 1', duration=100, audio='tests')
        video2 = models.Video.objects.create(title='video 2', duration=100, audio='tests')
        video3 = models.Video.objects.create(title='video 3', duration=100, audio='tests')
        playlist = models.Playlist.objects.create(title='playlist 1')

        pi1 = playlist.playlistitem_set.create(video=video1)
        pi2 = playlist.playlistitem_set.create(video=video2)
        pi3 = playlist.playlistitem_set.create(video=video3)

        user = UserModel.objects.create(username='test 1', email='email 1')

        models.UserPlaybackHistory.objects.create(video=video1, user=user, seconds=96)
        models.UserPlaybackHistory.objects.create(video=video2, user=user, seconds=96)

        self.assertEqual(pi3, playlist_tools.get_next_unwatched_audio_on_playlist(playlist=playlist, user=user))

    def test_next_unwatched_audio_with_partial_watched(self):
        video1 = models.Video.objects.create(title='video 1', duration=100, audio='tests')
        video2 = models.Video.objects.create(title='video 2', duration=100, audio='tests')
        video3 = models.Video.objects.create(title='video 3', duration=100, audio='tests')
        playlist = models.Playlist.objects.create(title='playlist 1')

        pi1 = playlist.playlistitem_set.create(video=video1)
        pi2 = playlist.playlistitem_set.create(video=video2)
        pi3 = playlist.playlistitem_set.create(video=video3)

        user = UserModel.objects.create(username='test 1', email='email 1')

        models.UserPlaybackHistory.objects.create(video=video1, user=user, seconds=96)
        models.UserPlaybackHistory.objects.create(video=video2, user=user, seconds=50)

        self.assertEqual(pi2, playlist_tools.get_next_unwatched_audio_on_playlist(playlist=playlist, user=user))

    def test_next_unwatched_audio_skips_without_audio(self):
        video1 = models.Video.objects.create(title='video 1', duration=100, audio='tests')
        video2 = models.Video.objects.create(title='video 2', duration=100, file='tests')
        video3 = models.Video.objects.create(title='video 3', duration=100, audio='tests')
        playlist = models.Playlist.objects.create(title='playlist 1')

        pi1 = playlist.playlistitem_set.create(video=video1)
        pi2 = playlist.playlistitem_set.create(video=video2)
        pi3 = playlist.playlistitem_set.create(video=video3)

        user = UserModel.objects.create(username='test 1', email='email 1')

        models.UserPlaybackHistory.objects.create(video=video1, user=user, seconds=96)

        self.assertEqual(pi3, playlist_tools.get_next_unwatched_audio_on_playlist(playlist=playlist, user=user))


class TemplateTagsPlaylistTools(TestCase):
    def test_link_to_playlist_page(self):
        playlist = models.Playlist.objects.create(title='test')

        videos = []
        for x in range(10):
            v = models.Video.objects.create(title=f"Video {x}")
            videos.append(v)
            playlist.videos.add(v)

        self.assertEqual(1, playlist_tools.link_to_playlist_page(playlist, videos[0], num_per_page=3))
        self.assertEqual(1, playlist_tools.link_to_playlist_page(playlist, videos[1], num_per_page=3))
        self.assertEqual(1, playlist_tools.link_to_playlist_page(playlist, videos[2], num_per_page=3))
        self.assertEqual(2, playlist_tools.link_to_playlist_page(playlist, videos[3], num_per_page=3))
        self.assertEqual(2, playlist_tools.link_to_playlist_page(playlist, videos[4], num_per_page=3))
        self.assertEqual(2, playlist_tools.link_to_playlist_page(playlist, videos[5], num_per_page=3))
        self.assertEqual(3, playlist_tools.link_to_playlist_page(playlist, videos[6], num_per_page=3))
        self.assertEqual(3, playlist_tools.link_to_playlist_page(playlist, videos[7], num_per_page=3))
        self.assertEqual(3, playlist_tools.link_to_playlist_page(playlist, videos[8], num_per_page=3))
        self.assertEqual(4, playlist_tools.link_to_playlist_page(playlist, videos[9], num_per_page=3))

    def test_link_to_playlist_page_none_video_is_not_on_playlist(self):
        playlist = models.Playlist.objects.create(title='test')
        v = models.Video.objects.create(title=f"Video not on playlist")
        self.assertIsNone(playlist_tools.link_to_playlist_page(playlist, v))

    def test_link_to_playlist_page_returns_none_when_less_than_page_size(self):
        playlist = models.Playlist.objects.create(title='test')
        v1 = models.Video.objects.create(title=f"Video 1")
        playlist.videos.add(v1)
        self.assertIsNone(playlist_tools.link_to_playlist_page(playlist, v1))
