import urllib.parse
from unittest.mock import patch, call

import bootstrap4.exceptions
from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group

from vidar import models, forms
from vidar.helpers import channel_helpers

User = get_user_model()


def date_to_aware_date(value):
    y, m, d = value.split('-')
    y, m, d = int(y), int(m), int(d)

    return timezone.make_aware(timezone.datetime(y, m, d))


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

