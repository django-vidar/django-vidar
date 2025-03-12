# flake8: noqa
import json
import pathlib

from unittest.mock import patch, call

from django.test import SimpleTestCase, TestCase, override_settings
from django.shortcuts import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group
from django.utils import timezone

from example import settings
from vidar import models, forms, renamers, json_encoders, exceptions, app_settings, interactor, utils
from vidar.helpers import channel_helpers, video_helpers

UserModel = get_user_model()


class UnauthenticatedVideoAccessTests(TestCase):

    def setUp(self) -> None:
        self.test_video_1 = models.Video.objects.create(
            provider_object_id='mBuHO8p0wS0',
        )
        self.test_video_2 = models.Video.objects.create(
            provider_object_id='3V6rjyL_63U',
        )
        self.group_anon, _ = Group.objects.get_or_create(name='Anonymous Users')
        perm_view_video = Permission.objects.get(
            codename='view_video',
            content_type__app_label='vidar',
            content_type__model='video',
        )
        perm_add_video = Permission.objects.get(
            codename='add_video',
            content_type__app_label='vidar',
            content_type__model='video',
        )
        perm_access_vidar = Permission.objects.get(
            codename='access_vidar',
            content_type__app_label='vidar',
            content_type__model='rightssupport',
        )
        self.group_anon.permissions.add(perm_access_vidar)
        self.group_anon.permissions.add(perm_view_video)
        self.group_anon.permissions.add(perm_add_video)

    def test_unauth_uses_public_template(self):
        resp = self.client.get(reverse('vidar:index'))
        self.assertTemplateUsed(resp, 'vidar/video_list_public.html')

    def test_unauth_cannot_see_anything(self):
        resp = self.client.get(reverse('vidar:index'))
        self.assertFalse(resp.context['object_list'])

    def test_unauth_can_see_one(self):
        self.client.post(reverse('vidar:video-create'), {'provider_object_id': self.test_video_1.url, 'quality': 720})

        resp = self.client.get(reverse('vidar:index'))
        self.assertIn(self.test_video_1, resp.context['object_list'])
        self.assertNotIn(self.test_video_2, resp.context['object_list'])


class VideoSaveWatchTimeTests(TestCase):

    def setUp(self) -> None:
        self.test_video_1 = models.Video.objects.create(provider_object_id='mBuHO8p0wS0')
        self.user1 = UserModel.objects.create(username='test 1', email='email 1', is_superuser=True)
        self.client.force_login(self.user1)

    def test_save_watch_history(self):
        self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
            'current_time': '5'
        })
        self.assertEqual(1, self.test_video_1.user_playback_history.count())

    def test_save_watch_history_updates_existing(self):
        self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
            'current_time': '5'
        })
        self.assertEqual(1, self.test_video_1.user_playback_history.count())

        self.assertEqual(5, models.UserPlaybackHistory.objects.get().seconds)

        self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
            'current_time': '10'
        })
        self.assertEqual(1, self.test_video_1.user_playback_history.count())
        self.assertEqual(10, models.UserPlaybackHistory.objects.get().seconds)

    def test_save_watch_history_create_second_entry_if_time_is_lesser_than_before(self):
        dt = timezone.now() - timezone.timedelta(hours=2)
        with patch.object(timezone, 'now', return_value=dt):
            self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
                'current_time': '300'
            })
        self.assertEqual(1, self.test_video_1.user_playback_history.count())

        self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
            'current_time': '10'
        })
        self.assertEqual(2, self.test_video_1.user_playback_history.count())

        self.assertEqual(300, models.UserPlaybackHistory.objects.last().seconds)
        self.assertEqual(10, models.UserPlaybackHistory.objects.latest().seconds)

    def test_save_watch_history_does_not_create_entry_jumping_forward_beyond_diff_value(self):

        # Enter a history entry as if it were 2 hours ago.
        with patch.object(timezone, 'now', return_value=timezone.now() - timezone.timedelta(hours=2)):
            self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
                'current_time': '300'
            })
        self.assertEqual(1, self.test_video_1.user_playback_history.count())

        latest = models.UserPlaybackHistory.objects.latest()
        self.assertEqual(300, latest.seconds)

        self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
            'current_time': '43'
        })
        self.assertEqual(2, self.test_video_1.user_playback_history.count(),
                         "Two hours later and greater than 120 seconds behind the last history entry. "
                         "It should have created a second entry.")

        latest = models.UserPlaybackHistory.objects.latest()
        self.assertEqual(43, latest.seconds)

        self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
            'current_time': '500'
        })
        self.assertEqual(2, self.test_video_1.user_playback_history.count(),
                         'Jumping into the future should not create another history entry')
        latest = models.UserPlaybackHistory.objects.latest()
        self.assertEqual(500, latest.seconds)

        self.client.post(reverse('vidar:video-save-user-view-time', args=[self.test_video_1.pk]), {
            'current_time': '120'
        })
        self.assertEqual(2, self.test_video_1.user_playback_history.count(),
                         'Jumping into the past should not create another history entry within the time limit')
        latest = models.UserPlaybackHistory.objects.latest()
        self.assertEqual(120, latest.seconds)


