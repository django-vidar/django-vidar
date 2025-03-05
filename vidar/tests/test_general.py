# flake8: noqa
import pathlib

from unittest.mock import patch, call

from django.test import TestCase
from django.shortcuts import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group
from django.utils import timezone

from vidar import models, forms, renamers
from vidar.helpers import video_helpers

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


class VideoTests(TestCase):
    def test_system_safe_title(self):
        video = models.Video.objects.create(
            title="The Myth Busting / Saving a Machinist's A $ $ - Professional TIG Welding Career Advice"
        )

        expected = 'The Myth Busting Saving a Machinists A Professional TIG Welding Career Advice'
        self.assertEqual(expected, video.system_safe_title)

    def test_system_safe_title_the(self):
        video = models.Video.objects.create(
            title="The Myth Busting / Saving a Machinist's A $ $ - Professional TIG Welding Career Advice"
        )

        expected = 'Myth Busting Saving a Machinists A Professional TIG Welding Career Advice, The'
        self.assertEqual(expected, video.system_safe_title_the)


class ChannelTests(TestCase):
    def test_system_safe_name(self):
        channel = models.Channel.objects.create(name="The Myth Busting & Associates")

        expected = 'The Myth Busting and Associates'
        self.assertEqual(expected, channel.system_safe_name)

    def test_system_safe_name_the(self):
        channel = models.Channel.objects.create(name="tHe Myth Busting & Associates")

        expected = 'Myth Busting and Associates, tHe'
        self.assertEqual(expected, channel.system_safe_name_the)


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


@patch('vidar.storages.vidar_storage.delete')
@patch('vidar.storages.vidar_storage.move')
@patch('vidar.services.video_services.generate_filepaths_for_storage')
class RenamerTests(TestCase):
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
        self.assertTrue(output)
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
