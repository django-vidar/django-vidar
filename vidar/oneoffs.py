# flake8:noqa
import copy
import csv
import glob
import json
import logging
import math
import os
import pathlib
from collections import defaultdict
from pprint import pprint

from django.utils import timezone


try:
    import icalendar
except ImportError:
    icalendar = None

import yt_dlp

from vidar import app_settings, helpers, renamers, utils
from vidar.exceptions import FileStorageBackendHasNoMoveError
from vidar.helpers import file_helpers, video_helpers
from vidar.models import Channel, DurationSkip, Video, vidar_storage
from vidar.services import crontab_services, schema_services, video_services


log = logging.getLogger(__name__)


def find_existing_files_with_missing_video_entries():

    current_files = []
    for file in glob.glob(f"{app_settings.MEDIA_ROOT}/**/*.*", recursive=True):
        if not file.endswith(('.mp4', '.webm', '.mkv')):
            continue
        current_files.append(file.replace('/', ''))

    for video in Video.objects.archived():
        current_files.remove(video.file.path)

    for x in current_files:
        print(x)

    return current_files


def find_existing_videos_without_local_file():

    missing = []
    for video in Video.objects.archived():

        if not video.file.storage.exists(video.file.name):
            missing.append(video)
            print(video)

    return missing


def sponsorblocks_testing():
    ydl_opts = {
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                  "best[height<=720][ext=mp4]",
        "outtmpl": "%(id)s.%(ext)s",
        'quiet': False,
        'keepvideo': True,
        # 'progress_hooks': [],
        # 'quiet': True,
        # "ratelimit": 10 * 1024,
        'postprocessors': [
            {
                'key': 'SponsorBlock',
                'categories': ['sponsor']
            },
            {
                'key': 'ModifyChapters',
                'remove_sponsor_segments': ['sponsor']
            }
        ]
    }

    sandwich_bread_with_sponsorblock = "https://www.youtube.com/watch?v=i3sP2jwG9jc"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(sandwich_bread_with_sponsorblock, download=True)


