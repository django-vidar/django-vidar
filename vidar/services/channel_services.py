import json
import logging
import pathlib
import re
import requests
import shutil

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from bs4 import BeautifulSoup

from vidar import app_settings, exceptions, storages
from vidar.helpers import channel_helpers
from vidar.services import image_services, notification_services, schema_services


log = logging.getLogger(__name__)


def set_thumbnail(channel, url, save=True):
    log.debug(f"Setting thumbnail with {url}")
    contents, final_ext = image_services.download_and_convert_to_jpg(url)
    directory_name = schema_services.channel_directory_name(channel=channel)
    final_filename = f"{directory_name}.{final_ext}"
    channel.thumbnail.save(final_filename, ContentFile(contents), save=save)


def set_banner(channel, url, save=True):
    log.debug(f"Setting banner with {url}")
    contents, final_ext = image_services.download_and_convert_to_jpg(url)
    channel.banner.save('banner.jpg', ContentFile(contents), save=save)


def set_tvart(channel, url, save=True):
    log.debug(f"Setting tvart with {url}")
    contents, final_ext = image_services.download_and_convert_to_jpg(url)
    channel.tvart.save('tvart.jpg', ContentFile(contents), save=save)


def generate_filepaths_for_storage(channel, field, filename, upload_to):
    valid_new_filename = storages.vidar_storage.get_valid_name(filename)
    new_storage_path = upload_to(channel, valid_new_filename)
    new_full_filepath = pathlib.Path(field.storage.path(new_storage_path))
    return new_full_filepath, new_storage_path


def cleanup_storage(channel, dry_run=False):
    # Clean up cover.jpg and extras if exists.
    log.info(f'Clean up channel storage directory, {channel}')

    try:
        channel_directory_name = schema_services.channel_directory_name(channel=channel).strip()
    except exceptions.DirectorySchemaInvalidError:
        log.info('Skipping channel directory cleanup, name is invalid')
        return

    if not channel_directory_name:
        log.info(f'Skipping channel directory cleanup, name is invalid {channel_directory_name=}')
        return

    if channel_directory_name in ('/', '\\'):
        log.info('Skipping channel directory cleanup, it may remove other data')
        return

    channel_directory_path_str = storages.vidar_storage.path(channel_directory_name)
    channel_directory_path = pathlib.Path(channel_directory_path_str)

    log.debug(f'{channel_directory_path_str=}')
    log.debug(f'{channel_directory_path=}')

    if channel_directory_path == storages.vidar_storage.path(''):
        log.info('Skipping channel directory cleanup, directory path returned same as primary storage path.')
        return

    log.info(f'Cleaning up directory {channel_directory_path=}.')

    if not channel_directory_path.exists():
        log.info('Channel directory does not exist')
        return

    log.info('Channel directory exists, deleting remaining data.')

    if not dry_run:
        shutil.rmtree(channel_directory_path)

    return True


def recalculate_video_sort_ordering(channel):
    index = 0
    for video in channel.videos.order_by('upload_date', 'inserted', 'pk'):
        index += 1

        video.sort_ordering = index
        video.save(update_fields=['sort_ordering'])


def generate_sort_name(name: str):

    if not name or not name.lower().startswith('the ') or len(name) < 4:
        return ''

    the_format = name[:4]
    name_without_the = name[4:]

    return f"{name_without_the}, {the_format}".strip()


def set_channel_details_from_ytdlp(channel, response):
    channel.name = response['title']
    channel.description = response['description']
    channel.active = True
    channel.uploader_id = response['uploader_id']

    if not channel.sort_name:
        channel.sort_name = generate_sort_name(channel.name)

    channel.save()


def no_longer_active(channel, status='Banned', commit=True):
    channel.status = status

    channel.scanner_crontab = ''
    channel.index_videos = False
    channel.index_shorts = False
    channel.index_livestreams = False
    channel.full_archive = False
    channel.full_archive_after = None
    channel.mirror_playlists = False
    channel.swap_index_videos_after = None
    channel.swap_index_shorts_after = None
    channel.swap_index_livestreams_after = None

    if commit:
        channel.save()

    channel.playlists.exclude(crontab='').update(crontab='')


def apply_exception_status(channel, exc):
    exc_msg = str(exc).lower()

    status_changed = False
    old_status = channel.status

    if 'account' in exc_msg and 'terminated' in exc_msg:
        no_longer_active(channel=channel, status=channel_helpers.ChannelStatuses.TERMINATED)
        status_changed = True

    elif 'violated' in exc_msg and 'community' in exc_msg:
        no_longer_active(channel=channel, status=channel_helpers.ChannelStatuses.REMOVED)
        status_changed = True

    elif 'channel' in exc_msg and 'does not exist' in exc_msg:
        no_longer_active(channel=channel, status=channel_helpers.ChannelStatuses.NO_LONGER_EXISTS)
        status_changed = True

    if status_changed:
        log.info(f'Channel status changed from {old_status=} to {channel.status=}')
        notification_services.channel_status_changed(channel=channel)
        return True


def full_archiving_completed(channel):

    channel.full_archive = False
    channel.slow_full_archive = False
    channel.send_download_notification = True
    channel.fully_indexed = True
    channel.save()


def recently_scanned(channel):

    hours = channel.block_rescan_window_in_hours

    if not hours:
        hours = app_settings.CHANNEL_BLOCK_RESCAN_WINDOW_HOURS

    if not hours:
        return

    ago = timezone.now() - timezone.timedelta(hours=hours)
    return channel.scan_history.filter(inserted__gte=ago).first()


