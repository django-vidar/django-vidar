from django.urls import path

from exampleapp import views

app_name = "exampleapp"
urlpatterns = [
    path(
        "PublicOrLoggedInUserMixin/",
        views.TestModelPublicOrLoggedInUserMixinView.as_view(),
        name='mixin-PublicOrLoggedInUserMixin',
    ),
    path(
        "RestrictQuerySetToAuthorizedUserMixin/",
        views.TestModelRestrictQuerySetToAuthorizedUserMixinView.as_view(),
        name="mixin-RestrictQuerySetToAuthorizedUserMixin"
    ),
    path(
        "RestrictQuerySetToAuthorizedUserMixin/bad-field",
        views.TestModelRestrictQuerySetToAuthorizedUserMixinWithAlteredUserFieldView.as_view(),
        name="mixin-RestrictQuerySetToAuthorizedUserMixin-bad-field"
    ),
    path(
        "mixin-RequestBasedQuerysetFilteringMixin/",
        views.TestModelRequestBasedQuerysetFilteringMixinView.as_view(),
        name="mixin-RequestBasedQuerysetFilteringMixin",
    ),
    path(
        "mixin-RequestBasedQuerysetFilteringMixin/no-fields-selected/",
        views.TestModelRequestBasedQuerysetFilteringMixinNoFieldsSelectView.as_view(),
        name="mixin-RequestBasedQuerysetFilteringMixin-no-fields-selected",
    ),
    path(
        "mixin-RequestBasedQuerysetFilteringMixin/value-sep/",
        views.TestModelRequestBasedQuerysetFilteringMixinValueSepView.as_view(),
        name="mixin-RequestBasedQuerysetFilteringMixin-value-separator",
    ),
    path(
        "mixin-TestModelHTMXIconBooleanSwapperView/<int:pk>/",
        views.TestModelHTMXIconBooleanSwapperView.as_view(),
        name="mixin-TestModelHTMXIconBooleanSwapperView",
    ),
    path(
        "mixin-TestModelHTMXIconBooleanSwapperView/<int:pk>/raises/",
        views.TestModelHTMXIconBooleanSwapperRaisesErrorView.as_view(),
        name="mixin-TestModelHTMXIconBooleanSwapperView-raises",
    ),
]
