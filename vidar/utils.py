import copy
import datetime
import logging
import random
import requests
import urllib.parse
import warnings
from collections import defaultdict

from django.db.models import When
from django.utils import timezone

from bs4 import BeautifulSoup

from vidar import app_settings


log = logging.getLogger(__name__)


def contains_one_of_many(value, matches, strip_matches=True):
    """Return True/False if value contains any ONE of the values found in matches.

    >>> value = 'Livestream on ___ date #shorts'
    >>> matches = ['#shorts', '#gameplay']
    >>> contains_one_of_many(value, matches)
    True

    """
    for skip in matches:
        if not isinstance(skip, str):
            raise ValueError("matches must contain strings only")
        if strip_matches:
            skip = skip.strip()
        if not skip:
            continue
        if skip.lower() in value.lower():
            return True


def get_playlist_id_from_url(url):
    return get_video_id_from_url(url, playlist=True)


def get_video_id_from_url(url, playlist=False):

    key = "list" if playlist else "v"

    def strip_extra_params(data):
        # Strip timestamp
        if "#" in data:
            data, _ = data.split("#", 1)

        if "?" in data:
            yid, _ = data.split("?", 1)
            return yid
        elif "&" in data:
            yid, _ = data.split("&", 1)
            return yid
        return data

    if qs := urllib.parse.urlparse(url).query:
        if d := urllib.parse.parse_qs(qs):
            if value := d.get(key):
                try:
                    return value[0]
                except IndexError:
                    pass

    if f"{key}/" in url:
        _, messy = url.split(f"{key}/", 1)
        return strip_extra_params(messy)

    if not playlist:

        if "embed/" in url:
            _, messy = url.split("embed/", 1)
            return strip_extra_params(messy)

        elif "#p/" in url:
            messy = url.split("/")
            return strip_extra_params(messy[-1])

        elif "youtu.be" in url:
            _, messy = url.split(".be/", 1)
            return strip_extra_params(messy)

    return None


def get_channel_id_from_url(url):
    qs = urllib.parse.urlparse(url)

    # /channel/U... or /channel/@Nickname
    path = qs.path

    # remainder could be U.../about strip that ending bit
    channel_id = path.replace("/channel/", "").split("/", 1)[0]

    if not channel_id or not channel_id.startswith("U") and "http" in url:
        try:
            req = requests.get(url)
            soup = BeautifulSoup(req.text, "html.parser")
            youtube_url = soup.find("link", {"rel": "canonical"})["href"]
            channel_id = get_channel_id_from_url(youtube_url)
        except (requests.exceptions.ConnectionError, KeyError, TypeError):
            warnings.warn("Failure to obtain youtube_id from youtube channel")

    return channel_id


def generate_balanced_crontab_hourly():
    """Obtains all system hourly based crontabs and then calculates the next lowest hour range to select from.
    So if 6am had 9 items and 10am had 2, it would select 10am.
    """
    crontab_counters = count_crontab_used()
    min_value = min(crontab_counters.values())
    lowest_counters = [k for k, v in crontab_counters.items() if v == min_value]
    return random.choice(lowest_counters)


def get_channel_ordering_by_next_crontab_whens():
    """
    Channel.objects.all().annotate(
        channel_next_based_order=Case(*whens, default=1000)
    ).order_by('channel_next_based_order', 'name')
    """
    from vidar.models import Channel

    now = timezone.now()

    # Rounded 5 minutes
    dt = now - timezone.timedelta(minutes=now.minute % 5, seconds=now.second, microseconds=now.microsecond)

    if dt < now:
        dt += timezone.timedelta(minutes=5)

    channel_ordering = defaultdict(list)

    for channel in Channel.objects.indexing_enabled().exclude(scanner_crontab=""):
        nrt = channel.next_runtime
        ids = int((nrt - now).total_seconds())
        channel_ordering[ids].append(channel.pk)

    whens = []
    for k, ids in channel_ordering.items():
        whens.append(When(pk__in=ids, then=k))

    return whens


def count_crontab_used():
    from vidar.models import Channel

    # Base cron pattern WITHOUT minutes. Minutes will be built up.
    # base_crons = ['6-22/12 * * *', '7-21/12 * * *']
    base_crons = app_settings.CRON_DEFAULT_SELECTION.split("|")

    minutes = {
        0: 0,
        10: 0,
        20: 0,
        30: 0,
        40: 0,
        50: 0,
    }

    counters = {}

    qs = Channel.objects.indexing_enabled()

    for hour_plus in base_crons:
        for minute in minutes.keys():
            ct = f"{minute} {hour_plus.strip()}"
            counters[ct] = qs.filter(scanner_crontab=ct).count()

    return counters


def convert_timestamp_to_datetime(timestamp, tz=datetime.timezone.utc):
    return timezone.datetime.fromtimestamp(timestamp, tz)


