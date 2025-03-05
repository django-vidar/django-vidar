import datetime
import os

from django import template


register = template.Library()


@register.filter
def get_type(value):
    return type(value)


@register.filter
def get_type_name(value):
    return type(value).__name__


@register.filter
def int_to_timedelta_seconds(value):
    try:
        return datetime.timedelta(seconds=value)
    except TypeError:
        return


@register.filter
def filename(value):
    return os.path.basename(value)
