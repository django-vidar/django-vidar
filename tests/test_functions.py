"""
    Not for actually testing functionality, it's for overridden
    functions and functions only used to support tests.
"""
from django.utils import timezone


def date_to_aware_date(value):
    y, m, d = value.split('-')
    y, m, d = int(y), int(m), int(d)

    return timezone.make_aware(timezone.datetime(y, m, d))


def get_cookies_user_func(video=None):
    return "user func cookies here"


def cookies_checker_user_func(video=None, attempt=0):
    return f"user func cookies checker {attempt=}"


def video_metadata_artist(video):
    return "user assigned func for artist"


def video_metadata_album(video):
    return "user assigned func for album"


def ytdlp_initializer_test(action, instance=None, **kwargs):
    return f'inside tests.test_functions.ytdlp_initializer_test {action=} {instance=} {kwargs=}'


def proxies_user_defined(**kwargs):
    return kwargs
