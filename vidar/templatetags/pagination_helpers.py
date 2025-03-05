from django import template


register = template.Library()


@register.simple_tag
def proper_pagination(
    paginator, current_page, neighbors=4, include_first=None, include_last=None, include_separator=False
):
    """Returns a list containing a range of numbers to be used for pagination.

    Args:
        paginator: The paginator object to work on.
        current_page: The current page we're on
        neighbors: How many page numbers before and after
            the current page do we show? Default 5
        include_first: If we're to a point where the first
            couple of pages are no longer shown (see neighbors),
            how many of the first pages do we want to re-include.
            i.e.: 1, 2, 3, 56, 57, 58
        include_last: If we're at a point where the last couple of
            pages are no longer shown (see neighbors), how many
            of the last few pages do we want to re-include?
            i.e.: 56, 57, 58, 71, 72, 73
        include_separator: If you use include_first, or include_last.
            you can supply a separator between the first and last
            items added to an existing page list
            i.e.: 1, 2, 3, ..., 56, 57, 58, ..., 71, 72, 73

    Examples:

        For this example lets assume
            - Paginator has 72 pages
            - We are currently on page 14
            - We want 3 neighbor digits showing around the current item
            - We want the first 2 page numbers showing at all times
            - We want the last 2 page numbers showing at all times
            - Separate the first and last page numbers from the current numbers(with neighbors) by ...

        {% proper_paginate paginator page_obj.number 3 2 2 "..." as pagination_results %}

        Will result in:

            1, 2, ..., 11, 12, 13, 14, 15, 16, 17, ..., 71, 72

    """
    if paginator.num_pages > 2 * neighbors:
        start_index = max(1, current_page - neighbors)
        end_index = min(paginator.num_pages, current_page + neighbors)
        if end_index < start_index + 2 * neighbors:
            end_index = start_index + 2 * neighbors
        elif start_index > end_index - 2 * neighbors:
            start_index = end_index - 2 * neighbors
        if start_index < 1:
            end_index -= start_index
            start_index = 1
        elif end_index > paginator.num_pages:
            start_index -= end_index - paginator.num_pages
            end_index = paginator.num_pages
        page_list = [f for f in range(start_index, end_index + 1)]

        prepend_pages = []
        append_pages = []

        if include_first:
            for x in range(1, include_first + 1):
                if x not in page_list:
                    prepend_pages.append(x)

        if include_last:
            for x in range(paginator.num_pages - include_last + 1, paginator.num_pages + 1):
                if x not in append_pages and x not in prepend_pages and x not in page_list:
                    append_pages.append(x)

        # Only include separator if we have pages and are not
        # too close to the start or end of the page range.
        if include_separator:
            if current_page - 1 > (neighbors + include_first):
                prepend_pages.append(include_separator)

            if paginator.num_pages - (neighbors + include_last) > current_page:
                append_pages.insert(0, include_separator)

        return prepend_pages + page_list[: (2 * neighbors + 1)] + append_pages

    return paginator.page_range
