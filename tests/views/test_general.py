import urllib.parse
from unittest.mock import patch, call

from django.test import TestCase
from django.shortcuts import reverse
from django.contrib import messages
from django.contrib.auth import get_user_model

from vidar import models

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
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} (\d+){1,2} \*$')

        resp = self.client.get(self.make_url(type="yearly", hours=[2,3]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) ([2,3]) (\d+){1,2} (\d+){1,2} \*$')

    def test_biyearly(self):
        resp = self.client.get(self.make_url(type="biyearly"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} (\d+){1,2},(\d+){,2} \*$')

        resp = self.client.get(self.make_url(type="biyearly", hours=[2,3]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) ([2,3]) (\d+){1,2} (\d+){1,2},(\d+){,2} \*$')

    def test_monthly(self):
        resp = self.client.get(self.make_url(type="monthly"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} \* \*$')

        resp = self.client.get(self.make_url(type="monthly", hours=[2,3]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) ([2,3]) (\d+){1,2} \* \*$')

    def test_monthly_with_channel(self):
        channel = models.Channel.objects.create()
        resp = self.client.get(self.make_url(type="monthly", channel=channel.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} \* \*$')

        channel.videos.create(upload_date=date_to_aware_date('2025-01-03'))
        channel.videos.create(upload_date=date_to_aware_date('2025-02-03'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-03'))

        resp = self.client.get(self.make_url(type="monthly", channel=channel.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} 3 \* \*$')

        channel.videos.create(upload_date=date_to_aware_date('2025-03-06'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-15'))

        resp = self.client.get(self.make_url(type="monthly", channel=channel.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} 3 \* \*$')

    def test_monthly_with_playlist(self):
        playlist = models.Playlist.objects.create()
        resp = self.client.get(self.make_url(type="monthly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} (\d+){1,2} \* \*$')

        playlist.videos.create(upload_date=date_to_aware_date('2025-01-03'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-02-03'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-03'))

        resp = self.client.get(self.make_url(type="monthly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} 3 \* \*$')

        playlist.videos.create(upload_date=date_to_aware_date('2025-03-06'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-15'))

        resp = self.client.get(self.make_url(type="monthly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} 3 \* \*$')

    def test_weekly(self):
        resp = self.client.get(self.make_url(type="weekly"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* [0-7]$')

        resp = self.client.get(self.make_url(type="weekly", hours=[2,3]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) ([2,3]) \* \* [0-7]$')

        resp = self.client.get(self.make_url(type="weekly", hours=[2,3], day_of_week=[4,5]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) ([2,3]) \* \* [4,5]$')

        resp = self.client.get(self.make_url(type="weekly", day_of_week=[4,5]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* [4,5]$')

        with self.assertRaises(ValueError):
            self.client.get(self.make_url(type="weekly", day_of_week=9))

    def test_weekly_with_channel(self):
        channel = models.Channel.objects.create()
        resp = self.client.get(self.make_url(type="weekly", channel=channel.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* [0-7]$')

        # videos released on mondays should scan on tuesday
        channel.videos.create(upload_date=date_to_aware_date('2025-03-03'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-10'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-17'))

        resp = self.client.get(self.make_url(type="weekly", channel=channel.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* 2$')

        channel.videos.create(upload_date=date_to_aware_date('2025-03-06'))
        channel.videos.create(upload_date=date_to_aware_date('2025-03-15'))

        # Most common upload date is still monday, scan on tuesdays still.
        resp = self.client.get(self.make_url(type="weekly", channel=channel.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* 2$')

    def test_weekly_with_playlist(self):
        playlist = models.Playlist.objects.create()
        resp = self.client.get(self.make_url(type="weekly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* [0-7]$')

        # videos released on mondays should scan on tuesday
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-03'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-10'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-17'))

        resp = self.client.get(self.make_url(type="weekly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* 2$')

        playlist.videos.create(upload_date=date_to_aware_date('2025-03-06'))
        playlist.videos.create(upload_date=date_to_aware_date('2025-03-15'))

        # Most common upload date is still monday, scan on tuesdays still.
        resp = self.client.get(self.make_url(type="weekly", playlist=playlist.pk))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* 2$')

    def test_daily(self):
        resp = self.client.get(self.make_url())
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* \*$')

        resp = self.client.get(self.make_url(hours=[2,3]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) ([2,3]) \* \* \*$')

        resp = self.client.get(self.make_url(type="daily"))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* \*$')

        resp = self.client.get(self.make_url(type="daily", hours=[2,3]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) ([2,3]) \* \* \*$')

    def test_every_other_day(self):
        resp = self.client.get(self.make_url(type="every_other_day"))
        self.assertEqual(200, resp.status_code)
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (\d+){1,2} \* \* (0-7\/2|1-7\/2)$')

        resp = self.client.get(self.make_url(type="every_other_day", hours=[2,3]))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) ([2,3]) \* \* (0-7\/2|1-7\/2)$')

    def test_hourly(self):
        resp = self.client.get(self.make_url(type="hourly"))
        self.assertRegex(resp.content, br'^(0|10|20|30|40|50) (7-21\/4|6-22\/4) \* \* \*$')

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
            self.assertRegex(resp.content, br'^(0|10|20|30|40|50) 6-22/4 \* \* \*$')


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

