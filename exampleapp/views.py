from django.contrib.auth.mixins import PermissionRequiredMixin
from django.views.generic import DetailView, ListView, UpdateView

from exampleapp.models import TestModel
from vidar.mixins import (
    FieldFilteringMixin,
    HTMXIconBooleanSwapper,
    PublicOrLoggedInUserMixin,
    RequestBasedQuerysetFilteringMixin,
    RestrictQuerySetToAuthorizedUserMixin,
    WatchLaterContextDataMixin,
)


class TestModelPublicOrLoggedInUserMixinView(PublicOrLoggedInUserMixin, ListView):
    model = TestModel


class TestModelRestrictQuerySetToAuthorizedUserMixinView(PermissionRequiredMixin, RestrictQuerySetToAuthorizedUserMixin, ListView):
    model = TestModel
    permission_required = ['exampleapp.view_testmodel']


class TestModelRestrictQuerySetToAuthorizedUserMixinWithAlteredUserFieldView(PermissionRequiredMixin, RestrictQuerySetToAuthorizedUserMixin, ListView):
    model = TestModel
    permission_required = ['exampleapp.view_testmodel']
    queryset_restrict_user_field = "bad-field"


class TestModelRequestBasedQuerysetFilteringMixinView(RequestBasedQuerysetFilteringMixin, ListView):
    model = TestModel
    RequestBaseFilteringDefaultFields = ['search_field']


class TestModelRequestBasedQuerysetFilteringMixinNoFieldsSelectView(RequestBasedQuerysetFilteringMixin, ListView):
    model = TestModel


class TestModelRequestBasedQuerysetFilteringMixinValueSepView(RequestBasedQuerysetFilteringMixin, ListView):
    model = TestModel
    RequestBaseFilteringDefaultFields = ['search_field']
    RequestBaseFilteringSearchValueSeparator = '|'


class TestModelHTMXIconBooleanSwapperView(HTMXIconBooleanSwapper, UpdateView):
    model = TestModel
    fields = '__all__'


class TestModelHTMXIconBooleanSwapperRaisesErrorView(HTMXIconBooleanSwapper, UpdateView):
    model = TestModel
    HTMX_RAISE_404 = True
    fields = '__all__'


class TestModelFieldFilteringMixinView(FieldFilteringMixin, ListView):
    model = TestModel


class TestModelFieldFilteringMixinSkippedFieldsView(FieldFilteringMixin, ListView):
    model = TestModel
    FILTERING_SKIP_FIELDS = ["search_field"]


class TestModelFieldFilteringMixinOnlyFieldsView(FieldFilteringMixin, ListView):
    model = TestModel
    FILTERING_ONLY_FIELDS = ["search_field"]


class TestViewWatchLaterContextDataMixin(WatchLaterContextDataMixin, ListView):
    model = TestModel
