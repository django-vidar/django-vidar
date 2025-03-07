import copy
import urllib.parse
import warnings

from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator


def paginator_helper(
    context_key,
    queryset,
    requested_page=None,
    limit=None,
    params=None,
    request_params=None,
    page_url_param=getattr(settings, "PAGINATION_PAGE_PARAM", "page"),
    limit_url_param=getattr(settings, "PAGINATION_LIMIT_PARAM", "limit"),
    last_first=getattr(settings, "PAGINATION_LAST_FIRST", False),
    context_keys_prefix=None,
    **kwargs,
):
    """Builds and supports the custom pagination system this system uses.

    Examples:

        Standard Template and View usage:
            {% include 'core/pagination.html' %}

            def get_context_data(self, **kwargs):
                kwargs.update(paginator_helper(
                    context_key='images',
                    queryset=self.object.images.all(),
                    request_params=self.request.GET,
                ))
                return super().get_context_data(**kwargs)

        Custom Page and Limit Template and View usage:
            {% include 'core/pagination.html' with page_url_param='comments_page' limit_url_param='comments_limit' %}

            def get_context_data(self, **kwargs):
                kwargs.update(paginator_helper(
                    context_key='images',
                    queryset=self.object.images.all(),
                    page_url_param='comments_page',
                    limit_url_param='comments_limit',
                    request_params=self.request.GET,
                ))
                return super().get_context_data(**kwargs)

    Args:
        context_key: The objects list key passed into the template context
        queryset: The queryset to base pagination on
        requested_page: Which page to load
        limit: How many items per page
        request_params: Typically just request.GET, it fixes the url to allow
            extra GET parameters and not interfere with ?page mechanism.
        params: depreciated, use request_params.
        page_url_param: The param to be found in request_params that
            pertains to the page being loaded.
        limit_url_param: The param to be found in request_params that
            pertains to the number of items returned per page.
        last_first: Whether or not to load the first or last page
            when no page param is given.
        context_keys_prefix: A prefix string to use on all context keys in the returned dict.

    Returns:
        dict of data to be added to the templates context for pagination purposes.
    """
    if params:
        warnings.warn("params has been depreciated, use request_params", DeprecationWarning)
        request_params = params

    if not isinstance(request_params, dict):
        request_params = {}
    if page_url_param and page_url_param in request_params:
        requested_page = request_params[page_url_param]
        last_first = False
    if limit_url_param and limit_url_param in request_params:
        limit = request_params[limit_url_param]

    if last_first and requested_page is None:
        requested_page = -1
    else:
        requested_page = requested_page or 1

    default_limit = int(getattr(settings, "PAGINATION_LIMIT", 15))

    paginator = Paginator(object_list=queryset, per_page=limit or default_limit, **kwargs)

    try:
        page = paginator.page(requested_page)
    except (EmptyPage, PageNotAnInteger):
        try:
            requested_page = int(requested_page)
            if requested_page == -1 or requested_page > paginator.num_pages:
                requested_page = paginator.num_pages
            elif requested_page <= 0:
                raise ValueError
        except (ValueError, TypeError):
            requested_page = 1

        page = paginator.page(requested_page)

    base_url = ""
    if request_params and isinstance(request_params, dict):
        request_params = copy.deepcopy(request_params)
        if page_url_param in request_params:
            del request_params[page_url_param]

        if request_params:
            base_url = f"{urllib.parse.urlencode(request_params)}&"

    final_context_key = context_key
    final_paginator_key = "paginator"
    final_page_obj_key = "page_obj"
    final_pagination_base_url_key = "pagination_base_url"
    final_is_paginated_key = "is_paginated"
    if context_keys_prefix:
        final_context_key = f"{context_keys_prefix}{context_key}"
        final_paginator_key = f"{context_keys_prefix}paginator"
        final_page_obj_key = f"{context_keys_prefix}page_obj"
        final_pagination_base_url_key = f"{context_keys_prefix}pagination_base_url"
        final_is_paginated_key = f"{context_keys_prefix}is_paginated"

    return {
        final_context_key: page.object_list,
        final_paginator_key: paginator,
        final_page_obj_key: page,
        final_pagination_base_url_key: f"?{base_url}",
        final_is_paginated_key: paginator.num_pages > 1,
    }