def get_proxy(previous_proxies: list = None, instance=None, attempt: int = None):

    user_defined_proxies = app_settings.PROXIES
    if not previous_proxies:
        previous_proxies = []

    if callable(user_defined_proxies):
        return user_defined_proxies(previous_proxies=previous_proxies, instance=instance, attempt=attempt)

    if isinstance(attempt, int):
        if attempt >= 2:
            return app_settings.PROXIES_DEFAULT

    if isinstance(user_defined_proxies, str):
        user_defined_proxies = user_defined_proxies.split(",")

    else:
        user_defined_proxies = copy.copy(user_defined_proxies)

    while user_defined_proxies:
        selected_proxy = random.choice(user_defined_proxies)
        if selected_proxy not in previous_proxies:
            return selected_proxy
        user_defined_proxies.remove(selected_proxy)

    return app_settings.PROXIES_DEFAULT


def do_new_start_end_points_overlap_existing(new_start, new_end, existing, allow_start_to_overlap_end=True):
    """Check if new start and end points overlap with existing start and ends.

    allow_start_to_overlap_end=True or False controls whether or not you can
        have a start point at a previous entries end point.
        i.e. 0-6 and 6-10. technically two sections to skip.

    """

    existing_start_points = set()
    existing_end_points = set()

    # Flatten existing points
    points = set()
    for start, end in existing:
        # +1 for range, not for calculations
        points.update(range(start, end + 1))

        existing_start_points.add(start)
        existing_end_points.add(end)

    if allow_start_to_overlap_end and new_start in existing_end_points:
        new_start += 1

    return points & set(range(new_start, new_end + 1))


def get_sponsorblock_video_data(video_id, categories=None):

    if categories is None:
        categories = ["sponsor", "selfpromo", "outro", "interaction", "poi_highlight"]

    url_extras = ""
    if categories:
        url_extras += "&category=" + "&category=".join(categories)

    url = f"https://sponsor.ajay.app/api/skipSegments?videoID={video_id}{url_extras}"
    print(url)

    resp = requests.get(url)

    if resp.status_code == 404:
        return []

    resp.raise_for_status()

    return resp.json()


def is_duration_outside_min_max(duration, minimum, maximum):
    if minimum and duration <= minimum:
        log.info(f"Not permitted due to {duration} <= {minimum}")
        return True

    if maximum and duration >= maximum:
        log.info(f"Not permitted due to {duration} >= {maximum}")
        return True


def should_halve_download_limit(duration):
    if duration_limit_split_value := app_settings.AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT:
        if duration >= duration_limit_split_value:
            log.info(f"Halving max automated downloads as {duration=} exceeds range {duration_limit_split_value=}.")
            return True


class OutputCapturer:
    """
    from functools import partial

    def print_messages(msg, **kwargs):
        # kwargs will contain at a minimum the following keys:
        #   _type: 'info', 'debug', 'error', or 'warning'
        #   any parameters passed to the partial callback initialization

        print(msg, kwargs)

    interactor_capture = partial(OutputCapturer, callback_func=print_messages)

    ytdlp_kwargs = {
        'logger': interactor_capture(),
    }

    """

    def __init__(self, callback_func=None, **kwargs):
        self.callback_func = callback_func
        self.kwargs = kwargs or {}

    def msg_received(self, msg, _type):
        if callable(self.callback_func):
            self.callback_func(msg, _type=_type, **self.kwargs)

    def info(self, msg):
        self.msg_received(msg, "info")

    def debug(self, msg):
        self.msg_received(msg, "debug")

    def error(self, msg):
        self.msg_received(msg, "error")

    def warning(self, msg):
        self.msg_received(msg, "warning")


# def get_next_best_crontab(base_crons=None):
#     if not base_crons:
#         base_crons = ['6-20/2 * * *', '7-21/2 * * *']
#
#     qs = Channel.objects.filter(enabled=True)
#
#     counters = []
#     for base in base_crons:
#         counters.append(qs.filter(scanner_crontab__endswith=base).count())
#
#     lowest_counter = min(counters)
#
#     index_with_lowest_counter = counters.index(lowest_counter)
#
#     base_cron_with_lowest_counter = base_crons[index_with_lowest_counter]
#
#     qs = qs.filter(scanner_crontab__endswith=base_cron_with_lowest_counter)
#
#     counters = {
#         0: 0,
#         10: 0,
#         20: 0,
#         30: 0,
#         40: 0,
#         50: 0,
#     }
#     for channel in qs:
#         tmp = channel.scanner_crontab.split(' ')
#         tmp = int(tmp[0])
#         counters[tmp] += 1
#
#     lowest_counter = min(counters.values())
#     assigned_minute = 0
#     for k, v in counters.items():
#         if v == lowest_counter:
#             assigned_minute = k
#             break
#
#     return f"{assigned_minute} {base_cron_with_lowest_counter}"
