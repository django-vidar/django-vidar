import urllib.parse
from unittest.mock import patch

import bootstrap4.exceptions
from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from vidar import models

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

