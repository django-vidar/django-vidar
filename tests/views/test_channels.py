import urllib.parse
from unittest.mock import patch

import bootstrap4.exceptions
from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from vidar import models, forms
from vidar.helpers import channel_helpers

from tests.test_functions import date_to_aware_date

User = get_user_model()


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

    def test_searching_custom_filter_exact_no_match(self):
        resp = self.client.get(self.url + "?q=title__exact:Video 1")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(0, queryset.count())

    def test_searching_custom_filter_iexact_matches(self):
        resp = self.client.get(self.url + "?q=title__iexact:Video 2")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertEqual(self.video2, queryset[0])

    def test_searching_default_filtering_matches_one(self):
        resp = self.client.get(self.url + "?q=title:2")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(1, queryset.count())
        self.assertEqual(self.video2, queryset[0])

    def test_searching_custom_boolean_field(self):
        resp = self.client.get(self.url + "?q=at_max_quality:true")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(0, queryset.count())

    def test_searching_custom_boolean_field_with_ordering(self):
        resp = self.client.get(self.url + "?q=at_max_quality:false&o=pk")
        queryset = resp.context_data["channel_videos"]
        self.assertEqual(2, queryset.count())
        self.assertEqual(self.video1, queryset[0])
        self.assertEqual(self.video2, queryset[1])

    def test_searching_invalid_field_returns_zero(self):
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

