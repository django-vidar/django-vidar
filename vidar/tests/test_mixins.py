import warnings

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import FieldError
from django.shortcuts import reverse
from django.test import TestCase

from exampleapp.models import TestModel

UserModel = get_user_model()


class PublicOrLoggedInMixinTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = UserModel.objects.create(username='test')
        cls.tm1u = TestModel.objects.create(user=cls.user)
        cls.tm2u = TestModel.objects.create(user=cls.user)
        cls.tm3 = TestModel.objects.create()
        cls.tm4 = TestModel.objects.create()

    def test_unauthed_user_cannot_see_user_assigned_models(self):
        resp = self.client.get(reverse('exampleapp:mixin-PublicOrLoggedInUserMixin'))
        self.assertEqual(200, resp.status_code)
        objects = resp.context_data["object_list"]
        self.assertNotIn(self.tm1u, objects)
        self.assertNotIn(self.tm2u, objects)
        self.assertIn(self.tm3, objects)
        self.assertIn(self.tm4, objects)

    def test_authed_user_can_see_all_objects(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('exampleapp:mixin-PublicOrLoggedInUserMixin'))
        self.assertEqual(200, resp.status_code)
        objects = resp.context_data["object_list"]
        self.assertIn(self.tm1u, objects)
        self.assertIn(self.tm2u, objects)
        self.assertIn(self.tm3, objects)
        self.assertIn(self.tm4, objects)


class RestrictQuerySetToAuthorizedUserMixinTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = UserModel.objects.create(username='test')
        cls.user.user_permissions.add(Permission.objects.get(codename='view_testmodel'))

        cls.tm1u = TestModel.objects.create(user=cls.user)
        cls.tm2u = TestModel.objects.create(user=cls.user)
        cls.tm3 = TestModel.objects.create()
        cls.tm4 = TestModel.objects.create()

    def test_unauthed_redirects_due_to_permissions_required(self):
        resp = self.client.get(reverse('exampleapp:mixin-RestrictQuerySetToAuthorizedUserMixin'))
        self.assertEqual(302, resp.status_code)

    def test_authed_sees_only_theirs(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('exampleapp:mixin-RestrictQuerySetToAuthorizedUserMixin'))
        self.assertEqual(200, resp.status_code)
        objects = resp.context_data["object_list"]
        self.assertIn(self.tm1u, objects)
        self.assertIn(self.tm2u, objects)
        self.assertNotIn(self.tm3, objects)
        self.assertNotIn(self.tm4, objects)

    def test_mixin_fails_with_non_existing_field_selected(self):
        self.client.force_login(self.user)
        with self.assertRaises(FieldError):
            self.client.get(reverse('exampleapp:mixin-RestrictQuerySetToAuthorizedUserMixin-bad-field'))


