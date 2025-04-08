import urllib.parse

from django.test import TestCase
from django.shortcuts import reverse
from django.contrib.auth import get_user_model

from exampleapp.models import TestModel

User = get_user_model()


class FieldFilteringMixinTests(TestCase):

    def setUp(self):
        self.url = reverse("exampleapp:mixin-TestModelFieldFilteringMixinView")

        self.obj1 = TestModel.objects.create(search_field="field a 1", boolean_field=True)
        self.obj2 = TestModel.objects.create(search_field="field a 2", boolean_field=False)
        self.obj3 = TestModel.objects.create(search_field="field b 1", boolean_field=False)
        self.obj4 = TestModel.objects.create(search_field="field b 2", boolean_field=True)

    def query(self, expected, params=None):
        url = self.url
        if params:
            url = f"{self.url}?{urllib.parse.urlencode(params)}"
        resp = self.client.get(url)
        self.assertEqual(expected, resp.context_data["object_list"].count())
        return resp.context_data["object_list"]

    def test_lists_all(self):
        self.query(4)

    def test_filtering_a_exact(self):
        output = self.query(1, {"search_field": "field a 1"})
        self.assertIn(self.obj1, output)

    def test_filtering_a_dunder_startswith(self):
        output = self.query(2, {"search_field__startswith": "field a"})
        self.assertIn(self.obj1, output)
        self.assertIn(self.obj2, output)

    def test_filtering_boolean_type_string(self):
        output = self.query(2, {"boolean_field": True})
        self.assertIn(self.obj1, output)
        self.assertIn(self.obj4, output)

    def test_filtering_boolean_type_number(self):
        output = self.query(2, {"boolean_field": "0"})
        self.assertIn(self.obj2, output)
        self.assertIn(self.obj3, output)

    def test_excludes(self):
        output = self.query(3, {"!search_field": "field a 1"})
        self.assertIn(self.obj2, output)
        self.assertIn(self.obj3, output)
        self.assertIn(self.obj4, output)

    def test_does_not_break_due_to_invalid_field(self):
        self.query(4, {"invalid_field": "field a 1"})


class FieldFilteringMixinWithSkipsTests(TestCase):

    def setUp(self):
        self.url = reverse("exampleapp:mixin-TestModelFieldFilteringMixinSkippedFieldsView")

        self.obj1 = TestModel.objects.create(search_field="field a 1", boolean_field=True)
        self.obj2 = TestModel.objects.create(search_field="field a 2", boolean_field=False)
        self.obj3 = TestModel.objects.create(search_field="field b 1", boolean_field=False)
        self.obj4 = TestModel.objects.create(search_field="field b 2", boolean_field=True)

    def query(self, expected, params=None):
        url = self.url
        if params:
            url = f"{self.url}?{urllib.parse.urlencode(params)}"
        resp = self.client.get(url)
        self.assertEqual(expected, resp.context_data["object_list"].count())
        return resp.context_data["object_list"]

    def test_lists_all(self):
        self.query(4)

    def test_cannot_search_skipped_field(self):
        self.query(4, {"search_field__startswith": "field a"})


class FieldFilteringMixinWithOnlyFieldsTests(TestCase):

    def setUp(self):
        self.url = reverse("exampleapp:mixin-TestModelFieldFilteringMixinOnlyFieldsView")

        self.obj1 = TestModel.objects.create(search_field="field a 1", boolean_field=True)
        self.obj2 = TestModel.objects.create(search_field="field a 2", boolean_field=False)
        self.obj3 = TestModel.objects.create(search_field="field b 1", boolean_field=False)
        self.obj4 = TestModel.objects.create(search_field="field b 2", boolean_field=True)

    def query(self, expected, params=None):
        url = self.url
        if params:
            url = f"{self.url}?{urllib.parse.urlencode(params)}"
        resp = self.client.get(url)
        self.assertEqual(expected, resp.context_data["object_list"].count())
        return resp.context_data["object_list"]

    def test_lists_all(self):
        self.query(4)

    def test_cannot_search_non_only_fields(self):
        self.query(4, {"boolean_field": True})

    def test_can_search_assigned_field(self):
        output = self.query(1, {"search_field": "field a 1"})
        self.assertIn(self.obj1, output)

    def test_can_search_assigned_field_other_not_included(self):
        output = self.query(1, {"search_field": "field a 1", "boolean_field": False})
        self.assertIn(self.obj1, output)