def download_progress_hooks_testing():
    v = Video.objects.get(pk=327)

    def progress_Check(d):
        yid = d['info_dict']['id']
        print('#### inside ####', d['status'], d.get('downloaded_bytes'), d.get('total_bytes_estimate'), d.get('eta'), d.get('speed'), yid)

    try:
        os.unlink('jT1tdfz6HYI.mp4')
    except FileNotFoundError:
        pass

    ydl_opts = {
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                  "best[height<=720][ext=mp4]",
        "outtmpl": "%(id)s.%(ext)s",
        "ratelimit": 800 * 1024,
        'progress_hooks': [progress_Check],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(v.url, download=True)


def set_channel_videos_inserted_to_upload_date(channel):

    if not isinstance(channel, Channel):
        channel = Channel.objects.get(pk=channel)

    for video in channel.videos.exclude(upload_date__isnull=True):
        video.inserted = video.inserted.replace(
            year=video.upload_date.year,
            month=video.upload_date.month,
            day=video.upload_date.day,
        )
        video.save()


def list_channel_dirs_that_are_no_longer_subscribed_channels():

    dirs = []

    for directory in app_settings.MEDIA_ROOT.glob('*'):
        if not directory.is_dir():
            continue
        dirs.append(directory.name)

    for channel in Channel.objects.all():
        cn = schema_services.channel_directory_name(channel=channel)
        if cn in dirs:
            dirs.remove(cn)

    for directory in dirs:
        print(app_settings.MEDIA_ROOT / directory)


def find_video_titles_changed_compared_to_file():
    output = []

    for video in Video.objects.archived():
        ext = video.file.name.rsplit('.', 1)[-1]
        valid_name = vidar_storage.get_valid_name(schema_services.video_file_name(video=video, ext=ext))
        expected_file_path = video_helpers.upload_to_file(video, valid_name)

        if video.file.name != str(expected_file_path):
            print(video.file.name)
            print(expected_file_path)
            output.append(video)

    return output


def get_all_possible_video_qualities_found_in_dlp_formats():
    all_qualities_seen = set()
    current_qualities_seen = set()
    for video in Video.objects.exclude(dlp_formats__isnull=True):
        possible_quality = helpers.get_possible_qualities_from_dlp_formats(video.dlp_formats)
        all_qualities_seen.update(possible_quality)

        current_qualities_seen.add(video.quality)

    print(all_qualities_seen)
    print(current_qualities_seen)


def build_test_fixtures():

    fixtures = {}

    ### dlp_formats
    video = Video.objects.get(provider_object_id='aIxFlD77JBU')
    dlpf = video.dlp_formats

    for d in dlpf:
        if 'url' in d:
            d['url'] = ''
        if 'fragments' in d:
            d['fragments'] = []
        if 'http_headers' in d:
            d['http_headers'] = {}
        if 'manifest_url' in d:
            d['manifest_url'] = ''
        if 'downloader_options' in d:
            d['downloader_options'] = {}

    fixtures['dlp_formats'] = dlpf

    ### dlp_response
    video = Video.objects.get(provider_object_id='6CmX4ZmhwPM')
    dlpf = video.raw_dlp_response

    first_thumbnail = copy.copy(dlpf['thumbnails'][0])

    dlpf['thumbnails'] = [
        first_thumbnail,
    ]

    for d in dlpf['formats']:
        if 'url' in d:
            d['url'] = ''
        if 'fragments' in d:
            d['fragments'] = []
        if 'http_headers' in d:
            d['http_headers'] = {}
        if 'manifest_url' in d:
            d['manifest_url'] = ''
        if 'downloader_options' in d:
            d['downloader_options'] = {}

    fixtures['dlp_response'] = dlpf

    with open('vidar/tests_fixture.json', 'w') as f:
        json.dump(fixtures, f)


def generate_calendar_from_channel_crontabs(date=None, write_to_file='cal.ics', verbose=False):
    if not icalendar:
        return "pip install icalendar to use this functionality"
    if not date:
        date = timezone.now()
    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = date.replace(hour=23, minute=59, second=59, microsecond=9999) + timezone.timedelta(days=7)

    delta = timezone.timedelta(minutes=5)

    index = 0

    calendar = icalendar.Calendar()
    calendar.add('prodid', '-//My calendar product//mxm.dk//')
    calendar.add('version', '2.0')

    original_start = start
    for channel in Channel.objects.actively_scanning():

        start = original_start

        while start <= end:

            if crontab_services.is_active_now(channel.scanner_crontab, now=start):
                index += 1
                if verbose:
                    print(f'scanning {index=} {channel=} @ {start}')
                event = icalendar.Event()
                event['dtstart'] = start.strftime('%Y%m%dT%H%M%S')
                start_end_5_minutes = start + timezone.timedelta(minutes=5)
                event['dtend'] = start_end_5_minutes.strftime('%Y%m%dT%H%M%S')
                event['summary'] = f"{channel.name} @ {start:%I:%M}"

                calendar.add_component(event)

            start += delta

    if write_to_file:
        with open(write_to_file, 'wb') as fw:
            fw.write(calendar.to_ical())

    return calendar


def fix_all_video_filepaths(commit=False, remove_empty=False):
    videos_changed = 0
    changes_made = 0
    for video in Video.objects.archived().order_by('pk'):
        if changed := renamers.video_rename_all_files(video, commit=commit, remove_empty=remove_empty):
            videos_changed += 1
            changes_made += len(changed)

    print(f"{videos_changed=}")
    print(f"{changes_made=}")


def old_youtube_channel_system_safe_name(name):
    return "".join([c for c in name if c.isalpha() or c.isdigit() or c == ' ']).rstrip()


def change_channel_safe_name_video_file_names():
    # Old function used when i changed safe_name formatting

    real_name = 'Real Name'
    old_safe_name = 'Old Safe Name'
    new_safe_name = 'New Safe Name'

    print(f"{real_name:<50} {old_safe_name:<50} {new_safe_name:<50}")

    # for channel in Channel.objects.filter(name__startswith='Salt'):
    for channel in Channel.objects.all():
        real_name = channel.name
        new_safe_name = schema_services.channel_directory_name(channel=channel)
        old_safe_name = old_youtube_channel_system_safe_name(channel.name)

        if new_safe_name == old_safe_name or not channel.videos.exclude(file='').exists():
            continue

        # print(real_name)
        # print(old_safe_name)
        # print(new_safe_name)
        print(f"{real_name:<50} {old_safe_name:<50} {new_safe_name:<50}")

        go = input(f'Have you renamed the folder from "{old_safe_name}" to "{new_safe_name}" ? ')

        if not go.lower().startswith('y'):
            print('\tSkipping')
            continue

        for video in channel.videos.exclude(file=''):
            old_path = video.file.name
            new_path = old_path.replace(old_safe_name, new_safe_name)

            print(old_path)
            print(new_path)
            video.file.name = new_path
            video.save()


def assign_oldest_thumbnail_to_channel_year_directories(position='first', commit=True):

    # TODO: Make this work for remote storage systems too.
    if not file_helpers.is_field_using_local_storage(Video.thumbnail.field):
        raise FileStorageBackendHasNoMoveError('assign_oldest_thumbnail_to_channel_year_directories called while storage backend has no move ability')

    log.info('Assigning oldest thumbnail to channel year directories')

    oldest_video_year = Video.objects.all().order_by('-upload_date').last().upload_date.year
    current_year = timezone.now().year
    for channel in Channel.objects.all():

        if not channel.store_videos_by_year_separation:
            log.info(f'Channel {channel=} is not set to store by year separation.')
            continue

        for year in range(oldest_video_year, current_year + 1):
            videos_in_this_year = channel.videos.filter(upload_date__year=year).exclude(thumbnail='').order_by('-upload_date')
            if not videos_in_this_year.exists():
                continue

            if position == 'latest':
                video = videos_in_this_year.first()
            elif position == 'random':
                video = videos_in_this_year.order_by('?').first()
            else:
                video = videos_in_this_year.last()

            full_path = pathlib.Path(video.thumbnail.path)
            year_path = full_path.parent
            if channel.store_videos_in_separate_directories:
                year_path = year_path.parent
            if year_path.name != str(year):
                log.info(f'Invalid year match. {year=} {year_path=}')

            cover_filepath = year_path / "cover.jpg"
            if cover_filepath.exists():
                log.info(f'Cover already exists at {cover_filepath=}')
            else:
                log.info(f'Writing {year=} from {video.upload_date} to {cover_filepath=}')
                if commit:
                    with video.thumbnail.open() as fo, cover_filepath.open('wb') as fw:
                        fw.write(fo.read())

    return True


def channels_most_released_videos_in_a_single_day():

    for channel in Channel.objects.all():
        grouped_by_date = defaultdict(int)
        for video in channel.videos.all():
            grouped_by_date[video.upload_date] += 1

        sorted_by_value = dict(sorted(grouped_by_date.items(), key=lambda item: item[1], reverse=True))
        first_item = next(iter(sorted_by_value))
        print(first_item, sorted_by_value[first_item], channel)


def load_sponsorblock_database_into_durationskip(
    database_csv_file,
    specific_video_youtube_ids=None,
    skip_negative_votes=True,
    categories=None,
    save_all_extra_sb_fields=False,
    csv_file_encoding='utf-8',
):
    """Loads a SponsorBlock database CSV dump file into DurationSkip model.

    NEEDS MORE WORK!
        - Needs to check for overlaps (utils.do_new_start_end_points_overlap_existing)
        - How to account for multiple category entries of the same thing
            intro 16 to 28
            intro 19 to 28
            intro 8 to 256

    load_sponsorblock_database_into_durationskip(
        database_csv_file='E:/sponsorTimes.csv',
        specific_video_youtube_ids=['FfgT6zx4k3Q'],
    )

    Args:
        database_csv_file: The file to process, expecting the sponsorTimes.csv dump file
        specific_video_youtube_ids: If you only want to import certain youtube ids, supply a list of them here
        skip_negative_votes: Entries with votes below 0 are skipped by default
        categories: The categories to import, default is ['sponsor', 'intro', 'outro']
                    https://wiki.sponsor.ajay.app/w/Types#Category
        save_all_extra_sb_fields: During import certain SB only fields are removed from the raw data before saving,
                                    should we keep all fields or not?
        csv_file_encoding: default utf-8

    """
    queryset = Video.objects.exclude(file='')

    if not specific_video_youtube_ids:
        local_video_ids = queryset.values_list('provider_object_id', flat=True)
    else:
        local_video_ids = None

    if categories is None:
        categories = ['sponsor', 'intro', 'outro']

    video_ids_cache = {}
    for data in queryset.values('provider_object_id', 'id'):
        video_ids_cache[data['provider_object_id']] = data['id']

    skips_seen = set()

    found = 0
    with open(database_csv_file, 'r', encoding=csv_file_encoding) as fo:
        datareader = csv.DictReader(fo)
        for row in datareader:
            if specific_video_youtube_ids and row['videoID'] not in specific_video_youtube_ids:
                continue
            if local_video_ids and row['videoID'] not in local_video_ids:
                continue
            if categories and row['category'] not in categories:
                continue
            if skip_negative_votes and int(row['votes']) < 0:
                continue
            if not save_all_extra_sb_fields:
                # These fields don't really matter to us, don't save them. description and userAgent were empty,
                #   userID is SB's own, hashedVideoID is their own as well.
                for f in ['userID', 'hashedVideoID', 'userAgent', 'description', 'shadowHidden']:
                    try:
                        del row[f]
                    except KeyError:
                        pass
            found += 1

            if not row['UUID']:
                print(row)
                raise ValueError('row has no UUID value. Is this an SB db csv dump? sponsorTimes.csv is expected.')

            ds, created = DurationSkip.objects.get_or_create(
                video_id=video_ids_cache[row['videoID']],
                sb_uuid=row['UUID'],
                defaults=dict(
                    start=int(float(row['startTime'])),
                    end=int(float(row['endTime'])),
                    sb_category=row['category'],
                    sb_votes=int(row['votes']),
                    sb_data=row,
                ),
            )

            if specific_video_youtube_ids:
                skips_seen.add(ds)
                print(found, created, ds, row)

    return skips_seen or found


def rebalance_daily_crontab_scans():
    qs = Channel.objects.filter(scanner_crontab__endswith='* * *')

    existing_crontabs_and_nums = utils.count_crontab_used()

    splits = math.ceil(qs.count() / len(existing_crontabs_and_nums))

    print(splits)

    crontab_selection = list(existing_crontabs_and_nums.keys())
    selected_crontab = None

    for index, channel in enumerate(qs):
        if not selected_crontab or (index and index % splits == 0):
            selected_crontab = crontab_selection.pop()
        print(selected_crontab, channel)
        channel.scanner_crontab = selected_crontab
        channel.save(update_fields=['scanner_crontab'])


def rebalance_all_weekly_channels_across_week():
    from collections import defaultdict

    from vidar.models import Channel, Playlist

    # by_day_of_week = defaultdict(int)
    #
    # for p in Playlist.objects.exclude(crontab=''):
    #     if not p.crontab.endswith('*'):
    #         day_of_week = p.crontab.split(' ')[-1]
    #         by_day_of_week[day_of_week] += 1
    #
    # pprint(dict(sorted(by_day_of_week.items())))

    by_day_of_week = defaultdict(int)

    channels_found = 0

    for c in Channel.objects.exclude(scanner_crontab=''):
        if not c.scanner_crontab.endswith('*'):
            day_of_week = c.scanner_crontab.split(' ')[-1]
            by_day_of_week[day_of_week] += 1
            channels_found += 1

    pprint(dict(sorted(by_day_of_week.items())))

    print(channels_found)
    per_day = math.ceil(channels_found / 7)
    day = 1
    counter = 0

    for c in Channel.objects.exclude(scanner_crontab=''):
        if not c.scanner_crontab.endswith('*'):
            ct = c.scanner_crontab.split(' ')
            day_of_week = int(ct[-1])

            print(ct)
            if day_of_week != day:
                ct[-1] = str(day)

            print(ct)
            c.scanner_crontab = ' '.join(ct)
            c.save()

            counter += 1
            if counter >= per_day:
                day += 1
                counter = 0


def fix_video_thumbnails_renamed_physically_but_path_not_saved_to_database(commit=False):
    for video in Video.objects.archived().filter():

        if video.thumbnail.storage.exists(video.thumbnail.name):
            continue

        ext = video.thumbnail.name.rsplit('.', 1)[-1]
        new_full_filepath, new_storage_path = video_services.generate_filepaths_for_storage(
            video=video,
            ext=ext,
            upload_to=video_helpers.upload_to_thumbnail
        )
        exists = video.thumbnail.storage.exists(new_storage_path)
        if not exists:
            print('\tNew doesnt exist')
            break
        print(video)
        print('\t', new_storage_path)
        print('\t', video.thumbnail.name)
        if commit:
            video.thumbnail.name = str(new_storage_path)
            video.save(update_fields=['thumbnail'])