class RequestBasedCustomQuerysetFilteringMixinTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tm1 = TestModel.objects.create(search_field="field data 1 tag1", boolean_field=True)
        cls.tm2 = TestModel.objects.create(search_field="field data 2 tag2", boolean_field=True)
        cls.tm3 = TestModel.objects.create(search_field="field data 3 tag2", boolean_field=False)
        cls.tm4 = TestModel.objects.create(search_field="field data 4 tag1", boolean_field=None)

    def test_basics(self):

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin')+"?q=tag2")

        self.assertEqual(200, resp.status_code)
        objects = resp.context_data["object_list"]
        self.assertNotIn(self.tm1, objects)
        self.assertIn(self.tm2, objects)
        self.assertIn(self.tm3, objects)
        self.assertNotIn(self.tm4, objects)

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin')+"?q=data 4")

        self.assertEqual(200, resp.status_code)
        objects = resp.context_data["object_list"]
        self.assertNotIn(self.tm1, objects)
        self.assertNotIn(self.tm2, objects)
        self.assertNotIn(self.tm3, objects)
        self.assertIn(self.tm4, objects)

    def test_no_field_selected_returns_all(self):
        with warnings.catch_warnings(record=True) as w:
            resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin-no-fields-selected')+"?q=tag2")
            msg = w[-1]
            self.assertEqual("No fields defined to search for based on request query. See RequestBaseFilteringDefaultFields", str(msg.message))

        self.assertEqual(200, resp.status_code)
        objects = resp.context_data["object_list"]
        self.assertIn(self.tm1, objects)
        self.assertIn(self.tm2, objects)
        self.assertIn(self.tm3, objects)
        self.assertIn(self.tm4, objects)

    def test_with_value_separator_string(self):

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin-value-separator')+"?q=search_field__contains|tag2")

        self.assertEqual(200, resp.status_code)
        objects = resp.context_data["object_list"]
        self.assertNotIn(self.tm1, objects)
        self.assertIn(self.tm2, objects)
        self.assertIn(self.tm3, objects)
        self.assertNotIn(self.tm4, objects)

    def test_with_value_separator_boolean(self):

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin-value-separator')+"?q=boolean_field|true")

        objects = resp.context_data["object_list"]
        self.assertIn(self.tm1, objects)
        self.assertIn(self.tm2, objects)
        self.assertNotIn(self.tm3, objects)
        self.assertNotIn(self.tm4, objects)

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin-value-separator')+"?q=boolean_field|false")

        objects = resp.context_data["object_list"]
        self.assertNotIn(self.tm1, objects)
        self.assertNotIn(self.tm2, objects)
        self.assertIn(self.tm3, objects)
        self.assertNotIn(self.tm4, objects)

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin-value-separator')+"?q=boolean_field|none")

        objects = resp.context_data["object_list"]
        self.assertNotIn(self.tm1, objects)
        self.assertNotIn(self.tm2, objects)
        self.assertNotIn(self.tm3, objects)
        self.assertIn(self.tm4, objects)

    def test_with_value_separator_non_existent_field(self):

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin-value-separator')+"?q=bad_field|true")

        objects = resp.context_data["object_list"]
        self.assertNotIn(self.tm1, objects)
        self.assertNotIn(self.tm2, objects)
        self.assertNotIn(self.tm3, objects)
        self.assertNotIn(self.tm4, objects)

    def test_with_empty_q(self):

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin')+"?q= ")

        objects = resp.context_data["object_list"]
        self.assertIn(self.tm1, objects)
        self.assertIn(self.tm2, objects)
        self.assertIn(self.tm3, objects)
        self.assertIn(self.tm4, objects)

        resp = self.client.get(reverse('exampleapp:mixin-RequestBasedQuerysetFilteringMixin')+"?q=")

        objects = resp.context_data["object_list"]
        self.assertIn(self.tm1, objects)
        self.assertIn(self.tm2, objects)
        self.assertIn(self.tm3, objects)
        self.assertIn(self.tm4, objects)


class HTMXIconBooleanSwapperViewMixinTests(TestCase):

    def test_basics(self):

        tm = TestModel.objects.create(boolean_field=True)
        resp = self.client.post(reverse('exampleapp:mixin-TestModelHTMXIconBooleanSwapperView', args=[tm.pk])+"?field=boolean_field")
        self.assertEqual(b'<i class="fa fa-lg fa-xmark"></i>', resp.content)
        tm.refresh_from_db()
        self.assertFalse(tm.boolean_field)

        tm = TestModel.objects.create(boolean_field=False)
        resp = self.client.post(reverse('exampleapp:mixin-TestModelHTMXIconBooleanSwapperView', args=[tm.pk])+"?field=boolean_field")
        self.assertEqual(b'<i class="fa fa-lg fa-check"></i>', resp.content)
        tm.refresh_from_db()
        self.assertTrue(tm.boolean_field)

    def test_boolean_field_as_none_raises(self):

        tm = TestModel.objects.create(boolean_field=None)
        resp = self.client.post(reverse('exampleapp:mixin-TestModelHTMXIconBooleanSwapperView', args=[tm.pk])+"?field=boolean_field")
        self.assertEqual(404, resp.status_code)
        tm.refresh_from_db()
        self.assertIsNone(tm.boolean_field)

    def test_no_field_raises_404(self):

        tm = TestModel.objects.create(boolean_field=True)
        resp = self.client.post(reverse('exampleapp:mixin-TestModelHTMXIconBooleanSwapperView', args=[tm.pk]))
        self.assertEqual(302, resp.status_code)
        self.assertEqual("TestModelURL", resp.url)

        tm = TestModel.objects.create(boolean_field=True)
        resp = self.client.post(reverse('exampleapp:mixin-TestModelHTMXIconBooleanSwapperView-raises', args=[tm.pk]))
        self.assertEqual(404, resp.status_code)
