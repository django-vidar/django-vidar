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


@register.filter
def smooth_timedelta(
    timedeltaobj,
    str_joiner=" ",
    general_joiner=" ",
    day_str="day",
    days_str="days",
    hour_str="hour",
    hours_str="hours",
    minute_str="minute",
    minutes_str="minutes",
    second_str="second",
    seconds_str="seconds",
):
    """Convert a datetime.timedelta object into Days, Hours, Minutes, Seconds."""
    secs = timedeltaobj.total_seconds()

    is_negative = secs < 0
    if is_negative:
        secs = secs * -1

    def pluralize(value, singular, plural):
        return singular if value == 1 else plural

    timetot = []
    if secs > 86400:  # 60sec * 60min * 24hrs
        days = secs // 86400
        timetot.append("{}{}{}".format(int(days), str_joiner, pluralize(days, day_str, days_str)))
        secs = secs - days * 86400

    if secs > 3600:
        hrs = secs // 3600
        timetot.append("{}{}{}".format(int(hrs), str_joiner, pluralize(hrs, hour_str, hours_str)))
        secs = secs - hrs * 3600

    if secs > 60:
        mins = secs // 60
        timetot.append("{}{}{}".format(int(mins), str_joiner, pluralize(mins, minute_str, minutes_str)))
        secs = secs - mins * 60

    if secs > 0:
        timetot.append("{}{}{}".format(int(secs), str_joiner, pluralize(secs, second_str, seconds_str)))

    # if is_negative:
    #     timetot += " ago"

    return general_joiner.join(timetot)
