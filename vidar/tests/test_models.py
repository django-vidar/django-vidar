from django.test import TestCase
from django.utils import timezone

from vidar import models


class VideoMethodTests(TestCase):

    def test_set_and_get_latest_download_stats(self):
        video = models.Video.objects.create(title="test video")
        ts1 = timezone.now().isoformat()
        video.set_latest_download_stats(test_value=ts1)
        self.assertIn("downloads", video.system_notes)
        self.assertEqual(1, len(video.system_notes["downloads"]))

        ts2 = timezone.now().isoformat()
        video.set_latest_download_stats(test_value=ts2,)
        self.assertEqual(2, len(video.system_notes["downloads"]))

        latest_download = video.get_latest_download_stats()
        self.assertEqual({"test_value": ts2}, latest_download)

        with self.assertRaises(TypeError):
            video.set_latest_download_stats(test_value=video)

    def test_get_latest_download_stats_returns_dict_on_no_attmpt(self):
        video = models.Video.objects.create(title="test video")
        self.assertEqual({}, video.get_latest_download_stats())

    def test_append_to_latest_download_stats(self):
        video = models.Video.objects.create(title="test video")
        video.set_latest_download_stats(tester="here")

        self.assertIn("downloads", video.system_notes)
        self.assertEqual(1, len(video.system_notes["downloads"]))

        self.assertEqual({"tester": "here"}, video.get_latest_download_stats())

        video.append_to_latest_download_stats(another="test")

        self.assertEqual(1, len(video.system_notes["downloads"]))

        self.assertEqual({"tester": "here", "another": "test"}, video.get_latest_download_stats())

    def test_append_to_latest_download_stats_without_existing(self):
        video = models.Video.objects.create(title="test video")
        video.append_to_latest_download_stats(another="test")

        self.assertIn("downloads", video.system_notes)
        self.assertEqual(1, len(video.system_notes["downloads"]))

        self.assertEqual({"another": "test"}, video.get_latest_download_stats())

    def test_set_append_latest_download_stats_timezone_converts_to_isoformat_auto(self):
        video = models.Video.objects.create(title="test video")

        ts = timezone.now()

        try:
            video.set_latest_download_stats(test=ts)
        except TypeError:
            self.fail("set_latest_download_stats should have converted timezone.now to isoformat")

        latest = video.get_latest_download_stats()
        self.assertEqual(ts.isoformat(), latest["test"])

        ts2 = timezone.now()
        try:
            video.append_to_latest_download_stats(another=ts2)
        except TypeError:
            self.fail("append_to_latest_download_stats should have converted timezone.now to isoformat")

        latest = video.get_latest_download_stats()
        self.assertEqual(ts2.isoformat(), latest["another"])