class FormTests(TestCase):
    def test_convert_timeformat_to_seconds(self):
        output = forms.convert_timeformat_to_seconds('00:00:00')
        self.assertEqual(0, output)
        output = forms.convert_timeformat_to_seconds('00:00')
        self.assertEqual(0, output)
        with self.assertRaises(forms.forms.ValidationError):
            forms.convert_timeformat_to_seconds('00')

        output = forms.convert_timeformat_to_seconds('01:00:00')
        self.assertEqual(3600, output)

        output = forms.convert_timeformat_to_seconds('10:00')
        self.assertEqual(600, output)

        output = forms.convert_timeformat_to_seconds('10:06')
        self.assertEqual(606, output)

    def test_highlight_form_accepts_both_point_formats(self):
        form = forms.HighlightForm(data={
            'point': '60',
            'end_point': '65',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(60, form.cleaned_data['point'])
        self.assertEqual(65, form.cleaned_data['end_point'])
        self.assertEqual('test', form.cleaned_data['note'])

        form = forms.HighlightForm(data={
            'point': '15:23',
            'end_point': '18:45',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(923, form.cleaned_data['point'])
        self.assertEqual(1125, form.cleaned_data['end_point'])
        self.assertEqual('test', form.cleaned_data['note'])

    def test_highlight_form_without_end_point(self):
        form = forms.HighlightForm(data={
            'point': '60',
            'end_point': '',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(60, form.cleaned_data['point'])
        self.assertIsNone(form.cleaned_data['end_point'])
        self.assertEqual('test', form.cleaned_data['note'])

        form = forms.HighlightForm(data={
            'point': '15:23',
            'end_point': '18:45',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(923, form.cleaned_data['point'])
        self.assertEqual(1125, form.cleaned_data['end_point'])
        self.assertEqual('test', form.cleaned_data['note'])

    def test_highlight_form_wont_error_with_zero_start_point(self):
        form = forms.HighlightForm(data={
            'point': '0',
            'end_point': '65',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(00, form.cleaned_data['point'])
        self.assertEqual(65, form.cleaned_data['end_point'])
        self.assertEqual('test', form.cleaned_data['note'])

        form = forms.HighlightForm(data={
            'point': '00:00',
            'end_point': '65',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(00, form.cleaned_data['point'])
        self.assertEqual(65, form.cleaned_data['end_point'])
        self.assertEqual('test', form.cleaned_data['note'])

        form = forms.HighlightForm(data={
            'point': '00:00:00',
            'end_point': '65',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(00, form.cleaned_data['point'])
        self.assertEqual(65, form.cleaned_data['end_point'])
        self.assertEqual('test', form.cleaned_data['note'])

    def test_highlight_form_end_after_start_otherwise_error(self):
        form = forms.HighlightForm(data={
            'point': '60',
            'end_point': '15',
            'note': 'test',
        })
        self.assertFalse(form.is_valid())
        self.assertEqual('Start cannot be before End', form.errors['end_point'][0])

    def test_durationskip_form_accepts_both_point_formats(self):
        form = forms.DurationSkipForm(data={
            'start': '60',
            'end': '65',
        }, existing_skips=[])
        self.assertTrue(form.is_valid())
        self.assertEqual(60, form.cleaned_data['start'])
        self.assertEqual(65, form.cleaned_data['end'])

        form = forms.DurationSkipForm(data={
            'start': '15:23',
            'end': '18:43',
        }, existing_skips=[])
        self.assertTrue(form.is_valid())
        self.assertEqual(923, form.cleaned_data['start'])
        self.assertEqual(1123, form.cleaned_data['end'])

    def test_chapter_form_accepts_both_point_formats(self):
        form = forms.ChapterForm(data={
            'point': '60',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(60, form.cleaned_data['point'])
        self.assertEqual('test', form.cleaned_data['note'])

        form = forms.ChapterForm(data={
            'point': '15:23',
            'note': 'test',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(923, form.cleaned_data['point'])
        self.assertEqual('test', form.cleaned_data['note'])

    def test_durationskip_form_blocks_overlapping(self):
        form = forms.DurationSkipForm(data={
            'start': '60',
            'end': '65',
        }, existing_skips=[(30, 70)])
        self.assertFalse(form.is_valid())
        self.assertEqual('Chosen time range overlaps another skip.', form.errors['start'][0])

    def test_durationskip_form_errors_end_before_start(self):
        form = forms.DurationSkipForm(data={
            'start': '65',
            'end': '60',
        }, existing_skips=[])
        self.assertFalse(form.is_valid())
        self.assertEqual('End must be greater than start time', form.errors['end'][0])


class JsonEncoderTests(TestCase):
    def test_basics(self):
        def test_func(): pass
        test_func_str = str(test_func)
        video = models.Video.objects.create(title='test video')
        data = {
            'str': '',
            'tuple': tuple(),
            'set': set(),
            'dict': dict(),
            'func': test_func,
            "video": video,
        }
        output = json.dumps(data, cls=json_encoders.JSONSetToListEncoder)
        expected = f'{{"str": "", "tuple": [], "set": [], "dict": {{}}, "func": "{test_func_str}", "video": "{video}"}}'
        self.assertEqual(expected, output)


class RenamerTests(TestCase):
    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    @patch('vidar.services.video_services.generate_filepaths_for_storage')
    def test_video_rename_all_files_works(self, mock_generator, mock_move, mock_delete):
        mock_generator.return_value = 'static value'
        mock_generator.side_effect = [
            ('', pathlib.PurePosixPath('video 2.mp4')),
            ('', pathlib.PurePosixPath('info 2.json')),
            ('', pathlib.PurePosixPath('thumbnail 2.jpg')),
        ]
        mock_move.return_value = 'here in mock 2'
        channel = models.Channel.objects.create(name='Test Channel')
        video = models.Video.objects.create(
            channel=channel,
            title='Test Video',
            file='video.mp4',
            thumbnail='thumbnail.jpg',
            info_json='info.json',
            provider_object_id='test vidar id',
        )
        output = renamers.video_rename_all_files(video=video, commit=True)
        self.assertListEqual(['file', 'info_json', 'thumbnail'], output)
        mock_move.assert_has_calls((
            call(pathlib.PurePosixPath('video.mp4'), pathlib.PurePosixPath('video 2.mp4')),
            call(pathlib.PurePosixPath('info.json'), pathlib.PurePosixPath('info 2.json')),
            call(pathlib.PurePosixPath('thumbnail.jpg'), pathlib.PurePosixPath('thumbnail 2.jpg')),
        ))
        mock_generator.assert_has_calls((
            call(video=video, ext='mp4'),
            call(video=video, ext='info.json', upload_to=video_helpers.upload_to_infojson),
            call(video=video, ext='jpg', upload_to=video_helpers.upload_to_thumbnail),
        ))
        mock_delete.assert_not_called()

        self.assertEqual('video 2.mp4', video.file.name)
        self.assertEqual('info 2.json', video.info_json.name)
        self.assertEqual('thumbnail 2.jpg', video.thumbnail.name)

        video.refresh_from_db()

        self.assertEqual('video 2.mp4', video.file.name)
        self.assertEqual('info 2.json', video.info_json.name)
        self.assertEqual('thumbnail 2.jpg', video.thumbnail.name)

    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    @patch('vidar.services.video_services.generate_filepaths_for_storage')
    def test_video_rename_all_files_storage_already_exists(self, mock_generator, mock_move, mock_delete):
        mock_generator.return_value = 'static value'
        mock_generator.side_effect = [
            ('', pathlib.PurePosixPath('video.mp4')),
            ('', pathlib.PurePosixPath('info.json')),
            ('', pathlib.PurePosixPath('thumbnail.jpg')),
        ]
        mock_move.return_value = 'here in mock 2'
        channel = models.Channel.objects.create(name='Test Channel')
        video = models.Video.objects.create(
            channel=channel,
            title='Test Video',
            file='video.mp4',
            thumbnail='thumbnail.jpg',
            info_json='info.json',
            provider_object_id='test vidar id',
        )

        with self.assertLogs('vidar.renamers') as logger:
            output = renamers.video_rename_all_files(video=video, commit=True)
            self.assertListEqual([], output)

        expected_logs = [
            f"INFO:vidar.renamers:Checking video files are named correctly. commit=True {video=}",
            f"INFO:vidar.renamers:{video.pk=} storage paths already match, video.mp4 does not need renaming.",
            f"INFO:vidar.renamers:{video.pk=} storage paths already match, info.json does not need renaming.",
            f"INFO:vidar.renamers:{video.pk=} storage paths already match, thumbnail.jpg does not need renaming."
        ]
        self.maxDiff = None
        self.assertCountEqual(expected_logs, logger.output)

        mock_move.assert_not_called()
        mock_generator.assert_has_calls((
            call(video=video, ext='mp4'),
            call(video=video, ext='info.json', upload_to=video_helpers.upload_to_infojson),
            call(video=video, ext='jpg', upload_to=video_helpers.upload_to_thumbnail),
        ))
        mock_delete.assert_not_called()

        self.assertEqual('video.mp4', video.file.name)
        self.assertEqual('info.json', video.info_json.name)
        self.assertEqual('thumbnail.jpg', video.thumbnail.name)

        video.refresh_from_db()

        self.assertEqual('video.mp4', video.file.name)
        self.assertEqual('info.json', video.info_json.name)
        self.assertEqual('thumbnail.jpg', video.thumbnail.name)

    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    @patch('vidar.services.video_services.generate_filepaths_for_storage')
    def test_changing_dir_calls_delete(self, mock_generator, mock_move, mock_delete):
        mock_generator.return_value = ('', pathlib.PurePosixPath('dir 2/video.mp4'))
        mock_move.return_value = 'here in mock 2'
        channel = models.Channel.objects.create(name='Test Channel')
        video = models.Video.objects.create(
            channel=channel,
            title='Test Video',
            file='dir/video.mp4',
            provider_object_id='test vidar id',
        )
        output = renamers.video_rename_all_files(video=video, commit=True)
        self.assertTrue(output)
        mock_move.assert_called_once_with(pathlib.PurePosixPath('dir/video.mp4'), pathlib.PurePosixPath('dir 2/video.mp4'))
        mock_generator.assert_called_once_with(video=video, ext='mp4')
        mock_delete.assert_called_once_with('dir')

        self.assertEqual('dir 2/video.mp4', video.file.name)

    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    @patch('vidar.services.video_services.generate_filepaths_for_storage')
    def test_call_on_video_with_no_files_does_nothing(self, mock_generator, mock_move, mock_delete):
        channel = models.Channel.objects.create(name='Test Channel')
        video = models.Video.objects.create(
            channel=channel,
            title='Test Video',
            provider_object_id='test vidar id',
        )
        output = renamers.video_rename_all_files(video=video, commit=True)
        self.assertFalse(output)
        self.assertEqual('', video.file.name)
        self.assertEqual('', video.info_json.name)
        self.assertIsNone(video.thumbnail.name)

        mock_delete.assert_not_called()
        mock_move.assert_not_called()
        mock_generator.assert_not_called()

    @patch('vidar.helpers.file_helpers.can_file_be_moved')
    def test_storage_has_no_ability_to_move_files(self, mock_move):
        mock_move.return_value = False

        video = models.Video.objects.create(title='Test Video')
        with self.assertRaises(exceptions.FileStorageBackendHasNoMoveError):
            renamers.video_rename_all_files(video=video, commit=True)

        channel = models.Channel.objects.create(name='Test Channel')
        with self.assertRaises(exceptions.FileStorageBackendHasNoMoveError):
            renamers.channel_rename_all_files(channel=channel)

    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    @patch('vidar.services.channel_services.generate_filepaths_for_storage')
    def test_channel_rename_all_files_works(self, mock_generator, mock_move, mock_delete):
        mock_generator.return_value = 'static value'
        mock_generator.side_effect = [
            ('', pathlib.PurePosixPath('thumbnail 2.jpg')),
            ('', pathlib.PurePosixPath('tvart 2.jpg')),
            ('', pathlib.PurePosixPath('banner 2.jpg')),
        ]
        mock_move.return_value = 'here in mock 2'

        channel = models.Channel.objects.create(
            name='Test Channel',
            thumbnail='thumbnail.jpg',
            tvart='tvart.jpg',
            banner='banner.jpg',
        )

        output = renamers.channel_rename_all_files(channel=channel, commit=True)
        self.assertListEqual(['thumbnail', 'tvart', 'banner'], output)
        mock_move.assert_has_calls((
            call(pathlib.PurePosixPath('thumbnail.jpg'), pathlib.PurePosixPath('thumbnail 2.jpg')),
            call(pathlib.PurePosixPath('tvart.jpg'), pathlib.PurePosixPath('tvart 2.jpg')),
            call(pathlib.PurePosixPath('banner.jpg'), pathlib.PurePosixPath('banner 2.jpg')),
        ))
        mock_generator.assert_has_calls((
            call(channel=channel, field=channel.thumbnail, filename=f'{channel.name}.jpg', upload_to=channel_helpers.upload_to_thumbnail),
            call(channel=channel, field=channel.tvart, filename='tvart.jpg', upload_to=channel_helpers.upload_to_tvart),
            call(channel=channel, field=channel.banner, filename='banner.jpg', upload_to=channel_helpers.upload_to_banner),
        ))
        mock_delete.assert_not_called()

        self.assertEqual('thumbnail 2.jpg', channel.thumbnail.name)
        self.assertEqual('tvart 2.jpg', channel.tvart.name)
        self.assertEqual('banner 2.jpg', channel.banner.name)

    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    @patch('vidar.services.channel_services.generate_filepaths_for_storage')
    def test_channel_rename_all_files_storage_already_exists(self, mock_generator, mock_move, mock_delete):
        mock_generator.return_value = 'static value'
        mock_generator.side_effect = [
            ('', pathlib.PurePosixPath('thumbnail.jpg')),
            ('', pathlib.PurePosixPath('tvart.jpg')),
            ('', pathlib.PurePosixPath('banner.jpg')),
        ]
        mock_move.return_value = 'here in mock 2'
        channel = models.Channel.objects.create(
            name='Test Channel',
            thumbnail='thumbnail.jpg',
            tvart='tvart.jpg',
            banner='banner.jpg',
        )

        with self.assertLogs('vidar.renamers') as logger:
            output = renamers.channel_rename_all_files(channel=channel, commit=True)
            self.assertListEqual([], output)

        expected_logs = [
            f"INFO:vidar.renamers:Checking channel files are named correctly. commit=True {channel=}",
            f"INFO:vidar.renamers:{channel.pk=} storage paths already match, thumbnail.jpg does not need renaming.",
            f"INFO:vidar.renamers:{channel.pk=} storage paths already match, tvart.jpg does not need renaming.",
            f"INFO:vidar.renamers:{channel.pk=} storage paths already match, banner.jpg does not need renaming."
        ]
        self.maxDiff = None
        self.assertCountEqual(expected_logs, logger.output)

        mock_move.assert_not_called()
        mock_generator.assert_has_calls((
            call(channel=channel, field=channel.thumbnail, filename=f'{channel.name}.jpg', upload_to=channel_helpers.upload_to_thumbnail),
            call(channel=channel, field=channel.tvart, filename='tvart.jpg', upload_to=channel_helpers.upload_to_tvart),
            call(channel=channel, field=channel.banner, filename='banner.jpg', upload_to=channel_helpers.upload_to_banner),
        ))
        mock_delete.assert_not_called()

        self.assertEqual('thumbnail.jpg', channel.thumbnail.name)
        self.assertEqual('tvart.jpg', channel.tvart.name)
        self.assertEqual('banner.jpg', channel.banner.name)

        channel.refresh_from_db()

        self.assertEqual('thumbnail.jpg', channel.thumbnail.name)
        self.assertEqual('tvart.jpg', channel.tvart.name)
        self.assertEqual('banner.jpg', channel.banner.name)

    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    @patch('vidar.services.video_services.generate_filepaths_for_storage')
    def test_call_on_channel_with_no_files_does_nothing(self, mock_generator, mock_move, mock_delete):
        channel = models.Channel.objects.create(name='Test Channel')

        output = renamers.channel_rename_all_files(channel=channel, commit=True)
        self.assertEqual([], output)
        self.assertIsNone(channel.thumbnail.name)
        self.assertIsNone(channel.tvart.name)
        self.assertIsNone(channel.banner.name)

        mock_delete.assert_not_called()
        mock_move.assert_not_called()
        mock_generator.assert_not_called()

    @patch('vidar.renamers.video_rename_all_files')
    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    def test_channel_rename_all_videos_with_files(self, mock_move, mock_delete, mock_video_renamer):
        mock_video_renamer.return_value = ['file']
        channel = models.Channel.objects.create(name='Test Channel')
        models.Video.objects.create(title='test video 1', channel=channel, file='test 1.mp4')

        output = renamers.channel_rename_all_files(channel=channel, rename_videos=True)
        self.assertEqual(['1 videos'], output)

        mock_video_renamer.assert_called_once()
        mock_delete.assert_not_called()
        mock_move.assert_not_called()

    @patch('vidar.renamers.video_rename_all_files')
    @patch('vidar.storages.vidar_storage.delete')
    @patch('vidar.storages.vidar_storage.move')
    def test_channel_rename_all_videos_without_files(self, mock_move, mock_delete, mock_video_renamer):
        mock_video_renamer.return_value = ['file']
        channel = models.Channel.objects.create(name='Test Channel')
        models.Video.objects.create(title='test video 1', channel=channel)

        output = renamers.channel_rename_all_files(channel=channel, rename_videos=True)
        self.assertEqual([], output)

        mock_video_renamer.assert_not_called()
        mock_delete.assert_not_called()
        mock_move.assert_not_called()


def ytdlp_initializer_test(action, instance=None, **kwargs):
    return f'inside vidar.tests.test_general.ytdlp_initializer_test {action=} {instance=} {kwargs=}'


class InteractorTests(SimpleTestCase):

    @patch('yt_dlp.YoutubeDL')
    def test_is_ytdlp_interactor_from_settings(self, mock_ytdlp):
        mock_ytdlp.side_effect = ValueError('yt_dlp.YoutubeDL should NOT be called while testing. Patching failed.')
        user_func = app_settings.YTDLP_INITIALIZER

        self.assertEqual(settings.my_ytdlp_initializer, user_func)

        output = user_func(action="testing")
        expected = "Successfully called example.settings.my_ytdlp_initializer"
        self.assertEqual(expected, output)

    def test_cleaning_kwargs(self):
        kwargs = {
            "kept": "value",
            "instance": "should be gone",
            "action": "should be gone",
        }
        interactor._clean_kwargs(kwargs)
        self.assertNotIn("instance", kwargs)
        self.assertNotIn("action", kwargs)
        self.assertIn("kept", kwargs)

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.utils.get_proxy')
    @override_settings(VIDAR_YTDLP_INITIALIZER='vidar.tests.test_general.ytdlp_initializer_test')
    def test_get_ytdlp_with_user_set_initializer(self, mock_proxy, mock_ytdlp):
        mock_ytdlp.side_effect = ValueError('yt_dlp.YoutubeDL should NOT be called while testing. Patching failed.')
        kwargs = dict(
            action='test_get_ytdlp action',
            instance='test_get_ytdlp instance',
            extra='field',
        )
        output = interactor.get_ytdlp(kwargs=kwargs)
        expected = "inside vidar.tests.test_general.ytdlp_initializer_test action='test_get_ytdlp action' instance='test_get_ytdlp instance' kwargs={'extra': 'field'}"
        self.assertEqual(expected, output)
        self.assertNotIn("instance", kwargs)
        self.assertNotIn("action", kwargs)
        self.assertIn("extra", kwargs)
        mock_proxy.assert_not_called()

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.utils.get_proxy')
    @override_settings(VIDAR_YTDLP_INITIALIZER=None)
    def test_get_ytdlp_with_default_initializer(self, mock_proxy, mock_ytdlp):
        mock_ytdlp.return_value = "mocked yt-dlp call"
        mock_proxy.return_value = "proxy address"
        kwargs = dict(
            action='test_get_ytdlp action',
            instance='test_get_ytdlp instance',
            extra='field',
        )
        output = interactor.get_ytdlp(kwargs=kwargs)
        self.assertEqual("mocked yt-dlp call", output)
        self.assertNotIn("instance", kwargs)
        self.assertNotIn("action", kwargs)
        self.assertIn("extra", kwargs)

        mock_ytdlp.assert_called_once()
        mock_ytdlp.assert_called_with(dict(extra='field', proxy="proxy address"))
        mock_proxy.assert_called_once()

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor.channel_videos')
    @patch('time.sleep')
    def test_func_with_retry_fails(self, mock_sleep, mock_interactor, mock_ytdlp):
        mock_ytdlp.side_effect = ValueError('yt_dlp.YoutubeDL should NOT be called while testing. Patching failed.')
        mock_interactor.return_value = ""

        output = interactor.func_with_retry(url="url", func=interactor.channel_videos, extra='data')

        self.assertIsNone(output)
        mock_interactor.assert_has_calls([
            call(url="url", extra="data"),
            call(url="url", extra="data"),
        ])
        mock_sleep.assert_called()

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor.channel_videos')
    @patch('time.sleep')
    def test_func_with_retry_worked(self, mock_sleep, mock_interactor, mock_ytdlp):
        mock_ytdlp.side_effect = ValueError('yt_dlp.YoutubeDL should NOT be called while testing. Patching failed.')
        expected = {"entries": ["entry1", "entry2"]}
        mock_interactor.return_value = expected

        output = interactor.func_with_retry(url="url", sleep=0, func=interactor.channel_videos, extra='data')
        self.assertEqual(expected, output)
        mock_sleep.assert_not_called()

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor._clean_kwargs')
    @override_settings(VIDAR_YTDLP_INITIALIZER=None)
    def test_interactor_playlist_details_passes_action(self, mock_cleaner, mock_ytdlp):
        mock_ytdlp.return_value.__enter__.return_value.extract_info.return_value = "extract_info test"

        output = interactor.playlist_details(url="url")
        self.assertEqual("extract_info test", output)
        mock_ytdlp.assert_called_once()
        mock_ytdlp.return_value.__enter__.return_value.extract_info.assert_called_once()
        mock_cleaner.assert_called_once()

        first_call = mock_ytdlp.mock_calls[0]
        first_call_args = first_call.args[0]
        self.assertIn("action", first_call_args)
        self.assertEqual("playlist_details", first_call_args["action"])

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor._clean_kwargs')
    @override_settings(VIDAR_YTDLP_INITIALIZER=None)
    def test_interactor_video_download_passes_action(self, mock_cleaner, mock_ytdlp):
        mock_ytdlp.return_value.__enter__.return_value.extract_info.return_value = "extract_info test"

        output, _ = interactor.video_download(url="url")
        self.assertEqual("extract_info test", output)
        mock_ytdlp.assert_called_once()
        mock_ytdlp.return_value.__enter__.return_value.extract_info.assert_called_once()
        mock_cleaner.assert_called_once()
        first_call = mock_ytdlp.mock_calls[0]
        first_call_args = first_call.args[0]
        self.assertIn("action", first_call_args)
        self.assertEqual("video_download", first_call_args["action"])

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor._clean_kwargs')
    @override_settings(VIDAR_YTDLP_INITIALIZER=None)
    def test_interactor_video_details_passes_action(self, mock_cleaner, mock_ytdlp):
        mock_ytdlp.return_value.__enter__.return_value.extract_info.return_value = "extract_info test"

        output = interactor.video_details(url="url")
        self.assertEqual("extract_info test", output)
        mock_ytdlp.assert_called_once()
        mock_ytdlp.return_value.__enter__.return_value.extract_info.assert_called_once()
        mock_cleaner.assert_called_once()
        first_call = mock_ytdlp.mock_calls[0]
        first_call_args = first_call.args[0]
        self.assertIn("action", first_call_args)
        self.assertEqual("video_details", first_call_args["action"])

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor._clean_kwargs')
    @override_settings(VIDAR_YTDLP_INITIALIZER=None)
    def test_interactor_video_comments_passes_action(self, mock_cleaner, mock_ytdlp):
        mock_ytdlp.return_value.__enter__.return_value.extract_info.return_value = "extract_info test"

        output = interactor.video_comments(url="url")
        self.assertEqual("extract_info test", output)
        mock_ytdlp.assert_called_once()
        mock_ytdlp.return_value.__enter__.return_value.extract_info.assert_called_once()
        mock_cleaner.assert_called_once()
        first_call = mock_ytdlp.mock_calls[0]
        first_call_args = first_call.args[0]
        self.assertIn("action", first_call_args)
        self.assertEqual("video_comments", first_call_args["action"])


    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor._clean_kwargs')
    @override_settings(VIDAR_YTDLP_INITIALIZER=None)
    def test_interactor_channel_details_passes_action(self, mock_cleaner, mock_ytdlp):
        mock_ytdlp.return_value.__enter__.return_value.extract_info.return_value = "extract_info test"

        output = interactor.channel_details(url="url")
        self.assertEqual("extract_info test", output)
        mock_ytdlp.assert_called_once()
        mock_ytdlp.return_value.__enter__.return_value.extract_info.assert_called_once()
        mock_cleaner.assert_called_once()
        first_call = mock_ytdlp.mock_calls[0]
        first_call_args = first_call.args[0]
        self.assertIn("action", first_call_args)
        self.assertEqual("channel_details", first_call_args["action"])

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor._clean_kwargs')
    @override_settings(VIDAR_YTDLP_INITIALIZER=None)
    def test_interactor_channel_videos_passes_action(self, mock_cleaner, mock_ytdlp):
        mock_ytdlp.return_value.__enter__.return_value.extract_info.return_value = "extract_info test"

        output = interactor.channel_videos(url="url", limit=2)
        self.assertEqual("extract_info test", output)
        mock_ytdlp.assert_called_once()
        mock_ytdlp.return_value.__enter__.return_value.extract_info.assert_called_once()
        mock_cleaner.assert_called_once()
        first_call = mock_ytdlp.mock_calls[0]
        first_call_args = first_call.args[0]
        self.assertIn("action", first_call_args)
        self.assertEqual("channel_videos", first_call_args["action"])
        self.assertIn("playlistend", first_call_args)
        self.assertEqual(2, first_call_args["playlistend"])

    @patch('yt_dlp.YoutubeDL')
    @patch('vidar.interactor._clean_kwargs')
    @override_settings(VIDAR_YTDLP_INITIALIZER=None)
    def test_interactor_channel_playlists_passes_action(self, mock_cleaner, mock_ytdlp):
        mock_ytdlp.return_value.__enter__.return_value.extract_info.return_value = "extract_info test"

        output = interactor.channel_playlists("url")
        self.assertEqual("extract_info test", output)
        mock_ytdlp.assert_called_once()
        mock_ytdlp.return_value.__enter__.return_value.extract_info.assert_called_once()
        mock_cleaner.assert_called_once()
        first_call = mock_ytdlp.mock_calls[0]
        first_call_args = first_call.args[0]
        self.assertIn("action", first_call_args)
        self.assertEqual("channel_playlists", first_call_args["action"])


def proxies_user_defined(**kwargs):
    return kwargs


class UtilsTests(TestCase):

    @override_settings(
        VIDAR_PROXIES_DEFAULT="default proxy",
        VIDAR_PROXIES=['proxy1', 'proxy2', 'proxy3', 'proxy4']
    )
    def test_get_proxy_returns_default_after_x(self):
        possible_proxies = ['proxy1', 'proxy2', 'proxy3', 'proxy4']
        self.assertIn(utils.get_proxy(attempt=0), possible_proxies)
        self.assertIn(utils.get_proxy(attempt=1), possible_proxies)
        self.assertEqual("default proxy", utils.get_proxy(attempt=2))

    @override_settings(
        VIDAR_PROXIES_DEFAULT="default proxy",
        VIDAR_PROXIES=['proxy1', 'proxy2', 'proxy3', 'proxy4']
    )
    def test_get_proxy_with_previous_proxies_supplied(self):
        self.assertEqual("proxy3", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy4']))
        self.assertEqual("default proxy", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy3', 'proxy4']))

    @override_settings(
        VIDAR_PROXIES_DEFAULT="default proxy",
        VIDAR_PROXIES='proxy1,proxy2,proxy3,proxy4'
    )
    def test_get_proxy_proxies_supplied_as_comma_delim_string(self):
        self.assertEqual("proxy3", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy4']))
        self.assertEqual("default proxy", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy3', 'proxy4']))

    @override_settings(VIDAR_PROXIES=proxies_user_defined)
    def test_get_proxy_with_proxies_user_defined_function(self):
        self.assertEqual(proxies_user_defined, app_settings.PROXIES)

        output = utils.get_proxy(previous_proxies=['passed into utils.get_proxy'])
        self.assertEqual(dict(previous_proxies=["passed into utils.get_proxy"], instance=None, attempt=None), output)

    @override_settings(VIDAR_PROXIES=proxies_user_defined)
    def test_get_proxy_with_proxies_user_defined_function_always_called(self):
        self.assertEqual(proxies_user_defined, app_settings.PROXIES)

        output = utils.get_proxy(previous_proxies=['passed into utils.get_proxy'], attempt=100)
        self.assertEqual(dict(previous_proxies=["passed into utils.get_proxy"], instance=None, attempt=100), output)
