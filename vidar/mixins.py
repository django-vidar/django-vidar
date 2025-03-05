import warnings

from django.core.exceptions import FieldDoesNotExist, FieldError
from django.db.models import Q
from django.shortcuts import Http404, HttpResponse, get_object_or_404


class PublicOrLoggedInUserMixin:
    def get_queryset(self):
        if self.request.user.is_authenticated:
            return super().get_queryset().filter(Q(user=None) | Q(user=self.request.user))
        return super().get_queryset().filter(user=None)


class UseProviderObjectIdMatchingMixin:
    def get_object(self, queryset=None):

        if not queryset:
            queryset = self.get_queryset()

        if 'pk' in self.kwargs:
            return get_object_or_404(queryset, pk=self.kwargs['pk'])

        if 'slug' in self.kwargs:
            return get_object_or_404(queryset, slug=self.kwargs['slug'])

        raise ValueError(f'Invalid value used in url pattern. {self.kwargs=}')


class RequestBasedCustomQuerysetFilteringMixin:

    RequestBaseFilteringDefaultFields: list = None
    RequestBaseFilteringDefaultSearchComparator: str = '__icontains'
    RequestBaseFilteringSearchValueSeparator: str = ":"
    RequestBaseFilteringQueryParameter: str = 'q'

    def get_default_queryset_filters(self, query, fields: list=None):
        if fields is None:
            fields = self.RequestBaseFilteringDefaultFields
        qs_wheres = Q()
        if not fields:
            warnings.warn('No fields defined to search for based on request query. '
                          'See RequestBaseFilteringDefaultFields')
            return qs_wheres
        for field in fields:
            qs_wheres |= Q(**{f"{field}{self.RequestBaseFilteringDefaultSearchComparator}": query})
        return qs_wheres

    def apply_queryset_filtering(self, qs, fields: list=None):
        if q := self.request.GET.get(self.RequestBaseFilteringQueryParameter):
            q = q.strip()

            if not q:
                return qs

            if self.RequestBaseFilteringSearchValueSeparator in q:

                field, q = q.split(self.RequestBaseFilteringSearchValueSeparator, 1)
                field = field.strip()
                q = q.strip()

                if q.lower() in ['true', 'false']:
                    q = q.lower() == 'true'
                elif q.lower() == 'none':
                    q = None

                if '__' not in field:
                    field = f"{field}{self.RequestBaseFilteringDefaultSearchComparator}"

                try:
                    qs = qs.filter(
                        **{field: q}
                    )
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

    queryset_restrict_user_field = 'user'

    def get_queryset(self):
        return super().get_queryset().filter(**{self.queryset_restrict_user_field: self.request.user})


class HTMXIconBooleanSwapper:

    HTMX_ICON_TRUE = 'fa fa-lg fa-check'
    HTMX_ICON_FALSE = 'fa fa-lg fa-xmark'
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
        field_name = self.kwargs.get('field', self.request.GET.get('field'))
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
        self.htmx_swapper_check_value_is_valid(
            field_name=field_name,
            value=current_object_value
        )
        new_value = self.htmx_swapper_calculate_new_field_value(
            field_name=field_name,
            current_value=current_object_value
        )
        self.htmx_swapper_set_object_value(field_name=field_name, new_value=new_value)

        self.object.save()

        new_val = getattr(self.object, field_name)

        icon = self.HTMX_ICON_TRUE if new_val else self.HTMX_ICON_FALSE

        return HttpResponse(f'<i class="{icon}"></i>')


class FieldFilteringMixin:

    FILTERING_SKIP_FIELDS: list = None

    def get_queryset(self):
        qs = super().get_queryset()
        for k, v in self.request.GET.items():
            if self.FILTERING_SKIP_FIELDS and k in self.FILTERING_SKIP_FIELDS:
                continue
            try:
                field_data = self.model._meta.get_field(k)
                if v in ['1', 'True']:
                    v = True
                elif v in ['0', 'False']:
                    v = False
                print(field_data.attname, v)
                qs = qs.filter(**{field_data.attname: v})
            except FieldDoesNotExist:
                print(f"Field {k} does not exist")
        return qs
