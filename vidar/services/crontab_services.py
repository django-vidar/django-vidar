import functools
import random
import re

from django.db import models
from django.utils import timezone


DAYNAMES = 'sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'
WEEKDAYS = dict(zip(DAYNAMES, range(7)))

CrontabOptions = models.TextChoices("CrontabOptions", "HOURLY DAILY WEEKLY MONTHLY")


def weekday(name):
    """Return the position of a weekday: 0 - 7, where 0 is Sunday.

    Example:
        >>> weekday('sunday'), weekday('sun'), weekday('mon')
        (0, 0, 1)
    """
    abbreviation = name[0:3].lower()
    try:
        return WEEKDAYS[abbreviation]
    except KeyError:
        # Show original day name in exception, instead of abbr.
        raise KeyError(name)


class ParseException(Exception):
    """Raised by :class:`CrontabParser` when the input can't be parsed."""


class CrontabParser:
    """Parser for Crontab expressions.

    Any expression of the form 'groups'
    (see BNF grammar below) is accepted and expanded to a set of numbers.
    These numbers represent the units of time that the Crontab needs to
    run on:

    .. code-block:: bnf

        digit   :: '0'..'9'
        dow     :: 'a'..'z'
        number  :: digit+ | dow+
        steps   :: number
        range   :: number ( '-' number ) ?
        numspec :: '*' | range
        expr    :: numspec ( '/' steps ) ?
        groups  :: expr ( ',' expr ) *

    The parser is a general purpose one, useful for parsing hours, minutes and
    day of week expressions.  Example usage:

    .. code-block:: pycon

        >>> minutes = CrontabParser(60).parse('*/15')
        [0, 15, 30, 45]
        >>> hours = CrontabParser(24).parse('*/4')
        [0, 4, 8, 12, 16, 20]
        >>> day_of_week = CrontabParser(7).parse('*')
        [0, 1, 2, 3, 4, 5, 6]

    It can also parse day of month and month of year expressions if initialized
    with a minimum of 1.  Example usage:

    .. code-block:: pycon

        >>> days_of_month = CrontabParser(31, 1).parse('*/3')
        [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31]
        >>> months_of_year = CrontabParser(12, 1).parse('*/2')
        [1, 3, 5, 7, 9, 11]
        >>> months_of_year = CrontabParser(12, 1).parse('2-12/2')
        [2, 4, 6, 8, 10, 12]

    The maximum possible expanded value returned is found by the formula:

        :math:`max_ + min_ - 1`
    """

    ParseException = ParseException

    _range = r'(\w+?)-(\w+)'
    _steps = r'/(\w+)?'
    _star = r'\*'

    def __init__(self, max_=60, min_=0):
        self.max_ = max_
        self.min_ = min_
        self.pats = (
            (re.compile(self._range + self._steps), self._range_steps),
            (re.compile(self._range), self._expand_range),
            (re.compile(self._star + self._steps), self._star_steps),
            (re.compile('^' + self._star + '$'), self._expand_star),
        )

    def parse(self, spec):
        acc = set()
        for part in spec.split(','):
            if not part:
                raise self.ParseException('empty part')
            acc |= set(self._parse_part(part))
        return acc

    def _parse_part(self, part):
        for regex, handler in self.pats:
            m = regex.match(part)
            if m:
                return handler(m.groups())
        return self._expand_range((part,))

    def _expand_range(self, toks):
        fr = self._expand_number(toks[0])
        if len(toks) > 1:
            to = self._expand_number(toks[1])
            if to < fr:  # Wrap around max_ if necessary
                return list(range(fr, self.min_ + self.max_)) + list(range(self.min_, to + 1))
            return list(range(fr, to + 1))
        return [fr]

    def _range_steps(self, toks):
        if len(toks) != 3 or not toks[2]:
            raise self.ParseException('empty filter')
        return self._expand_range(toks[:2])[:: int(toks[2])]

    def _star_steps(self, toks):
        if not toks or not toks[0]:
            raise self.ParseException('empty filter')
        return self._expand_star()[:: int(toks[0])]

    def _expand_star(self, *args):
        return list(range(self.min_, self.max_ + self.min_))

    def _expand_number(self, s):
        if isinstance(s, str) and s[0] == '-':
            raise self.ParseException('negative numbers not supported')
        try:
            i = int(s)
        except ValueError:
            try:
                i = weekday(s)
            except KeyError:
                raise ValueError(f'Invalid weekday literal {s!r}.')

        max_val = self.min_ + self.max_ - 1
        if i > max_val:
            raise ValueError(f'Invalid end range: {i} > {max_val}.')
        if i < self.min_:
            raise ValueError(f'Invalid beginning range: {i} < {self.min_}.')

        return i


