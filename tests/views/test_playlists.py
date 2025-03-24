from unittest.mock import patch, call

from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from vidar import models, forms

User = get_user_model()


class PlaylistDetailViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_playlist"),
        )

        self.client.force_login(self.user)

        self.playlist = models.Playlist.objects.create(
            title="Playlist 1",
            provider_object_id="test-id",
        )

        self.video1 = self.playlist.videos.create(title="test video 1")
        self.video2 = self.playlist.videos.create(title="test video 2")

        self.url = self.playlist.get_absolute_url()

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

    def test_convert_to_custom(self):
        self.client.post(self.url, {
            "convert-to-custom": True
        })

        self.playlist.refresh_from_db()

        self.assertIn(f"Old YouTube ID: test-id", self.playlist.description)
        self.assertEqual("test-id", self.playlist.provider_object_id_old)
        self.assertEqual("", self.playlist.provider_object_id)

        for item in self.playlist.playlistitem_set.all():
            self.assertTrue(item.manually_added)

    @patch("vidar.tasks.download_provider_video_comments")
    def test_download_comments(self, mock_task):
        self.client.post(self.url, {
            "download-video-comments": True
        })

        mock_task.apply_async.assert_has_calls([
            call(args=[self.video1.pk, False], countdown=67),
            call(args=[self.video2.pk, False], countdown=0),
        ], any_order=True)

    @patch("vidar.tasks.download_provider_video_comments")
    def test_download_comments_all_comments(self, mock_task):
        self.client.post(self.url, {
            "download-video-comments": True,
            "download_all_comments": True,
        })

        mock_task.apply_async.assert_has_calls([
            call(args=[self.video1.pk, True], countdown=67),
            call(args=[self.video2.pk, True], countdown=0),
        ], any_order=True)


class PlaylistDeleteViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user.user_permissions.add(
            Permission.objects.get(codename="delete_playlist"),
        )

        self.client.force_login(self.user)

        self.playlist = models.Playlist.objects.create(
            title="Playlist 1",
            provider_object_id="test-id",
        )

        self.video1 = self.playlist.videos.create(title="test video 1")
        self.video2 = self.playlist.videos.create(title="test video 2")

        self.url = reverse('vidar:playlist-delete', args=[self.playlist.pk])

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

    @patch("vidar.services.playlist_services.delete_playlist_videos")
    def test_keep_videos(self, mock_func):
        mock_func.return_value = 5
        self.client.post(self.url)
        mock_func.assert_not_called()

    @patch("vidar.services.playlist_services.delete_playlist_videos")
    def test_videos_too(self, mock_func):
        mock_func.return_value = 5
        self.client.post(self.url, {
            "delete_videos": True,
        })
        mock_func.assert_called_once()


class PlaylistScanViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user.user_permissions.add(
            Permission.objects.get(codename="delete_playlist"),
        )

        self.client.force_login(self.user)

    @patch("vidar.tasks.sync_playlist_data")
    def test_delete_with_provider_object_id(self, mock_task):

        playlist = models.Playlist.objects.create(provider_object_id="test-id")

        self.client.get(reverse('vidar:playlist-scan', args=[playlist.pk]))
        mock_task.delay.assert_called_once()

    @patch("vidar.tasks.sync_playlist_data")
    def test_delete_without_provider_object_id(self, mock_task):

        playlist = models.Playlist.objects.create()

        self.client.get(reverse('vidar:playlist-scan', args=[playlist.pk]))
        mock_task.delay.assert_not_called()


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


class PlaylistWatchLaterViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.permission_change_channel = Permission.objects.get(codename="view_playlist")
        self.user.user_permissions.add(self.permission_change_channel)

        self.url = reverse('vidar:watch-later')

        self.client.force_login(self.user)

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

    def test_basics(self):
        resp = self.client.get(self.url)
        wl = models.Playlist.get_user_watch_later(user=self.user)
        self.assertEqual(wl, resp.context_data["object"])
