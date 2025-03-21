import urllib.parse
from unittest.mock import patch, call

import bootstrap4.exceptions
from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group
from django.core.files.uploadedfile import SimpleUploadedFile

from vidar import models, forms
from vidar.helpers import channel_helpers, celery_helpers, model_helpers
from vidar.services import video_services

from tests.test_functions import date_to_aware_date

User = get_user_model()


class Generate_crontab_tests(TestCase):

    url = reverse('vidar:htmx-crontab-generate')

    def make_url(self, **kwargs):
        output = ""
        if kwargs:
            output = self.url + "?" + urllib.parse.urlencode(kwargs)
        url = output or self.url
        return url

    def test_permission_not_required(self):
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_yearly(self):
        resp = self.client.get(self.make_url(type="yearly"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} (\d+){1,2} \*')

        resp = self.client.get(self.make_url(type="yearly", hours=[2,3]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) ([2,3]) (\d+){1,2} (\d+){1,2} \*')

    def test_biyearly(self):
        resp = self.client.get(self.make_url(type="biyearly"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} (\d+){1,2},(\d+){,2} \*')

        resp = self.client.get(self.make_url(type="biyearly", hours=[2,3]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) ([2,3]) (\d+){1,2} (\d+){1,2},(\d+){,2} \*')

    def test_monthly(self):
        resp = self.client.get(self.make_url(type="monthly"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} \* \*')

        resp = self.client.get(self.make_url(type="monthly", hours=[2,3]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) ([2,3]) (\d+){1,2} \* \*')

    def test_monthly_with_channel(self):
        channel = models.Channel.objects.create()
        resp = self.client.get(self.make_url(type="monthly", channel=channel.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} \* \*')

        channel.videos.create(upload_date=date_to_aware_date('2025-01-03'))
        channel.videos.create(upload_date=date_to_aware_date('2025-02-03'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-03'))

        resp = self.client.get(self.make_url(type="monthly", channel=channel.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} 3 \* \*')

        channel.videos.create(upload_date=date_to_aware_date('2025-03-06'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-15'))

        resp = self.client.get(self.make_url(type="monthly", channel=channel.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} 3 \* \*')

    def test_monthly_with_playlist(self):
        playlist = models.Playlist.objects.create()
        resp = self.client.get(self.make_url(type="monthly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} \* \*')

        playlist.videos.create(upload_date=date_to_aware_date('2025-01-03'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-02-03'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-03'))

        resp = self.client.get(self.make_url(type="monthly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} 3 \* \*')

        playlist.videos.create(upload_date=date_to_aware_date('2025-03-06'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-15'))

        resp = self.client.get(self.make_url(type="monthly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} 3 \* \*')

    def test_weekly(self):
        resp = self.client.get(self.make_url(type="weekly"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* [0-7]')

        resp = self.client.get(self.make_url(type="weekly", hours=[2,3]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) ([2,3]) \* \* [0-7]')

        resp = self.client.get(self.make_url(type="weekly", hours=[2,3], day_of_week=[4,5]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) ([2,3]) \* \* [4,5]')

        resp = self.client.get(self.make_url(type="weekly", day_of_week=[4,5]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* [4,5]')

        with self.assertRaises(ValueError):
            self.client.get(self.make_url(type="weekly", day_of_week=9))

    def test_weekly_with_channel(self):
        channel = models.Channel.objects.create()
        resp = self.client.get(self.make_url(type="weekly", channel=channel.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* [0-7]')

        # videos released on mondays should scan on tuesday
        channel.videos.create(upload_date=date_to_aware_date('2025-03-03'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-10'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-17'))

        resp = self.client.get(self.make_url(type="weekly", channel=channel.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* 2')

        channel.videos.create(upload_date=date_to_aware_date('2025-03-06'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-15'))

        # Most common upload date is still monday, scan on tuesdays still.
        resp = self.client.get(self.make_url(type="weekly", channel=channel.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* 2')

    def test_weekly_with_playlist(self):
        playlist = models.Playlist.objects.create()
        resp = self.client.get(self.make_url(type="weekly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* [0-7]')

        # videos released on mondays should scan on tuesday
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-03'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-10'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-17'))

        resp = self.client.get(self.make_url(type="weekly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* 2')

        playlist.videos.create(upload_date=date_to_aware_date('2025-03-06'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-15'))

        # Most common upload date is still monday, scan on tuesdays still.
        resp = self.client.get(self.make_url(type="weekly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* 2')

    def test_daily(self):
        resp = self.client.get(self.make_url())
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* \*')

        resp = self.client.get(self.make_url(hours=[2,3]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) ([2,3]) \* \* \*')

        resp = self.client.get(self.make_url(type="daily"))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* \*')

        resp = self.client.get(self.make_url(type="daily", hours=[2,3]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) ([2,3]) \* \* \*')

    def test_every_other_day(self):
        resp = self.client.get(self.make_url(type="every_other_day"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (\d+){1,2} \* \* (0-7\/2|1-7\/2)')

        resp = self.client.get(self.make_url(type="every_other_day", hours=[2,3]))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) ([2,3]) \* \* (0-7\/2|1-7\/2)')

    def test_hourly(self):
        resp = self.client.get(self.make_url(type="hourly"))
        self.assertRegex(resp.content, br'(0|10|20|30|40|50) (7-21\/4|6-22\/4) \* \* \*')

    def test_hourly_balanced(self):

        # Hourly also balances to try and ensure channels are spread
        #   out among the 2 hour selections.
        # Let's fill out all of one hour
        models.Channel.objects.create(scanner_crontab='0 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='10 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='20 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='30 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='40 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='50 7-21/4 * * *')

        for x in range(14):
            resp = self.client.get(self.make_url(type="hourly"))
            self.assertRegex(resp.content, br'(0|10|20|30|40|50) 6-22/4 \* \* \*')


class Channel_alter_integer_tests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission_change_channel = Permission.objects.get(codename="change_channel")
        self.user.user_permissions.add(self.permission_change_channel)

        self.channel = models.Channel.objects.create()
        self.url = reverse('vidar:channel-alter-ints', args=[self.channel.pk])

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url + "?field=delete_videos_after_days")
        self.assertEqual(200, resp.status_code)

    def test_increment(self):
        self.client.force_login(self.user)

        resp = self.client.get(self.url + "?field=delete_videos_after_days")
        self.assertEqual(b'0', resp.content)

        resp = self.client.post(self.url + "?field=delete_videos_after_days")
        self.assertEqual(b'1', resp.content)

        resp = self.client.get(self.url + "?field=delete_videos_after_days")
        self.assertEqual(b'1', resp.content)

    def test_decrement(self):
        self.client.force_login(self.user)

        self.channel.delete_videos_after_days = 5
        self.channel.save()

        resp = self.client.get(self.url + "?field=delete_videos_after_days&direction=decrement")
        self.assertEqual(b'5', resp.content)

        resp = self.client.post(self.url + "?field=delete_videos_after_days&direction=decrement")
        self.assertEqual(b'4', resp.content)

        resp = self.client.get(self.url + "?field=delete_videos_after_days&direction=decrement")
        self.assertEqual(b'4', resp.content)


class Channel_add_view_tests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission_change_channel = Permission.objects.get(codename="add_channel")
        self.user.user_permissions.add(self.permission_change_channel)

        self.url = reverse('vidar:channel-create')

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    @patch("requests.get")
    def test_request_param_channel_live_url_redirects_to_existing(self, mock_get):
        mock_get.side_effect = NotImplementedError()
        self.client.force_login(self.user)
        channel = models.Channel.objects.create(provider_object_id='Uexisting_id')
        resp = self.client.get(self.url + "?" + urllib.parse.urlencode({"url": "https://www.youtube.com/channel/Uexisting_id"}))
        self.assertEqual(302, resp.status_code)
        self.assertEqual(channel.get_absolute_url(), resp.url)
        mock_get.assert_not_called()

    @patch("requests.get")
    def test_request_param_channel_live_provider_id_redirects_to_existing(self, mock_get):
        mock_get.side_effect = NotImplementedError()
        self.client.force_login(self.user)
        channel = models.Channel.objects.create(provider_object_id='Uexisting_id')
        resp = self.client.get(self.url + "?" + urllib.parse.urlencode({"channel": "Uexisting_id"}))
        self.assertEqual(302, resp.status_code)
        self.assertEqual(channel.get_absolute_url(), resp.url)
        mock_get.assert_not_called()

        channel = models.Channel.objects.create(uploader_id='existing_id')
        resp = self.client.get(self.url + "?" + urllib.parse.urlencode({"channel": "existing_id"}))
        self.assertEqual(302, resp.status_code)
        self.assertEqual(channel.get_absolute_url(), resp.url)
        mock_get.assert_not_called()

    @patch("vidar.forms.ChannelVideosOptionsForm")
    @patch("vidar.forms.ChannelShortsOptionsForm")
    @patch("vidar.forms.ChannelLivestreamsOptionsForm")
    def test_index_false_disables_indexing_initial(self, mock_ls_form, mock_s_form, mock_v_form):
        self.client.force_login(self.user)

        try:
            resp = self.client.get(self.url + "?index=False")
            self.fail('Boostrap should have errored because it expects the form to be a form')
        except bootstrap4.exceptions.BootstrapError:
            pass

        mock_s_form.assert_called_once()
        mock_ls_form.assert_called_once()
        mock_v_form.assert_called_once()

        mock_s_form.assert_called_with(initial={"index_shorts": False, "download_shorts": False})
        mock_ls_form.assert_called_with(initial={"index_livestreams": False, "download_livestreams": False})
        mock_v_form.assert_called_with(initial={"index_videos": False, "download_videos": False})

    @patch("vidar.forms.ChannelVideosOptionsForm")
    @patch("vidar.forms.ChannelShortsOptionsForm")
    @patch("vidar.forms.ChannelLivestreamsOptionsForm")
    def test_index_true_leaves_indexing_initial_at_default(self, mock_ls_form, mock_s_form, mock_v_form):
        self.client.force_login(self.user)
        try:
            self.client.get(self.url)
            self.fail('Boostrap should have errored because it expects the form to be a form')
        except bootstrap4.exceptions.BootstrapError:
            pass

        mock_s_form.assert_called_once()
        mock_ls_form.assert_called_once()
        mock_v_form.assert_called_once()

        mock_s_form.assert_called_with(initial={"index_shorts": False, "download_shorts": False})
        mock_ls_form.assert_called_with(initial=None)
        mock_v_form.assert_called_with(initial=None)


class GeneralUtilitiesViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password", is_superuser=True)

        self.client.force_login(self.user)

        self.url = reverse('vidar:utilities')

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()

        self.client.force_login(User.objects.create_user(username="testuser2", password="password"))
        resp = self.client.get(self.url)
        self.assertEqual(403, resp.status_code)

    @patch("vidar.tasks.rename_all_archived_video_files")
    def test_videos_rename_files(self, mock_renamer):
        resp = self.client.post(self.url, {"videos_rename_files": True})

        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.url, resp.url)

        msgs = messages.get_messages(resp.wsgi_request)

        self.assertEqual(1, len(msgs))

        mock_renamer.delay.assert_called_once()

    @patch("vidar.tasks.channel_rename_files")
    def test_channel_rename_files(self, mock_renamer):

        channel = models.Channel.objects.create()

        resp = self.client.post(self.url, {"channel_rename_files": True, "channel": channel.pk})

        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.url, resp.url)

        msgs = messages.get_messages(resp.wsgi_request)

        self.assertEqual(1, len(msgs))

        mock_renamer.delay.assert_called_once()

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    def test_scan_all(self, mock_scanner):
        mock_scanner.return_value = 10

        channel1 = models.Channel.objects.create()
        channel2 = models.Channel.objects.create()
        channel3 = models.Channel.objects.create(index_videos=True)

        resp = self.client.post(self.url, {"scan_all": True, "countdown": 10})

        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.url, resp.url)

        mock_scanner.assert_has_calls([
            call(
                channel=channel1,
                countdown=0,
                wait_period=10,
            ),
            call(
                channel=channel2,
                countdown=10,
                wait_period=10,
            ),
            call(
                channel=channel3,
                countdown=10,
                wait_period=10,
            ),
        ])

    @patch("vidar.tasks.trigger_channel_scanner_tasks")
    def test_scan_all_indexing_only(self, mock_scanner):
        mock_scanner.return_value = 10

        channel1 = models.Channel.objects.create(index_videos=False, index_shorts=False, index_livestreams=False)
        channel2 = models.Channel.objects.create(index_videos=False, index_shorts=False, index_livestreams=False)
        channel3 = models.Channel.objects.create(index_videos=True)

        resp = self.client.post(self.url, {"scan_all": True, "countdown": 10, "indexing_enabled": True})

        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.url, resp.url)

        mock_scanner.assert_called_with(
            channel=channel3,
            countdown=0,
            wait_period=10,
        )


class PlaylistCreateViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission_change_channel = Permission.objects.get(codename="add_playlist")
        self.user.user_permissions.add(self.permission_change_channel)

        self.client.force_login(self.user)

        self.url = reverse('vidar:playlist-create')

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_youtube_id_in_querystring_is_copied_to_initial(self):
        resp = self.client.get(self.url)
        form = resp.context_data['form']
        self.assertIn("provider_object_id", form.initial)
        self.assertEqual("https://www.youtube.com/playlist?list=", form.initial["provider_object_id"])

        resp = self.client.get(self.url + "?youtube_id=someidhere")
        form = resp.context_data['form']
        self.assertIn("provider_object_id", form.initial)
        self.assertEqual(f"https://www.youtube.com/playlist?list=someidhere", form.initial["provider_object_id"])

    @patch('vidar.tasks.sync_playlist_data')
    def test_save_calls_task(self, mock_task):
        resp = self.client.post(self.url, {
            "provider_object_id": "https://www.youtube.com/playlist?list=someidhere",
            "videos_display_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "videos_playback_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
        })
        self.assertEqual(302, resp.status_code)
        self.assertEqual(1, models.Playlist.objects.count())
        obj = models.Playlist.objects.get()
        self.assertEqual(obj.get_absolute_url(), resp.url)
        mock_task.delay.assert_called_with(pk=obj.pk, initial_sync=True)

    @patch('vidar.tasks.sync_playlist_data')
    def test_save_errors_on_duplicate_id(self, mock_task):
        models.Playlist.objects.create(provider_object_id="someidhere")
        resp = self.client.post(self.url, {
            "provider_object_id": "https://www.youtube.com/playlist?list=someidhere",
            "videos_display_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "videos_playback_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
        })
        self.assertEqual(200, resp.status_code)
        mock_task.delay.assert_not_called()
        self.assertFormError(resp.context_data["form"], "provider_object_id", "Playlist already exists.")

    @patch('vidar.tasks.sync_playlist_data')
    def test_save_errors_on_duplicate_id_old(self, mock_task):
        models.Playlist.objects.create(provider_object_id_old="someidhere")
        resp = self.client.post(self.url, {
            "provider_object_id": "https://www.youtube.com/playlist?list=someidhere",
            "videos_display_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "videos_playback_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
        })
        self.assertEqual(200, resp.status_code)
        mock_task.delay.assert_not_called()
        self.assertFormError(resp.context_data["form"], "provider_object_id", "Playlist already exists.")

    @patch('vidar.tasks.sync_playlist_data')
    def test_save_messages_x_runtimes_per_day(self, mock_task):
        resp = self.client.post(self.url, {
            "provider_object_id": "https://www.youtube.com/playlist?list=someidhere",
            "videos_display_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "videos_playback_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "crontab": "10 4 * * *",
        })
        msgs = messages.get_messages(resp.wsgi_request)

        for msg in msgs:
            self.assertIn("1 times per day", msg.message)
            break
        else:
            self.fail("PlaylistCreateView should have told user how many scans per day were happening.")

    @patch('vidar.tasks.sync_playlist_data')
    def test_save_messages_x_runtimes_per_month(self, mock_task):
        resp = self.client.post(self.url, {
            "provider_object_id": "https://www.youtube.com/playlist?list=someidhere",
            "videos_display_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "videos_playback_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "crontab": "10 4 * * 3",
        })
        msgs = messages.get_messages(resp.wsgi_request)

        for msg in msgs:
            self.assertRegex(msg.message, r"[3,4,5] times per month")
            break
        else:
            self.fail("PlaylistCreateView should have told user how many scans per month were happening.")


class PlaylistEditViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission_change_channel = Permission.objects.get(codename="change_playlist")
        self.user.user_permissions.add(self.permission_change_channel)

        self.client.force_login(self.user)

        self.playlist = models.Playlist.objects.create(provider_object_id="test-id")

        self.url = reverse('vidar:playlist-edit', args=[self.playlist.pk])

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_regular_form_with_provider_object_id(self):

        resp = self.client.get(self.url)
        self.assertEqual(forms.PlaylistEditForm, type(resp.context_data['form']))

    def test_custom_form_without_provider_object_id(self):

        playlist = models.Playlist.objects.create()

        resp = self.client.get(reverse("vidar:playlist-edit", args=[playlist.pk]))
        self.assertEqual(forms.PlaylistManualEditForm, type(resp.context_data['form']))

    def test_save_messages_x_runtimes_per_day(self):
        resp = self.client.post(self.url, {
            "provider_object_id": "https://www.youtube.com/playlist?list=someidhere",
            "videos_display_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "videos_playback_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "crontab": "10 4 * * *",
        })
        msgs = messages.get_messages(resp.wsgi_request)

        for msg in msgs:
            self.assertIn("1 times per day", msg.message)
            break
        else:
            self.fail("PlaylistCreateView should have told user how many scans per day were happening.")

    def test_save_messages_x_runtimes_per_month(self):
        resp = self.client.post(self.url, {
            "provider_object_id": "https://www.youtube.com/playlist?list=someidhere",
            "videos_display_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "videos_playback_ordering": models.Playlist.PlaylistVideoOrderingChoices.DEFAULT,
            "crontab": "10 4 * * 3",
        })
        msgs = messages.get_messages(resp.wsgi_request)

        for msg in msgs:
            self.assertRegex(msg.message, r"[3,4,5] times per month")
            break
        else:
            self.fail("PlaylistCreateView should have told user how many scans per month were happening.")


class Update_playlists_bulk_tests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission_change_channel = Permission.objects.get(codename="change_playlist")
        self.user.user_permissions.add(self.permission_change_channel)

        self.url = reverse('vidar:playlist-bulk-update')

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_filtering_basic(self):

        p1 = models.Playlist.objects.create()
        p2 = models.Playlist.objects.create(provider_object_id="id")
        p3 = models.Playlist.objects.create()

        resp = self.client.get(self.url)

        self.assertNotIn(p1, resp.context['formset'].queryset)
        self.assertIn(p2, resp.context['formset'].queryset)
        self.assertNotIn(p3, resp.context['formset'].queryset)

    def test_filtering_channel(self):

        channel = models.Channel.objects.create()

        p1 = models.Playlist.objects.create(title="p1", )
        p2 = models.Playlist.objects.create(title="p2", provider_object_id="id")
        p3 = models.Playlist.objects.create(title="p3", provider_object_id="id2", channel=channel)

        resp = self.client.get(self.url + f"?channel={channel.pk}")

        self.assertNotIn(p1, resp.context['formset'].queryset)
        self.assertNotIn(p2, resp.context['formset'].queryset)
        self.assertIn(p3, resp.context['formset'].queryset)

    def test_submit_saves_channel_only(self):

        channel = models.Channel.objects.create()

        p1 = models.Playlist.objects.create(title="p1", )
        p2 = models.Playlist.objects.create(title="p2", provider_object_id="id")
        p3 = models.Playlist.objects.create(title="p3", provider_object_id="id2", channel=channel)

        response = self.client.get(self.url + f"?channel={channel.pk}")

        # https://stackoverflow.com/a/38479643
        # data will receive all the forms field names
        # key will be the field name (as "formx-fieldname"), value will be the string representation.
        data = {
            'csrf_token': response.context['csrf_token'],
        }

        # management form information, needed because of the formset
        management_form = response.context['formset'].management_form
        for i in 'TOTAL_FORMS', 'INITIAL_FORMS', 'MIN_NUM_FORMS', 'MAX_NUM_FORMS':
            data['%s-%s' % (management_form.prefix, i)] = management_form[i].value()

        for i in range(response.context['formset'].total_form_count()):
            current_form = response.context['formset'].forms[i]

            # retrieve all the fields
            for field_name in current_form.fields:
                value = current_form[field_name].value()
                if field_name == "crontab":
                    value = "10 5 * * *"
                data['%s-%s' % (current_form.prefix, field_name)] = value if value is not None else ''

        self.client.post(self.url + f"?channel={channel.pk}", data)

        p1.refresh_from_db()
        p2.refresh_from_db()
        p3.refresh_from_db()

        self.assertEqual("", p1.crontab)
        self.assertEqual("", p2.crontab)
        self.assertEqual("10 5 * * *", p3.crontab)

    def test_submit_saves(self):

        channel = models.Channel.objects.create()

        p1 = models.Playlist.objects.create(title="p1", )
        p2 = models.Playlist.objects.create(title="p2", provider_object_id="id")
        p3 = models.Playlist.objects.create(title="p3", provider_object_id="id2", channel=channel)

        response = self.client.get(self.url)

        # https://stackoverflow.com/a/38479643
        # data will receive all the forms field names
        # key will be the field name (as "formx-fieldname"), value will be the string representation.
        data = {
            'csrf_token': response.context['csrf_token'],
        }

        # management form information, needed because of the formset
        management_form = response.context['formset'].management_form
        for i in 'TOTAL_FORMS', 'INITIAL_FORMS', 'MIN_NUM_FORMS', 'MAX_NUM_FORMS':
            data['%s-%s' % (management_form.prefix, i)] = management_form[i].value()

        for i in range(response.context['formset'].total_form_count()):
            current_form = response.context['formset'].forms[i]

            # retrieve all the fields
            for field_name in current_form.fields:
                value = current_form[field_name].value()
                if field_name == "crontab":
                    value = f"10 {current_form.instance.pk} * * *"
                data['%s-%s' % (current_form.prefix, field_name)] = value if value is not None else ''

        self.client.post(self.url, data)

        p1.refresh_from_db()
        p2.refresh_from_db()
        p3.refresh_from_db()

        self.assertEqual("", p1.crontab)
        self.assertEqual(f"10 {p2.pk} * * *", p2.crontab)
        self.assertEqual(f"10 {p3.pk} * * *", p3.crontab)


class Update_channels_bulk_tests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission_change_channel = Permission.objects.get(codename="change_channel")
        self.user.user_permissions.add(self.permission_change_channel)

        self.url = reverse('vidar:channel-bulk-update')

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_filtering_basic(self):

        p1 = models.Channel.objects.create(status=channel_helpers.ChannelStatuses.BANNED)
        p2 = models.Channel.objects.create(provider_object_id="id")
        p3 = models.Channel.objects.create()

        resp = self.client.get(self.url)

        self.assertNotIn(p1, resp.context['formset'].queryset)
        self.assertIn(p2, resp.context['formset'].queryset)
        self.assertIn(p3, resp.context['formset'].queryset)

    def test_submit_saves(self):

        c1 = models.Channel.objects.create(name="p1", )
        c2 = models.Channel.objects.create(name="p2", provider_object_id="id")
        c3 = models.Channel.objects.create(name="p3", provider_object_id="id2")

        response = self.client.get(self.url)

        # https://stackoverflow.com/a/38479643
        # data will receive all the forms field names
        # key will be the field name (as "formx-fieldname"), value will be the string representation.
        data = {
            'csrf_token': response.context['csrf_token'],
        }

        # management form information, needed because of the formset
        management_form = response.context['formset'].management_form
        for i in 'TOTAL_FORMS', 'INITIAL_FORMS', 'MIN_NUM_FORMS', 'MAX_NUM_FORMS':
            data['%s-%s' % (management_form.prefix, i)] = management_form[i].value()

        for i in range(response.context['formset'].total_form_count()):
            current_form = response.context['formset'].forms[i]

            # retrieve all the fields
            for field_name in current_form.fields:
                value = current_form[field_name].value()
                if field_name == "scanner_crontab":
                    value = f"10 {current_form.instance.pk} * * *"
                data['%s-%s' % (current_form.prefix, field_name)] = value if value is not None else ''

        self.client.post(self.url, data)

        c1.refresh_from_db()
        c2.refresh_from_db()
        c3.refresh_from_db()

        self.assertEqual(f"10 {c1.pk} * * *", c1.scanner_crontab)
        self.assertEqual(f"10 {c2.pk} * * *", c2.scanner_crontab)
        self.assertEqual(f"10 {c3.pk} * * *", c3.scanner_crontab)


class PlaylistListViewTest(TestCase):
    # simple test, this view uses querystring so it'll fail tests under django v5.1

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission_change_channel = Permission.objects.get(codename="view_playlist")
        self.user.user_permissions.add(self.permission_change_channel)

        self.url = reverse('vidar:playlist-index')

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_default_view_shows_all(self):

        p1 = models.Playlist.objects.create(title="p1")
        p2 = models.Playlist.objects.create(title="p2")
        p3 = models.Playlist.objects.create(title="p3")

        resp = self.client.get(self.url)

        self.assertEqual(3, resp.context_data["object_list"].count())
        self.assertIn(p1, resp.context_data["object_list"])
        self.assertIn(p2, resp.context_data["object_list"])
        self.assertIn(p3, resp.context_data["object_list"])

    def test_filtered_view_shows_channel_only(self):

        c = models.Channel.objects.create()

        p1 = models.Playlist.objects.create(title="p1")
        p2 = models.Playlist.objects.create(title="p2", channel=c)
        p3 = models.Playlist.objects.create(title="p3")
        p4 = models.Playlist.objects.create(title="p4", channel=c)

        resp = self.client.get(self.url + f"?channel={c.pk}")

        self.assertEqual(2, resp.context_data["object_list"].count())
        self.assertNotIn(p1, resp.context_data["object_list"])
        self.assertIn(p2, resp.context_data["object_list"])
        self.assertNotIn(p3, resp.context_data["object_list"])
        self.assertIn(p4, resp.context_data["object_list"])

    def test_ordering_asc(self):

        c = models.Channel.objects.create()

        p1 = models.Playlist.objects.create(title="p1")
        p2 = models.Playlist.objects.create(title="p2", channel=c)
        p3 = models.Playlist.objects.create(title="p3")
        p4 = models.Playlist.objects.create(title="p4", channel=c)

        resp = self.client.get(self.url + f"?channel={c.pk}&o=title")

        qs = resp.context_data["object_list"]
        self.assertEqual(p2, qs[0])
        self.assertEqual(p4, qs[1])

    def test_ordering_desc(self):

        c = models.Channel.objects.create()

        p1 = models.Playlist.objects.create(title="p1")
        p2 = models.Playlist.objects.create(title="p2", channel=c)
        p3 = models.Playlist.objects.create(title="p3")
        p4 = models.Playlist.objects.create(title="p4", channel=c)

        resp = self.client.get(self.url + f"?channel={c.pk}&o=-title")

        qs = resp.context_data["object_list"]
        self.assertEqual(p2, qs[1])
        self.assertEqual(p4, qs[0])

    def test_ordering_invalid_field(self):

        p1 = models.Playlist.objects.create(title="p1")
        p2 = models.Playlist.objects.create(title="p2")
        p3 = models.Playlist.objects.create(title="p3")
        p4 = models.Playlist.objects.create(title="p4")

        resp = self.client.get(self.url + f"?o=invalid_field")

        qs = resp.context_data["object_list"]
        self.assertEqual(p1, qs[0])
        self.assertEqual(p2, qs[1])
        self.assertEqual(p3, qs[2])
        self.assertEqual(p4, qs[3])


class VideoDetailViewTest(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission = Permission.objects.get(codename="view_video")
        self.user.user_permissions.add(self.permission)

        self.channel = models.Channel.objects.create(name="Test Channel")
        self.video = models.Video.objects.create(title="Test Video Detail View", channel=self.channel)

        self.url = self.video.get_absolute_url()

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_metadata_artist_exists(self):
        resp = self.client.get(self.url)
        self.assertIn(f"artist: '{self.video.metadata_artist()}',".encode('utf8'), resp.content)

    def test_metadata_album_exists(self):
        resp = self.client.get(self.url)
        self.assertIn(f"album: '{self.video.metadata_album()}',".encode('utf8'), resp.content)

    def test_metadata_artist_without_channel_blank(self):
        video = models.Video.objects.create(title="Video Without Channel")
        resp = self.client.get(video.get_absolute_url())
        self.assertIn(f"artist: '{video.metadata_artist()}',".encode('utf8'), resp.content)

    def test_metadata_album_without_channel_blank(self):
        video = models.Video.objects.create(title="Video Without Channel")
        resp = self.client.get(video.get_absolute_url())
        self.assertIn(f"album: '{video.metadata_album()}',".encode('utf8'), resp.content)


class VideoRequestViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission = Permission.objects.get(codename="add_video")
        self.user.user_permissions.add(self.permission)

        self.video = models.Video.objects.create(provider_object_id="test-video-1")

        self.url = reverse('vidar:video-create')

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    @patch("vidar.tasks.download_provider_video")
    def test_ensure_id_only_works(self, mock_download):

        resp = self.client.post(reverse('vidar:video-create'), data={
            "provider_object_id": "some-id-here",
            "quality": 480,
        })

        self.assertEqual(302, resp.status_code)

        mock_download.apply_async.assert_called_once()

        self.assertEqual(1, models.Video.objects.filter(provider_object_id="some-id-here").count())
        v = models.Video.objects.get(provider_object_id="some-id-here")
        self.assertEqual(v.get_absolute_url(), resp.url)

    def test_view_with_url_to_existing_video_redirects_to_video(self):
        resp = self.client.get(self.url + "?url=" + self.video.url)
        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.video.get_absolute_url(), resp.url)

    def test_view_with_url_to_non_existing_video_fills_initial(self):
        resp = self.client.get(self.url + "?url=https://www.youtube.com/watch?v=some-id-here")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("some-id-here", resp.context_data["form"].initial['provider_object_id'])


class VideoRequestViewUnauthenticatedTests(TestCase):

    def setUp(self) -> None:
        self.group = Group.objects.create(name="Anonymous Users")
        self.group.permissions.add(
            Permission.objects.get(codename="view_video"),
            Permission.objects.get(codename="add_video")
        )

        self.video1 = models.Video.objects.create(title="Test Video 1", provider_object_id="test-video-1")
        self.video2 = models.Video.objects.create(title="Test Video 2", provider_object_id="test-video-2")

    @patch("vidar.tasks.download_provider_video")
    def test_cannot_access_video_before_requesting(self, mock_download):

        resp = self.client.get(self.video1.get_absolute_url())
        self.assertEqual(302, resp.status_code)

        mock_download.assert_not_called()

    @patch("vidar.tasks.download_provider_video")
    def test_can_access_permitted_video_after_requesting(self, mock_download):

        self.client.post(reverse('vidar:video-create'), data={
            "provider_object_id": self.video1.url,
            "quality": 480,
        })

        mock_download.assert_not_called()

        resp = self.client.get(self.video1.get_absolute_url())
        self.assertEqual(200, resp.status_code)

        resp = self.client.get(self.video2.get_absolute_url())
        self.assertEqual(302, resp.status_code)

    @patch("vidar.tasks.download_provider_video")
    def test_can_access_redirect_immediately_with_url_supplied(self, mock_download):

        url = reverse("vidar:video-create") + "?url=" + self.video1.url
        resp = self.client.get(url)

        mock_download.assert_not_called()

        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.video1.get_absolute_url(), resp.url)

        resp = self.client.get(self.video1.get_absolute_url())
        self.assertEqual(200, resp.status_code)


class VideoListViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission = Permission.objects.get(codename="access_vidar")
        self.user.user_permissions.add(self.permission)

        self.video1 = models.Video.objects.create(
            title="video 1",
            provider_object_id="test-video-1",
            date_added_to_system=date_to_aware_date('2025-01-01'),
            date_downloaded=date_to_aware_date('2025-02-10'),
            file_size=200,
        )
        self.video2 = models.Video.objects.create(
            title="video 2",
            provider_object_id="test-video-2",
            date_added_to_system=date_to_aware_date('2025-01-10'),
            date_downloaded=date_to_aware_date('2025-02-01'),
            file_size=100
        )

        self.url = reverse('vidar:index')

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_ordering(self):

        resp = self.client.get(self.url + "?o=date_added_to_system")
        queryset = resp.context_data["object_list"]
        self.assertEqual(self.video1, queryset[0])
        self.assertEqual(self.video2, queryset[1])

        resp = self.client.get(self.url + "?o=-date_added_to_system")
        queryset = resp.context_data["object_list"]
        self.assertEqual(self.video1, queryset[1])
        self.assertEqual(self.video2, queryset[0])

    def test_starred_watched_missing_archived(self):

        video_starred = models.Video.objects.create(starred=timezone.now())
        video_watched = models.Video.objects.create(watched=timezone.now(), file='test.mp4')

        resp = self.client.get(self.url + "?starred")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video_starred, queryset)

        resp = self.client.get(self.url + "?watched")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video_watched, queryset)

        resp = self.client.get(self.url + "?missing")
        queryset = resp.context_data["object_list"]
        self.assertEqual(3, queryset.count())
        self.assertIn(video_starred, queryset)
        self.assertIn(self.video1, queryset)
        self.assertIn(self.video2, queryset)

        resp = self.client.get(self.url + "?archived")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video_watched, queryset)

    def test_ordering_altering_object_count(self):

        video = models.Video.objects.create(
            title="video with file",
            last_privacy_status_check=timezone.now(),
            file='test.mp4',
            file_size=300
        )

        resp = self.client.get(self.url + "?o=last_privacy_status_check")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + "?o=file_size")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)
        self.assertNotIn(self.video1, queryset)
        self.assertNotIn(self.video2, queryset)

    def test_ordering_invalid_field(self):
        resp = self.client.get(self.url + "?o=invalid_field_name")
        self.assertEqual(200, resp.status_code)

    def test_date_filtering(self):
        video = models.Video.objects.create(
            upload_date=date_to_aware_date('2025-03-01')
        )

        resp = self.client.get(self.url + "?date=2025-02-01")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(self.video2, queryset)

        resp = self.client.get(self.url + "?upload_date=2025-03-01")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + "?date_downloaded=2025-02-10")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(self.video1, queryset)

        resp = self.client.get(self.url + "?year=2025")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + "?year=2025&month=3")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + "?year=2025&month=2")
        queryset = resp.context_data["object_list"]
        self.assertEqual(0, queryset.count())

    def test_channel_filtering(self):
        c = models.Channel.objects.create()
        video = models.Video.objects.create(channel=c)

        resp = self.client.get(self.url + f"?channel={c.pk}")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + f"?channel=none")
        queryset = resp.context_data["object_list"]
        self.assertEqual(2, queryset.count())
        self.assertIn(self.video1, queryset)
        self.assertIn(self.video2, queryset)

    def test_quality_filtering(self):
        video = models.Video.objects.create(quality=480)

        resp = self.client.get(self.url + "?quality=480")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

    def test_audio_filtering(self):
        video = models.Video.objects.create(quality=480, audio='audio.mp4')

        resp = self.client.get(self.url + "?view=audio")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)


class VideoListViewUnauthenticatedTests(TestCase):

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(reverse('vidar:index'))
        self.assertEqual(302, resp.status_code)

        self.group, _ = Group.objects.get_or_create(name="Anonymous Users")
        self.group.permissions.add(
            Permission.objects.get(codename="access_vidar"),
        )

        video1 = models.Video.objects.create(title="Test Video 1", provider_object_id="test-video-1")
        video2 = models.Video.objects.create(title="Test Video 2", provider_object_id="test-video-2")

        resp = self.client.get(reverse('vidar:index'))
        self.assertTemplateUsed(resp, 'vidar/video_list_public.html')
        self.assertEqual(200, resp.status_code)
        self.assertNotIn(video1, resp.context_data["object_list"])
        self.assertNotIn(video2, resp.context_data["object_list"])

    @patch("vidar.tasks.download_provider_video")
    def test_unauth_request_access_and_see_in_list_view(self, mock_download):
        self.group, _ = Group.objects.get_or_create(name="Anonymous Users")
        self.group.permissions.add(
            Permission.objects.get(codename="add_video"),
            Permission.objects.get(codename="access_vidar"),
        )

        video1 = models.Video.objects.create(title="Test Video 1", provider_object_id="test-video-1")
        video2 = models.Video.objects.create(title="Test Video 2", provider_object_id="test-video-2")

        url = reverse("vidar:video-create") + "?url=" + video1.url
        resp = self.client.get(url)

        self.assertEqual(302, resp.status_code)

        resp = self.client.get(reverse('vidar:index'))
        self.assertTemplateUsed(resp, 'vidar/video_list_public.html')
        self.assertEqual(200, resp.status_code)
        self.assertIn(video1, resp.context_data["object_list"])
        self.assertNotIn(video2, resp.context_data["object_list"])

        mock_download.assert_not_called()


class ChannelDetailViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission = Permission.objects.get(codename="view_channel")
        self.user.user_permissions.add(self.permission)

        self.channel = models.Channel.objects.create(name="video 1")

        self.video1 = models.Video.objects.create(
            channel=self.channel,
            title="video 1",
            provider_object_id="test-video-1",
            date_added_to_system=date_to_aware_date('2025-01-01'),
            date_downloaded=date_to_aware_date('2025-02-10'),
            file_size=200,
            duration=100,
        )
        self.video2 = models.Video.objects.create(
            channel=self.channel,
            title="video 2",
            provider_object_id="test-video-2",
            date_added_to_system=date_to_aware_date('2025-01-10'),
            date_downloaded=date_to_aware_date('2025-02-01'),
            file_size=100,
            duration=100,
        )

        self.url = self.channel.get_absolute_url()

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    @patch("vidar.tasks.download_provider_video")
    def test_request_download_without_add_video_permission_returns_nothing(self, mock_download):
        video = models.Video.objects.create(channel=self.channel)
        self.client.post(self.url, {
            f"video-{video.pk}": True,
            "quality": "1080",
        })
        mock_download.assert_not_called()

    @patch("vidar.tasks.download_provider_video")
    def test_request_download_quality_system_default_does_not_error(self, mock_download):
        self.user.user_permissions.add(Permission.objects.get(codename="add_video"))

        video = models.Video.objects.create(channel=self.channel)
        resp = self.client.post(self.url, {
            f"video-{video.pk}": True,
            "quality": "",
        })

        mock_download.delay.assert_called_with(
            pk=video.pk,
            quality="",
            task_source="Manual Download Selection",
        )

    @patch("vidar.tasks.download_provider_video")
    def test_request_download_quality_funky_value_does_not_error(self, mock_download):
        self.user.user_permissions.add(Permission.objects.get(codename="add_video"))

        video = models.Video.objects.create(channel=self.channel)
        resp = self.client.post(self.url, {
            f"video-{video.pk}": True,
            "quality": "bad-value",
        })

        mock_download.delay.assert_called_with(
            pk=video.pk,
            quality=None,
            task_source="Manual Download Selection",
        )

    def test_starred_watched_missing_archived(self):

        video_starred = models.Video.objects.create(starred=timezone.now(), channel=self.channel)
        video_watched = models.Video.objects.create(watched=timezone.now(), file='test.mp4', channel=self.channel)

        resp = self.client.get(self.url + "?starred")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video_starred, queryset)

        resp = self.client.get(self.url + "?watched")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video_watched, queryset)

        resp = self.client.get(self.url + "?missing")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(3, queryset.count())
        self.assertIn(video_starred, queryset)
        self.assertIn(self.video1, queryset)
        self.assertIn(self.video2, queryset)

        resp = self.client.get(self.url + "?archived")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video_watched, queryset)

    def test_date_filtering(self):
        video = models.Video.objects.create(
            upload_date=date_to_aware_date('2025-03-01'),
            channel=self.channel,
        )

        resp = self.client.get(self.url + "?year=2025")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + "?year=2025&month=3")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + "?year=2025&month=2")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(0, queryset.count())

    def test_quality_filtering(self):
        video = models.Video.objects.create(quality=480, channel=self.channel)

        resp = self.client.get(self.url + "?quality=480")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

    def test_ordering(self):

        resp = self.client.get(self.url + "?o=date_added_to_system")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(self.video1, queryset[0])
        self.assertEqual(self.video2, queryset[1])

        resp = self.client.get(self.url + "?o=-date_added_to_system")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(self.video1, queryset[1])
        self.assertEqual(self.video2, queryset[0])

    def test_searching(self):
        resp = self.client.get(self.url + "?q=1")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertEqual(self.video1, queryset[0])

        resp = self.client.get(self.url + "?q=title__exact:Video 1")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(0, queryset.count())

        resp = self.client.get(self.url + "?q=title__iexact:Video 2")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertEqual(self.video2, queryset[0])

        resp = self.client.get(self.url + "?q=title:2")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertEqual(self.video2, queryset[0])

        resp = self.client.get(self.url + "?q=at_max_quality:true")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(0, queryset.count())

        resp = self.client.get(self.url + "?q=at_max_quality:false&o=pk")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(2, queryset.count())
        self.assertEqual(self.video1, queryset[0])
        self.assertEqual(self.video2, queryset[1])

        resp = self.client.get(self.url + "?q=bad-field:true")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(0, queryset.count())

    def test_unwatched(self):

        models.UserPlaybackHistory.objects.create(
            user=self.user,
            video=self.video1,
            seconds=self.video1.duration-50,
        )

        resp = self.client.get(self.url + "?unwatched&o=pk")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(2, queryset.count())
        self.assertEqual(self.video1, queryset[0])
        self.assertEqual(self.video2, queryset[1])

        models.UserPlaybackHistory.objects.create(
            user=self.user,
            video=self.video1,
            seconds=self.video1.duration,
        )

        resp = self.client.get(self.url + "?unwatched")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertEqual(self.video2, queryset[0])


class Download_video_tests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission = Permission.objects.get(codename="add_video")
        self.user.user_permissions.add(self.permission)

        self.video = models.Video.objects.create(title="Video 1")

        self.url = reverse('vidar:video-download', args=[self.video.pk, 0])

        self.client.force_login(self.user)

    @patch("vidar.tasks.download_provider_video")
    def test_permission_required(self, mock_download):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)
        mock_download.delay.assert_not_called()

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)
        mock_download.delay.assert_called_once()

    @patch("vidar.tasks.download_provider_video")
    def test_quality_zero_sets_max_quality(self, mock_download):
        resp = self.client.get(reverse('vidar:video-download', args=[self.video.pk, 0]))
        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.video.get_absolute_url(), resp.url)
        mock_download.delay.assert_called_once()


class Download_video_comments_tests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission = Permission.objects.get(codename="add_comment")
        self.user.user_permissions.add(self.permission)

        self.video = models.Video.objects.create(title="Video 1")

        self.url = reverse('vidar:video-download-comments', args=[self.video.pk])

        self.client.force_login(self.user)

    @patch("vidar.tasks.download_provider_video_comments")
    def test_permission_required(self, mock_download):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        mock_download.delay.assert_not_called()

    @patch("vidar.tasks.download_provider_video_comments")
    def test_basics(self, mock_download):
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.video.get_absolute_url() + "#yt-comments", resp.url)
        mock_download.delay.assert_not_called()

        resp = self.client.post(self.url)
        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.video.get_absolute_url() + "#yt-comments", resp.url)
        mock_download.delay.assert_called_once()


class Video_convert_to_mp3_tests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission = Permission.objects.get(codename="change_video")
        self.user.user_permissions.add(self.permission)

        self.video = models.Video.objects.create(title="Video 1")

        self.url = reverse('vidar:video-convert-to-audio', args=[self.video.pk])

        self.client.force_login(self.user)

    @patch("vidar.tasks.convert_video_to_audio")
    def test_permission_required(self, mock_task):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)
        mock_task.delay.assert_not_called()

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)
        mock_task.delay.assert_called_once()

    @patch("vidar.tasks.convert_video_to_audio")
    def test_basics(self, mock_task):
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)
        self.assertEqual(self.video.get_absolute_url(), resp.url)
        mock_task.delay.assert_called_once()


class VideoManageViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission = Permission.objects.get(codename="change_video")
        self.user.user_permissions.add(self.permission)

        self.video = models.Video.objects.create(title="Video 1")

        self.url = reverse('vidar:video-manage', args=[self.video.pk])

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_manual_editor_form_fields_not_locked_does_not_allow_changed(self):
        resp = self.client.get(self.url)
        self.assertNotIn("title", resp.context_data["video_form"].fields)
        self.assertNotIn("description", resp.context_data["video_form"].fields)

    def test_manual_editor_form_fields_locked_allow_changes(self):
        video = models.Video.objects.create(title_locked=True, description_locked=False)
        resp = self.client.get(reverse('vidar:video-manage', args=[video.pk]))
        self.assertIn("title", resp.context_data["video_form"].fields)
        self.assertNotIn("description", resp.context_data["video_form"].fields)

        video = models.Video.objects.create(title_locked=False, description_locked=True)
        resp = self.client.get(reverse('vidar:video-manage', args=[video.pk]))
        self.assertNotIn("title", resp.context_data["video_form"].fields)
        self.assertIn("description", resp.context_data["video_form"].fields)

        video = models.Video.objects.create(title_locked=True, description_locked=True)
        resp = self.client.get(reverse('vidar:video-manage', args=[video.pk]))
        self.assertIn("title", resp.context_data["video_form"].fields)
        self.assertIn("description", resp.context_data["video_form"].fields)

    def test_has_file_paths_dont_exist(self):
        video = models.Video.objects.create()
        resp = self.client.get(reverse('vidar:video-manage', args=[video.pk]))
        self.assertIn("expected_video_filepath", resp.context_data)
        self.assertEqual("No file attached to video", resp.context_data["expected_video_filepath"])

        video = models.Video.objects.create(file="test.mp4", title="test video")
        resp = self.client.get(reverse('vidar:video-manage', args=[video.pk]))
        self.assertIn("expected_video_filepath", resp.context_data)
        self.assertIn("current_video_filepath_already_exists", resp.context_data)
        self.assertIn("expected_video_filepath_already_exists", resp.context_data)
        self.assertFalse(resp.context_data["expected_video_filepath_already_exists"])
        self.assertFalse(resp.context_data["current_video_filepath_already_exists"])
        self.assertEqual(f"public/{timezone.now().year}/- test video [].mp4", str(resp.context_data["expected_video_filepath"]))

    @patch("vidar.storages.vidar_storage")
    def test_has_file_paths_exist(self, mock_storage):
        mock_storage.exists.return_value = True

        video = models.Video.objects.create(file="test.mp4", title="test video")
        resp = self.client.get(reverse('vidar:video-manage', args=[video.pk]))
        self.assertIn("expected_video_filepath", resp.context_data)
        self.assertIn("current_video_filepath_already_exists", resp.context_data)
        self.assertIn("expected_video_filepath_already_exists", resp.context_data)
        self.assertTrue(resp.context_data["expected_video_filepath_already_exists"])
        self.assertTrue(resp.context_data["current_video_filepath_already_exists"])

    @patch("vidar.tasks.rename_video_files")
    def test_fixing_filepaths_without_file(self, mock_task):
        video = models.Video.objects.create()
        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"fix-filepaths": True})

        mock_task.delay.assert_not_called()

        msgs = messages.get_messages(resp.wsgi_request)
        self.assertEqual(1, len(msgs))

    @patch("vidar.tasks.rename_video_files")
    def test_fixing_filepaths_with_file(self, mock_task):

        video = models.Video.objects.create(file="test.mp4")
        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"fix-filepaths": True})

        mock_task.delay.assert_called_once()

        msgs = messages.get_messages(resp.wsgi_request)
        self.assertFalse(msgs)

    def test_expected_file_paths_are_already_correct(self):

        video = models.Video.objects.create(file="test.mp4", title="test video 1")
        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"expected-filepaths-are-correct": True})
        video.refresh_from_db()
        self.assertEqual(f"public/{timezone.now().year}/- test video 1 [].mp4", video.file.name)

    def test_release_object_lock(self):

        video = models.Video.objects.create(file="test.mp4", title="test video 1")

        celery_helpers.object_lock_acquire(obj=video, timeout=2)
        self.assertTrue(celery_helpers.is_object_locked(obj=video))

        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"release-object-lock": True})

        self.assertFalse(celery_helpers.is_object_locked(obj=video))

        msgs = messages.get_messages(resp.wsgi_request)
        self.assertEqual(1, len(msgs))
        for msg in msgs:
            self.assertIn("success", msg.message)
            break
        else:
            self.fail("No message was logged in view.")

    @patch("vidar.helpers.celery_helpers.object_lock_release")
    def test_release_object_lock_fails(self, mock_release):

        video = models.Video.objects.create(file="test.mp4", title="test video 1")

        celery_helpers.object_lock_acquire(obj=video, timeout=2)
        self.assertTrue(celery_helpers.is_object_locked(obj=video))

        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"release-object-lock": True})

        self.assertTrue(celery_helpers.is_object_locked(obj=video))

        msgs = messages.get_messages(resp.wsgi_request)
        self.assertEqual(1, len(msgs))
        for msg in msgs:
            self.assertIn("fail", msg.message)
            break
        else:
            self.fail("No message was logged in view.")

    @patch("vidar.tasks.trigger_convert_video_to_mp4")
    def test_convert_to_mp4(self, mock_task):

        video = models.Video.objects.create(file="test.mp4")
        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"convert-to-mp4": True})

        mock_task.delay.assert_called_once()

    def test_block(self):
        video = models.Video.objects.create(file="test.mp4")

        self.assertFalse(video_services.is_blocked(video.provider_object_id))

        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"block": True})

        self.assertTrue(video_services.is_blocked(video.provider_object_id))

    def test_unblock(self):
        video = models.Video.objects.create(file="test.mp4")

        self.assertFalse(video_services.is_blocked(video.provider_object_id))

        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"block": True})

        self.assertTrue(video_services.is_blocked(video.provider_object_id))

        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"unblock": True})

        self.assertFalse(video_services.is_blocked(video.provider_object_id))

    def test_extrafile(self):
        content = SimpleUploadedFile("test.mp4", b"file_content", content_type="video/mp4")

        video = models.Video.objects.create(file="test.mp4")

        self.assertFalse(video.extra_files.exists())

        url = reverse('vidar:video-manage', args=[video.pk])
        self.client.post(url, {"extrafile": True, "file": content})

        self.assertEqual(1, video.extra_files.count())

        ef = video.extra_files.get()

        url = reverse('vidar:video-manage', args=[video.pk])
        self.client.post(url, {"extrafile-delete": True, "extrafile-id": ef.pk})

        self.assertFalse(video.extra_files.exists())

    def test_manualeditor_fields(self):

        video = models.Video.objects.create(
            title="Test Video",
            description="Test Description",
            playback_speed=model_helpers.PlaybackSpeed.NORMAL,
            playback_volume=model_helpers.PlaybackVolume.FULL,
            title_locked=False,
            description_locked=False,
        )

        url = reverse('vidar:video-manage', args=[video.pk])
        self.client.post(url, {
            "save-fields": True,
            "title": "New title",
            "description": "New description",
            "playback_speed": model_helpers.PlaybackSpeed.ONE_FIFTY,
            "playback_volume": model_helpers.PlaybackVolume.FIFTY,
        })

        video.refresh_from_db()

        self.assertEqual("Test Video", video.title)
        self.assertEqual("Test Description", video.description)
        self.assertEqual(model_helpers.PlaybackSpeed.ONE_FIFTY, video.playback_speed)
        self.assertEqual(model_helpers.PlaybackVolume.FIFTY, video.playback_volume)

    def test_manualeditor_fields_locked_fields(self):

        video = models.Video.objects.create(
            title="Test Video",
            description="Test Description",
            playback_speed=model_helpers.PlaybackSpeed.NORMAL,
            playback_volume=model_helpers.PlaybackVolume.FULL,
            title_locked=True,
            description_locked=True,
        )

        url = reverse('vidar:video-manage', args=[video.pk])
        self.client.post(url, {
            "save-fields": True,
            "title": "New title",
            "description": "New description",
            "playback_speed": model_helpers.PlaybackSpeed.ONE_FIFTY,
            "playback_volume": model_helpers.PlaybackVolume.FIFTY,
        })

        video.refresh_from_db()

        self.assertEqual("New title", video.title)
        self.assertEqual("New description", video.description)
        self.assertEqual(model_helpers.PlaybackSpeed.ONE_FIFTY, video.playback_speed)
        self.assertEqual(model_helpers.PlaybackVolume.FIFTY, video.playback_volume)

    @patch("vidar.tasks.post_download_processing")
    def test_retry_processing(self, mock_task):
        video = models.Video.objects.create()
        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"retry-processing": True})
        mock_task.delay.assert_not_called()

        video = models.Video.objects.create(
            system_notes={
                "downloads": [
                    {
                        "raw_file_path": "here"
                    }
                ]
            }
        )
        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"retry-processing": True})
        mock_task.delay.assert_called_with(
            pk=video.pk,
            filepath="here",
        )