@functools.lru_cache(maxsize=100000)
def parse(crontab):
    """
    Supply a string containing a crontab '* * * * *' and returns
    five sets containing valid integers that can be used to compare with datetime.

    >>> minutes, hours, days_of_month, months_of_year, day_of_week = parse('* * * * *')
    >>> now = datetime.datetime.now()
    >>> print(now.minute in minutes)
    >>> print(now.hour in hours)
    >>> print(now.day in days_of_month)
    >>> print(now.weekday() in day_of_week)
    >>> print(now.month in months_of_year)

    """
    minutes_raw, hours_raw, day_of_month_raw, months_of_year_raw, day_of_week_raw = crontab.split(' ', 4)
    minutes = CrontabParser(60).parse(minutes_raw)
    hours = CrontabParser(24).parse(hours_raw)
    days_of_month = CrontabParser(31, 1).parse(day_of_month_raw)
    months_of_year = CrontabParser(12, 1).parse(months_of_year_raw)
    day_of_week = CrontabParser(8).parse(day_of_week_raw)

    return minutes, hours, days_of_month, months_of_year, day_of_week


def isoweekday_sunday_zero(isoweekday):
    # Take datetime isoweekday value and convert it to crontab 0-6
    return 0 if isoweekday == 7 else isoweekday


def is_active_now(crontab, now):
    minutes, hours, days_of_month, months_of_year, day_of_week = parse(crontab)

    # print(f"{minutes=}")
    # print(f"{hours=}")
    # print(f"{days_of_month=}")
    # print(f"{months_of_year=}")
    # print(f"{day_of_week=}")

    # minute calculation only works if this task runs and
    # completes within the minute it's expected to run.
    #   If it falls outside the expected minute, then the
    #   channel will not get scanned.
    if now.minute not in minutes:
        return
    if now.hour not in hours:
        return
    if now.day not in days_of_month:
        return

    # weekday and isoweekday returns variations of 1-7, crontab needs 0-6
    if isoweekday_sunday_zero(now.isoweekday()) not in day_of_week:
        return
    if now.month not in months_of_year:
        return

    return True


def calculate_schedule(crontab, check_month=False, period=10, now=None):
    if not now:
        now = timezone.localtime()
    now = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if check_month:
        now = now.replace(day=1)
    matched_timestamps = []
    start_day = now.day
    start_month = now.month
    while True:
        if is_active_now(crontab, now):
            matched_timestamps.append(now)

        now = now + timezone.timedelta(minutes=period)
        if not check_month and now.day != start_day:
            break
        elif check_month and now.month != start_month:
            break

    return matched_timestamps


def validate_crontab_values(minute=None, hour=None, day_of_week=None, day_of_month=None):
    if isinstance(minute, int):
        if not 0 <= minute <= 59:
            raise ValueError(f'crontab minute must be between 0-59, was given {minute=}')
        if minute % 10 != 0:
            raise ValueError(f'crontab minute value must be divisible by 10, was given {minute=}')
    if isinstance(hour, int) and not 0 <= hour <= 23:
        raise ValueError(f'crontab hour must be between 0-23, was given {hour=}')
    if isinstance(day_of_week, int) and not 0 <= day_of_week <= 6:
        raise ValueError(f'crontab day_of_week must be between 0-6, was given {day_of_week=}')
    if isinstance(day_of_month, int) and not 1 <= day_of_month <= 31:
        raise ValueError(f'crontab day_of_month must be between 1-31, was given {day_of_month=}')
    return True


