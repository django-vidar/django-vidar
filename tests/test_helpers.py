import datetime
import io

from django.test import TestCase

from vidar import models
from vidar.helpers import json_safe_kwargs, celery_helpers


class GeneralHelpersTests(TestCase):

    def test_json_safe_kwargs(self):
        dt = datetime.datetime.now()
        kwargs = {
            "progress_hooks": [],
            "timezone": dt,
            "io": io.StringIO("test io"),
            "untouched": "here",
        }

        output = json_safe_kwargs(kwargs)

        self.assertNotIn("progress_hooks", output)

        self.assertIn("timezone", output)
        self.assertEqual(str, type(output["timezone"]))
        self.assertEqual(dt.isoformat(), output["timezone"])

        self.assertIn("io", output)
        self.assertEqual(str, type(output["io"]))
        self.assertEqual("test io", output["io"])

        self.assertIn("untouched", output)
        self.assertEqual(str, type(output["untouched"]))
        self.assertEqual("here", output["untouched"])


class CeleryHelpersTests(TestCase):

    def test_object_locks(self):
        video = models.Video.objects.create()
        self.assertFalse(celery_helpers.is_object_locked(video))

        celery_helpers.object_lock_acquire(video)
        self.assertTrue(celery_helpers.is_object_locked(video))

        celery_helpers.object_lock_release(video)
        self.assertFalse(celery_helpers.is_object_locked(video))
