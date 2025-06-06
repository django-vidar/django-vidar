import logging
import warnings

from django.core.exceptions import FieldDoesNotExist, FieldError
from django.db.models import Q
from django.shortcuts import Http404, HttpResponse, get_object_or_404


log = logging.getLogger(__name__)


class PublicOrLoggedInUserMixin:
    def get_queryset(self):
        if self.request.user.is_authenticated:
            return super().get_queryset().filter(Q(user=None) | Q(user=self.request.user))
        return super().get_queryset().filter(user=None)


class UseProviderObjectIdMatchingMixin:
    def get_object(self, queryset=None):

        if not queryset:
            queryset = self.get_queryset()

        if "pk" in self.kwargs:
            return get_object_or_404(queryset, pk=self.kwargs["pk"])

        if "slug" in self.kwargs:
            return get_object_or_404(queryset, slug=self.kwargs["slug"])

        raise ValueError(f"Invalid value used in url pattern. {self.kwargs=}")


class RequestBasedCustomQuerysetFilteringMixin:

    RequestBaseFilteringDefaultFields: list = None
    RequestBaseFilteringDefaultSearchComparator: str = "__icontains"
    RequestBaseFilteringSearchValueSeparator: str = ":"
    RequestBaseFilteringQueryParameter: str = "q"

    """Adds a way to add our own shortcuts for searching.
        Let's say we want to search by channel__name__icontains easily without typing the entire string.
        Here we can map a shortcut to the long django name.
        >>> RequestBaseFilteringSearchValueMapping = {"c": "channel__name__icontains"}
        Entering the search value of c:blah will now search channels with name containing "blah"
    """
    RequestBaseFilteringSearchValueMapping = {}

    def get_default_queryset_filters(self, query, fields: list = None):
        if fields is None:
            fields = self.RequestBaseFilteringDefaultFields
        qs_wheres = Q()
        if not fields:
            warnings.warn(
                "No fields defined to search for based on request query. See RequestBaseFilteringDefaultFields"
            )
            return qs_wheres
        for field in fields:
            qs_wheres |= Q(**{f"{field}{self.RequestBaseFilteringDefaultSearchComparator}": query})
        return qs_wheres

    def apply_queryset_filtering(self, qs, fields: list = None):
        if q := self.request.GET.get(self.RequestBaseFilteringQueryParameter):
            q = q.strip()

            if not q:
                return qs

            comparator = self.RequestBaseFilteringDefaultSearchComparator

            if self.RequestBaseFilteringSearchValueSeparator in q:

                field, q = q.split(self.RequestBaseFilteringSearchValueSeparator, 1)
                field = field.strip()
                q = q.strip()

                if q.lower() in ["true", "false"]:
                    q = q.lower() == "true"
                    comparator = ""
                elif q.lower() == "none":
                    q = None
                    comparator = ""

                if mapping := self.RequestBaseFilteringSearchValueMapping:
                    field = mapping.get(field, field)

                if "__" not in field:
                    field = f"{field}{comparator}"

                try:
                    qs = qs.filter(**{field: q})
                except FieldError:
                    qs_wheres = self.get_default_queryset_filters(query=q, fields=fields)
                    if qs_wheres:
                        qs = qs.filter(qs_wheres)

            else:
                qs_wheres = self.get_default_queryset_filters(query=q, fields=fields)
                if qs_wheres:
                    qs = qs.filter(qs_wheres)

        return qs


class RequestBasedQuerysetFilteringMixin(RequestBasedCustomQuerysetFilteringMixin):
    def get_queryset(self):
        qs = super().get_queryset()
        qs = self.apply_queryset_filtering(qs)
        return qs


class RestrictQuerySetToAuthorizedUserMixin:

    queryset_restrict_user_field = "user"

    def get_queryset(self):
        return super().get_queryset().filter(**{self.queryset_restrict_user_field: self.request.user})


class HTMXIconBooleanSwapper:

    HTMX_ICON_TRUE = "fa fa-lg fa-check"
    HTMX_ICON_FALSE = "fa fa-lg fa-xmark"
    HTMX_RAISE_404 = False

    def htmx_swapper_get_object_value(self, field_name):
        return getattr(self.object, field_name, None)

    def htmx_swapper_set_object_value(self, field_name, new_value):
        setattr(self.object, field_name, new_value)

    def htmx_swapper_check_value_is_valid(self, field_name, value):
        if value is None:
            raise Http404

    def htmx_swapper_calculate_new_field_value(self, field_name, current_value):
        return not current_value

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        field_name = self.kwargs.get("field", self.request.GET.get("field"))
        if not field_name:
            if self.HTMX_RAISE_404:
                raise Http404
            return super().post(request=request, *args, **kwargs)

        # try:
        #     field_type = self.model._meta.get_field(field_name).get_internal_type()
        #     if field_type != 'BooleanField':
        #         raise Http404
        # except FieldDoesNotExist:
        #     raise Http404

        current_object_value = self.htmx_swapper_get_object_value(field_name=field_name)
        self.htmx_swapper_check_value_is_valid(field_name=field_name, value=current_object_value)
        new_value = self.htmx_swapper_calculate_new_field_value(
            field_name=field_name, current_value=current_object_value
        )
        self.htmx_swapper_set_object_value(field_name=field_name, new_value=new_value)

        self.object.save()

        new_val = getattr(self.object, field_name)

        icon = self.HTMX_ICON_TRUE if new_val else self.HTMX_ICON_FALSE

        return HttpResponse(f'<i class="{icon}"></i>')


class FieldFilteringMixin:

    FILTERING_SKIP_FIELDS: list = None
    FILTERING_ONLY_FIELDS: list = None

    def get_queryset(self):
        qs = super().get_queryset()
        filterings = {}
        excludings = {}
        for k, v in self.request.GET.items():
            k, v = k.lower(), v.lower()

            filter_type = "filter"
            if "!" in k:
                filter_type = "exclude"
                k = k.replace("!", "")

            field_name = k
            if "__" in field_name:
                field_name, _ = field_name.split("__", 1)

            if self.FILTERING_SKIP_FIELDS and field_name in self.FILTERING_SKIP_FIELDS:
                log.info(f"Field {k} skipped, not permitted for searching.")
                continue
            if self.FILTERING_ONLY_FIELDS and field_name not in self.FILTERING_ONLY_FIELDS:
                log.info(f"Field {k} not in only fields, not permitted for searching.")
                continue

            try:
                self.model._meta.get_field(field_name)
            except FieldDoesNotExist:
                log.info(f"Field {k} does not exist")
                continue

            if v in ["1", "true"]:
                v = True
            elif v in ["0", "false"]:
                v = False
            if filter_type == "filter":
                filterings[k] = v
            else:
                excludings[k] = v
        if filterings:
            qs = qs.filter(**filterings)
        if excludings:
            qs = qs.exclude(**excludings)
        return qs
