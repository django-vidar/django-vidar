import statistics

from django.db.models.functions import ExtractDay, ExtractWeek, ExtractWeekDay


def most_common_date_weekday(queryset, date_field="upload_date"):
    """Return Sunday=0 through Saturday=6.

    - 1 is needed to get 0-6 instead of 1-7

    multimode returns multiple if multiple days of the week return as most common,
        such as 1, 1, 2, 2
        Using -1 to get last item as it'll be later in the week.
    """

    weekdays = queryset.annotate(weekday=ExtractWeekDay(date_field)).values_list("weekday", flat=True)
    mode = statistics.multimode(weekdays)
    return max(mode) - 1


def most_common_date_day_of_month(queryset, date_field="upload_date"):

    days = queryset.annotate(day=ExtractDay(date_field)).values_list("day", flat=True)
    most_common_days = statistics.multimode(days)
    most_common_day = max(most_common_days)

    if most_common_day == 31:
        return 30

    return most_common_day


def most_common_date_week_of_year(queryset, date_field="upload_date"):
    weeks = queryset.annotate(week=ExtractWeek(date_field)).values_list("week", flat=True)
    mode = statistics.multimode(weeks)
    return max(mode)
