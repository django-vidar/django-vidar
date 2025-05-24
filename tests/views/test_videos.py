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
            starred=date_to_aware_date('2025-01-01'),
            date_downloaded=date_to_aware_date('2025-02-10'),
            file_size=200,
        )
        self.video2 = models.Video.objects.create(
            title="video 2",
            provider_object_id="test-video-2",
            starred=date_to_aware_date('2025-01-10'),
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

        resp = self.client.get(self.url + "?o=starred")
        queryset = resp.context_data["object_list"]
        self.assertEqual(self.video1, queryset[0])
        self.assertEqual(self.video2, queryset[1])

        resp = self.client.get(self.url + "?o=-starred")
        queryset = resp.context_data["object_list"]
        self.assertEqual(self.video1, queryset[1])
        self.assertEqual(self.video2, queryset[0])

    def test_starred_watched_missing_archived(self):

        video_starred = models.Video.objects.create(starred=timezone.now())
        video_watched = models.Video.objects.create(watched=timezone.now(), file='test.mp4')

        resp = self.client.get(self.url + "?starred")
        queryset = resp.context_data["object_list"]
        self.assertEqual(3, queryset.count())
        self.assertIn(video_starred, queryset)
        self.assertNotIn(video_watched, queryset)

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

        resp = self.client.get(self.url + "?date_downloaded__date=2025-02-01")
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

        resp = self.client.get(self.url + "?upload_date__year=2025")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + "?upload_date__year=2025&month=3")
        queryset = resp.context_data["object_list"]
        self.assertEqual(1, queryset.count())
        self.assertIn(video, queryset)

        resp = self.client.get(self.url + "?upload_date__year=2025&upload_date__month=2")
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

    def test_week_filtering(self):
        video1 = models.Video.objects.create(date_downloaded=date_to_aware_date("2024-04-06"))
        video2 = models.Video.objects.create(date_downloaded=date_to_aware_date("2024-04-07"))
        video3 = models.Video.objects.create(date_downloaded=date_to_aware_date("2023-04-06"))
        video4 = models.Video.objects.create(date_downloaded=date_to_aware_date("2023-04-06"))
        video5 = models.Video.objects.create(date_downloaded=date_to_aware_date("2023-04-06"))

        resp = self.client.get(self.url + "?week=14&date_downloaded__year=2024")
        queryset = resp.context_data["object_list"]
        self.assertEqual(2, queryset.count())
        self.assertIn(video1, queryset)
        self.assertIn(video2, queryset)


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


    @patch("vidar.tasks.delete_cached_file")
    @patch("vidar.tasks.write_file_to_storage")
    @patch("vidar.tasks.convert_video_to_mp4")
    @patch("vidar.tasks.download_provider_video")
    def test_convert_to_mp4(self, mock_dl, mock_convert, mock_write, mock_delete):

        video = models.Video.objects.create(file="test.mp4")
        url = reverse('vidar:video-manage', args=[video.pk])
        resp = self.client.post(url, {"convert-to-mp4": True})

        mock_dl.apply_async.assert_not_called()
        mock_convert.si.assert_called_once_with(pk=video.pk)
        mock_write.s.assert_called_once_with(pk=video.pk, field_name="file")
        mock_delete.s.assert_called_once()

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


class VideoChaptersListViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_video"),
            Permission.objects.get(codename="view_highlight")
        )

        self.client.force_login(self.user)

        self.video = models.Video.objects.create(title="Video 1")

        self.chapter1 = self.video.highlights.create(
            source=models.Highlight.Sources.CHAPTERS,
            point=1,
            note="test chapter 1"
        )
        self.chapter2 = self.video.highlights.create(
            source=models.Highlight.Sources.CHAPTERS,
            point=60,
            note="test chapter 1"
        )

        self.url = reverse('vidar:video-chapter-list', args=[self.video.pk])

    def get_chapters(self):
        return self.video.highlights.filter(source=models.Highlight.Sources.CHAPTERS).order_by('pk')

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

    def test_delete_chapter(self):
        self.client.post(self.url, {
            "chapter": self.chapter2.pk,
        })
        qs = self.get_chapters()
        self.assertEqual(1, qs.count())
        self.assertIn(self.chapter1, qs)

    def test_create_chapter_seconds(self):
        self.client.post(self.url, {
            "point": 5,
            "note": "here in tests",
        })
        qs = self.get_chapters()
        self.assertEqual(3, qs.count())

    def test_create_chapter_timestamp(self):
        self.client.post(self.url, {
            "point": "20:45",
            "note": "here in tests",
        })
        qs = self.get_chapters()
        self.assertEqual(3, qs.count())

        last = qs.last()
        self.assertEqual(1245, last.point)
        self.assertEqual("here in tests", last.note)
        self.assertEqual(self.user, last.user)


class VideoChaptersUpdateViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_video"),
            Permission.objects.get(codename="change_chapter")
        )

        self.client.force_login(self.user)

        self.video = models.Video.objects.create(title="Video 1")

        self.chapter1 = self.video.highlights.create(
            source=models.Highlight.Sources.CHAPTERS,
            point=1,
            note="test chapter 1"
        )

        self.highlight1 = self.video.highlights.create(
            source=models.Highlight.Sources.USER,
            point=1,
            note="test highlight 1"
        )

        self.url = reverse('vidar:chapters-update', args=[self.chapter1.pk])

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

    def get_chapters(self):
        return self.video.highlights.filter(source=models.Highlight.Sources.CHAPTERS).order_by('pk')

    def test_basics(self):
        resp = self.client.post(self.url, {
            "point": 10,
        })
        self.chapter1.refresh_from_db()
        self.assertEqual(10, self.chapter1.point)

    def test_cannot_update_highlights(self):
        resp = self.client.post(
            reverse('vidar:chapters-update', args=[self.highlight1.pk]),{
                "point": 10,
            }
        )
        self.assertEqual(404, resp.status_code)


class VideoHighlightsListViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_video"),
            Permission.objects.get(codename="view_highlight")
        )

        self.client.force_login(self.user)

        self.video = models.Video.objects.create(title="Video 1")

        self.highlight1 = self.video.highlights.create(
            source=models.Highlight.Sources.USER,
            point=1,
            note="test highlight 1"
        )
        self.highlight2 = self.video.highlights.create(
            source=models.Highlight.Sources.USER,
            point=60,
            note="test highlight 1"
        )

        self.url = reverse('vidar:video-highlight-list', args=[self.video.pk])

    def get_highlights(self):
        return self.video.highlights.filter(source=models.Highlight.Sources.USER).order_by('pk')

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

    def test_delete_highlight(self):
        self.client.post(self.url, {
            "highlight": self.highlight2.pk,
        })
        qs = self.get_highlights()
        self.assertEqual(1, qs.count())
        self.assertIn(self.highlight1, qs)

    def test_create_highlight_seconds(self):
        self.client.post(self.url, {
            "point": 5,
            "note": "here in tests",
        })
        qs = self.get_highlights()
        self.assertEqual(3, qs.count())

    def test_create_highlight_timestamp(self):
        self.client.post(self.url, {
            "point": "20:45",
            "note": "here in tests",
        })
        qs = self.get_highlights()
        self.assertEqual(3, qs.count())

        last = qs.last()
        self.assertEqual(1245, last.point)
        self.assertEqual("here in tests", last.note)
        self.assertEqual(self.user, last.user)


class VideoHighlightsUpdateViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_video"),
            Permission.objects.get(codename="change_highlight")
        )

        self.client.force_login(self.user)

        self.video = models.Video.objects.create(title="Video 1")

        self.highlight1 = self.video.highlights.create(
            source=models.Highlight.Sources.USER,
            point=1,
            note="test highlight 1"
        )

        self.chapter1 = self.video.highlights.create(
            source=models.Highlight.Sources.CHAPTERS,
            point=1,
            note="test chapter 1"
        )

        self.url = reverse('vidar:highlights-update', args=[self.highlight1.pk])

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

    def get_highlights(self):
        return self.video.highlights.filter(source=models.Highlight.Sources.USER).order_by('pk')

    def test_basics(self):
        resp = self.client.post(self.url, {
            "point": 10,
        })
        self.highlight1.refresh_from_db()
        self.assertEqual(10, self.highlight1.point)

    def test_cannot_update_chapters(self):
        resp = self.client.post(
            reverse('vidar:highlights-update', args=[self.chapter1.pk]),{
                "point": 10,
            }
        )
        self.assertEqual(404, resp.status_code)


class VideoWatchedViewViewTests(TestCase):

    def setUp(self):
        # Create a user and assign necessary permissions
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_video"),
        )

        self.client.force_login(self.user)

        self.video = models.Video.objects.create(title="Video 1")

        self.url = reverse('vidar:video-watched', args=[self.video.pk])

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

    def test_basics(self):

        self.client.post(self.url)

        self.video.refresh_from_db()

        self.assertTrue(self.video.watched)

    def test_video_removed_from_playlist_when_option_true(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist.playlistitem_set.create(video=self.video)

        self.client.post(self.url + f"?playlist={playlist.pk}")

        self.assertFalse(playlist.playlistitem_set.exists())

    def test_video_not_removed_from_playlist_when_option_false(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=False)
        playlist.playlistitem_set.create(video=self.video)

        self.client.post(self.url)

        self.assertTrue(playlist.playlistitem_set.exists())

    def test_video_not_removed_from_playlist_when_url_param_playlist_supplied(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist.playlistitem_set.create(video=self.video)

        playlist2 = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist2.playlistitem_set.create(video=self.video)

        self.client.post(self.url + f"?playlist={playlist.pk}")

        self.assertFalse(playlist.playlistitem_set.exists())
        self.assertTrue(playlist2.playlistitem_set.exists())

    def test_video_not_removed_from_playlist_when_url_param_playlist_not_supplied(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist.playlistitem_set.create(video=self.video)

        playlist2 = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist2.playlistitem_set.create(video=self.video)

        self.client.post(self.url)

        self.assertTrue(playlist.playlistitem_set.exists())
        self.assertTrue(playlist2.playlistitem_set.exists())


class VideoSaveWatchTimeTests(TestCase):

    def setUp(self) -> None:
        self.video = models.Video.objects.create(provider_object_id='mBuHO8p0wS0', duration=120)
        self.user = User.objects.create(username='test 1', email='email 1', is_superuser=True)
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_video"),
        )

        self.client.force_login(self.user)

        self.url = reverse('vidar:video-save-user-view-time', args=[self.video.pk])

    def test_permission_required(self):
        """Ensure users without the necessary permissions cannot access the view."""
        resp = self.client.get(self.url)
        self.assertEqual(200, resp.status_code)

        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(302, resp.status_code)

    def test_save_watch_history(self):
        self.client.post(self.url, {'current_time': '5'})
        self.assertEqual(1, self.video.user_playback_history.count())

    def test_save_watch_history_updates_existing(self):
        self.client.post(self.url, {'current_time': '5'})
        self.assertEqual(1, self.video.user_playback_history.count())

        self.assertEqual(5, models.UserPlaybackHistory.objects.get().seconds)

        self.client.post(self.url, {'current_time': '10'})
        self.assertEqual(1, self.video.user_playback_history.count())
        self.assertEqual(10, models.UserPlaybackHistory.objects.get().seconds)

    def test_save_watch_history_create_second_entry_if_time_is_lesser_than_before(self):
        dt = timezone.now() - timezone.timedelta(hours=2)
        with patch.object(timezone, 'now', return_value=dt):
            self.client.post(self.url, {'current_time': '300'})
        self.assertEqual(1, self.video.user_playback_history.count())

        self.client.post(self.url, {'current_time': '10'})
        self.assertEqual(2, self.video.user_playback_history.count())

        self.assertEqual(300, models.UserPlaybackHistory.objects.last().seconds)
        self.assertEqual(10, models.UserPlaybackHistory.objects.latest().seconds)

    def test_save_watch_history_does_not_create_entry_jumping_forward_beyond_diff_value(self):

        # Enter a history entry as if it were 2 hours ago.
        with patch.object(timezone, 'now', return_value=timezone.now() - timezone.timedelta(hours=2)):
            self.client.post(self.url, {'current_time': '300'})
        self.assertEqual(1, self.video.user_playback_history.count())

        latest = models.UserPlaybackHistory.objects.latest()
        self.assertEqual(300, latest.seconds)

        self.client.post(self.url, {'current_time': '43'})
        self.assertEqual(2, self.video.user_playback_history.count(),
                         "Two hours later and greater than 120 seconds behind the last history entry. "
                         "It should have created a second entry.")

        latest = models.UserPlaybackHistory.objects.latest()
        self.assertEqual(43, latest.seconds)

        self.client.post(self.url, {'current_time': '500'})
        self.assertEqual(2, self.video.user_playback_history.count(),
                         'Jumping into the future should not create another history entry')
        latest = models.UserPlaybackHistory.objects.latest()
        self.assertEqual(500, latest.seconds)

        self.client.post(self.url, {'current_time': '120'})
        self.assertEqual(2, self.video.user_playback_history.count(),
                         'Jumping into the past should not create another history entry within the time limit')
        latest = models.UserPlaybackHistory.objects.latest()
        self.assertEqual(120, latest.seconds)

    def test_video_removed_from_playlist_when_option_true(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist.playlistitem_set.create(video=self.video)

        self.client.post(self.url + f"?playlist={playlist.pk}", {'current_time': self.video.duration})

        self.assertFalse(playlist.playlistitem_set.exists())

    def test_video_not_removed_from_playlist_when_option_false(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=False)
        playlist.playlistitem_set.create(video=self.video)

        self.client.post(self.url, {'current_time': self.video.duration})

        self.assertTrue(playlist.playlistitem_set.exists())

    def test_video_not_removed_from_secondary_playlist_when_url_param_playlist_supplied(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist.playlistitem_set.create(video=self.video)

        playlist2 = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist2.playlistitem_set.create(video=self.video)

        self.client.post(self.url + f"?playlist={playlist.pk}", {'current_time': self.video.duration})

        self.assertFalse(playlist.playlistitem_set.exists())
        self.assertTrue(playlist2.playlistitem_set.exists())

    def test_video_not_removed_from_playlist_when_url_param_playlist_not_supplied(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist.playlistitem_set.create(video=self.video)

        playlist2 = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist2.playlistitem_set.create(video=self.video)

        self.client.post(self.url, {'current_time': self.video.duration})

        self.assertTrue(playlist.playlistitem_set.exists())
        self.assertTrue(playlist2.playlistitem_set.exists())

    def test_video_not_removed_from_playlist_when_watched_percentage_lower_than_user_selected(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist.playlistitem_set.create(video=self.video)

        self.client.post(self.url + f"?playlist={playlist.pk}", {'current_time': '60'})

        self.assertTrue(playlist.playlistitem_set.exists())

    def test_does_not_raise_exception_on_invalid_playlist_pk_value(self):
        playlist = models.Playlist.objects.create(remove_video_from_playlist_on_watched=True)
        playlist.playlistitem_set.create(video=self.video)

        try:
            self.client.post(self.url + f"?playlist=None", {'current_time': '60'})
        except:
            self.fail("here")