def generate_weekly(minute=None, hour=None, day_of_week=None):
    """
    day_of_week can be 0-7 with 0 and 7 meaning sunday.
    """

    validate_crontab_values(minute=minute, hour=hour, day_of_week=day_of_week)

    minutes = list(range(0, 60, 10))
    hours = list(range(8, 20))
    month = '*'

    if isinstance(hour, list):
        hour = random.choice(hour)

    minute = minute or random.choice(minutes)
    hour = hour or random.choice(hours)
    day_of_month = '*'

    if not day_of_week:
        day_of_week = random.choice(list(range(0, 7)))

    return f"{minute} {hour} {day_of_month} {month} {day_of_week}"


def generate_monthly(minute=None, hour=None, day=None):

    if isinstance(hour, list):
        hour = random.choice(hour)

    validate_crontab_values(minute=minute, hour=hour, day_of_month=day)

    minutes = list(range(0, 60, 10))
    hours = list(range(8, 20))
    days = list(range(1, 29))  # 29 ensures it'll run even in February
    month = '*'

    minute = minute or random.choice(minutes)
    hour = hour or random.choice(hours)
    day_of_month = day or random.choice(days)
    day_of_week = '*'

    return f"{minute} {hour} {day_of_month} {month} {day_of_week}"


def generate_biyearly(minute=None, hour=None, day=None):

    validate_crontab_values(minute=minute, hour=hour, day_of_month=day)

    minutes = list(range(0, 60, 10))
    hours = list(range(8, 20))
    days = list(range(1, 29))  # 29 ensures it'll run even in February
    month = list(range(1, 13))

    if isinstance(hour, list):
        hour = random.choice(hour)

    minute = minute or random.choice(minutes)
    hour = hour or random.choice(hours)
    day_of_month = day or random.choice(days)
    month1 = random.choice(month)
    month2 = (month1 + 6) % 12 or 1
    day_of_week = '*'

    return f"{minute} {hour} {day_of_month} {month1},{month2} {day_of_week}"


def generate_yearly(minute=None, hour=None, day=None):

    validate_crontab_values(minute=minute, hour=hour)

    minutes = list(range(0, 60, 10))
    hours = list(range(8, 20))
    days = list(range(1, 29))  # 29 ensures it'll run even in February
    month = list(range(1, 13))

    if isinstance(hour, list):
        hour = random.choice(hour)

    minute = minute or random.choice(minutes)
    hour = hour or random.choice(hours)
    day_of_month = day or random.choice(days)
    month = random.choice(month)
    day_of_week = '*'

    return f"{minute} {hour} {day_of_month} {month} {day_of_week}"


def generate_daily(minute=None, hour=None):

    validate_crontab_values(minute=minute, hour=hour)

    minutes = list(range(0, 60, 10))
    hours = list(range(8, 20))

    if isinstance(hour, list):
        hour = random.choice(hour)

    minute = minute or random.choice(minutes)
    hour = hour or random.choice(hours)
    day_of_month = '*'
    month = '*'
    day_of_week = '*'

    return f"{minute} {hour} {day_of_month} {month} {day_of_week}"


def generate_selection_monthly_crontabs(length=22, minute=0, hour=5, increment_minute=10, increment_hour=1):
    vals = []

    for x in range(length):

        day_of_month = random.choice(range(1, 30))

        vals.append(f'{minute} {hour} {day_of_month} * *')

        minute += increment_minute
        if minute >= 60:
            minute = 0
            hour += increment_hour

    return vals


def generate_selection_biweekly_crontabs(length=22, minute=0, hour=13, increment_minute=10, increment_hour=1):
    vals = []

    week_of_month_options = [
        list(range(1, 14 + 1)),
        list(range(14, 30 + 1)),
    ]

    for x in range(length):

        day_of_week_selection_list = []
        for opt in week_of_month_options:
            check_day = random.choice(opt)
            day_of_week_selection_list.append(str(check_day))

        day_of_month = ','.join(day_of_week_selection_list)

        vals.append(f'{minute} {hour} {day_of_month} * *')

        minute += increment_minute
        if minute >= 60:
            minute = 0
            hour += increment_hour

    return vals


def generate_selection_daily_crontabs(length=22, minute=0, hour=16, increment_minute=10, increment_hour=1):
    vals = []

    for x in range(length):

        vals.append(f'{minute} {hour} * * *')

        minute += increment_minute
        if minute >= 60:
            minute = 0
            hour += increment_hour

    return vals