def delete_files(channel):

    # Prepare necessary variables to remove channel directory after removing the files.
    deletable_directories = set()
    for x in [channel.thumbnail, channel.banner, channel.tvart]:
        if x and x.storage.exists(x.name):
            parent_dir = pathlib.Path(x.path).parent
            deletable_directories.add(parent_dir)
            x.delete(save=False)

    for directory in deletable_directories:
        try:
            directory.rmdir()
        except (OSError, TypeError) as exc:
            if 'not empty' not in str(exc):
                log.exception('Failure to delete channel directory')
            else:
                log.info(f'Failure to delete channel {directory=}')


class ChannelScraper:

    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.soup = False
        self.yt_json = False
        self.json_data = False

    def __str__(self):
        return f"ChannelScraper({self.channel_id})"

    def get_json(self):
        """main method to return channel dict"""
        self.get_soup()
        self._extract_yt_json()
        self._parse_channel_main()
        self._parse_channel_meta()
        return self.json_data

    def get_soup(self):
        """return soup from youtube"""
        log.info(f"{self.channel_id}: scrape channel data from youtube")
        url = f"https://www.youtube.com/channel/{self.channel_id}/about?hl=en"
        requests_args = {
            'cookies': {"CONSENT": "YES+xxxxxxxxxxxxxxxxxxxxxxxxxxx"},
        }
        if user_agent := getattr(settings, 'REQUESTS_USER_AGENT', None):
            requests_args['headers'] = {'User-Agent': user_agent}
        if user_set_proxy := getattr(settings, 'REQUESTS_PROXIES', None):
            requests_args['proxies'] = user_set_proxy
        response = requests.get(url, **requests_args)
        if response.ok:
            channel_page = response.text
        else:
            log.info(f"{self.channel_id}: failed to extract channel info")
            raise ConnectionError
        self.soup = BeautifulSoup(channel_page, "html.parser")

    def _extract_yt_json(self):
        """parse soup and get ytInitialData json"""
        all_scripts = self.soup.find("body").find_all("script")
        script_content = None
        for script in all_scripts:
            if "var ytInitialData = " in str(script):
                script_content = str(script)
                break
        # extract payload
        script_content = script_content.split("var ytInitialData = ")[1]
        json_raw = script_content.rstrip(";</script>")
        self.yt_json = json.loads(json_raw)

    def _parse_channel_main(self):
        """extract maintab values from scraped channel json data"""
        main_tab = self.yt_json["header"]["c4TabbedHeaderRenderer"]
        # build and return dict
        self.json_data = {
            "channel_active": True,
            "channel_last_refresh": int(timezone.now().timestamp()),
            "channel_subs": self._get_channel_subs(main_tab),
            "channel_name": main_tab["title"],
            "channel_banner_url": self._get_thumbnails(main_tab, "banner"),
            "channel_tvart_url": self._get_thumbnails(main_tab, "tvBanner"),
            "channel_id": self.channel_id,
            "channel_subscribed": False,
        }

    @staticmethod
    def _get_thumbnails(main_tab, thumb_name):
        """extract banner url from main_tab"""
        try:
            all_banners = main_tab[thumb_name]["thumbnails"]
            banner = sorted(all_banners, key=lambda k: k["width"])[-1]["url"]
        except KeyError:
            banner = False

        return banner

    @staticmethod
    def _get_channel_subs(main_tab):
        """process main_tab to get channel subs as int"""
        channel_subs = 0
        try:
            sub_text_simple = main_tab["subscriberCountText"]["simpleText"]
            sub_text = sub_text_simple.split(" ")[0]
            if sub_text[-1] == "K":
                channel_subs = int(float(sub_text.replace("K", "")) * 1000)
            elif sub_text[-1] == "M":
                channel_subs = int(float(sub_text.replace("M", "")) * 1000000)
            elif int(sub_text) >= 0:
                channel_subs = int(sub_text)
            else:
                message = f"{sub_text} not dealt with"
                print(message)
        except KeyError:
            pass

        return channel_subs

    def _parse_channel_meta(self):
        """extract meta tab values from channel payload"""
        # meta tab
        meta_tab = self.yt_json["metadata"]["channelMetadataRenderer"]
        all_thumbs = meta_tab["avatar"]["thumbnails"]
        thumb_url = sorted(all_thumbs, key=lambda k: k["width"])[-1]["url"]
        # stats tab
        renderer = "twoColumnBrowseResultsRenderer"
        all_tabs = self.yt_json["contents"][renderer]["tabs"]
        for tab in all_tabs:
            if "tabRenderer" in tab.keys():
                if tab["tabRenderer"]["title"] == "About":
                    about_tab = tab["tabRenderer"]["content"]["sectionListRenderer"]["contents"][0][
                        "itemSectionRenderer"
                    ]["contents"][0]["channelAboutFullMetadataRenderer"]
                    break
        try:
            channel_views_text = about_tab["viewCountText"]["simpleText"]
            channel_views = int(re.sub(r"\D", "", channel_views_text))
        except (KeyError, UnboundLocalError):
            channel_views = None

        self.json_data.update(
            {
                "channel_description": meta_tab["description"],
                "channel_thumb_url": thumb_url,
                "channel_views": channel_views,
            }
        )
