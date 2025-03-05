import logging

from vidar import app_settings, utils


log = logging.getLogger(__name__)


def get_ytdlp_args(rate_limit=None, proxies_attempted=None, retries=0, video=None, **kwargs):

    if rate_limit is None:
        rate_limit = app_settings.DOWNLOAD_SPEED_RATE_LIMIT

    if rate_limit and isinstance(rate_limit, int):
        kwargs.setdefault("ratelimit", rate_limit * 1024)

    # if retries <= 2:
    # Initial download attempt will use the system set proxy
    # if download fails because the video is blocked in the country
    # of that proxy, use another proxy.
    proxy_to_use = utils.get_proxy(proxies_attempted, instance=video, attempt=retries)
    kwargs['proxy'] = proxy_to_use
    log.info(f'Setting proxy "{proxy_to_use}" on yt-dlp download connection.')

    return kwargs


def get_video_downloader_args(video, retries=0, cache_folder=None, quality=None,
                              rate_limit=None, video_format=None, **kwargs):

    kwargs = get_ytdlp_args(
        proxies_attempted=video.system_notes.get('proxies_attempted'),
        rate_limit=rate_limit,
        video=video,
        retries=retries,
        **kwargs
    )

    if video_format is None:
        video_format = app_settings.VIDEO_DOWNLOAD_FORMAT

    if quality in [0, None]:
        video_format = app_settings.VIDEO_DOWNLOAD_FORMAT_BEST

    # kwargs.setdefault('format', "bestvideo+bestaudio")
    # kwargs.setdefault('format', 'bestvideo[ext=mp4,height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best')
    kwargs.setdefault('format', video_format.format(quality=quality))

    if cache_folder:
        # If quality is supplied, add it to the cached file name.
        # This prevents possible errors happening, the cache file still
        #   existing and someone selecting a better quality, yt-dlp would find the
        #   cached file at a lower quality and then assume its the selected quality.
        kwargs.setdefault('outtmpl', f"{cache_folder}/%(id)s_{quality}.%(ext)s")

    # If the video is being retried, pass check_formats, it'll grab the
    # next best available that is actually available.
    if retries:
        kwargs.setdefault('check_formats', 'selected')

    kwargs.setdefault('writeinfojson', True)

    return kwargs


def get_comment_downloader_extractor_args(total_max_comments=None, max_parents=None,
                                          max_replies=None, max_replies_per_thread=None, sorting=None):
    """
        https://github.com/yt-dlp/yt-dlp#extractor-arguments

        comment_sort: top or new (default) - choose comment sorting mode (on YouTube's side)

        max_comments: Limit the amount of comments to gather. Comma-separated list of integers
        representing max-comments,max-parents,max-replies,max-replies-per-thread.
        Default is all,all,all,all

        E.g.
        all,all,1000,10     will get a maximum of 1000 replies total, with up to 10 replies per thread.
        1000,all,100     will get a maximum of 1000 comments, with a maximum of 100 replies total

        "extractor_args": {
            "youtube": {
                "max_comments": max_comments_list,
                "comment_sort": [comment_sort],
            }
        },"""

    if total_max_comments is None:
        total_max_comments = app_settings.COMMENTS_TOTAL_MAX_COMMENTS
    if max_parents is None:
        max_parents = app_settings.COMMENTS_MAX_PARENTS
    if max_replies is None:
        max_replies = app_settings.COMMENTS_MAX_REPLIES
    if max_replies_per_thread is None:
        max_replies_per_thread = app_settings.COMMENTS_MAX_REPLIES_PER_THREAD
    if sorting is None:
        sorting = app_settings.COMMENTS_SORTING

    defaults = {
        'max_comments': [
            str(total_max_comments), str(max_parents), str(max_replies), str(max_replies_per_thread)
        ]
    }

    if sorting:
        defaults['comment_sort'] = [sorting]

    return {'extractor_args': {'youtube': defaults}}


def convert_format_note_to_int(format_note):
    format_note_digits_only = ''.join([x for x in format_note if x.isdigit()])
    return int(format_note_digits_only)


def get_displayable_video_quality_from_dlp_format(dlp_format):

    if 'format_note' not in dlp_format:
        return str(dlp_format['height'])

    format_note_raw = dlp_format['format_note']

    # Non standard formats seen so far:
    #   720p60
    #   Premium+medium
    #   DASH video

    tmp = format_note_raw.split('+')
    format_note = tmp[0]

    small_fn = format_note.lower()
    if small_fn in ['premium', 'medium'] or 'dash' in small_fn:
        return str(dlp_format['height'])

    # 720p60
    if 'p' in small_fn:
        quality, fps = small_fn.split('p', 1)
        return quality

    return format_note


def get_video_downloaded_quality_from_dlp_response(info):
    split_format_id = info['format_id'].split('+')
    potential_video_format_id = split_format_id[0]

    for f in info['formats']:
        if f['format_id'] == potential_video_format_id:
            format_note = get_displayable_video_quality_from_dlp_format(f)
            return convert_format_note_to_int(format_note)


def get_possible_qualities_from_dlp_formats(formats):
    possible_formats = set()
    for f in formats:
        if f.get('video_ext') == 'none':
            continue
        if f.get('format_note'):
            format_note = get_displayable_video_quality_from_dlp_format(f)
            format_note_int = convert_format_note_to_int(format_note)
            possible_formats.add(format_note_int)
    return sorted(possible_formats)


def is_video_at_highest_quality_from_dlp_response(dlp_response):
    current_quality = get_video_downloaded_quality_from_dlp_response(dlp_response)
    if not current_quality:
        raise ValueError('No current quality found in dlp response.')

    return is_quality_at_highest_quality_from_dlp_formats(dlp_response['formats'], current_quality)


def is_quality_at_highest_quality_from_dlp_formats(dlp_formats, current_quality):
    max_quality = get_highest_quality_from_video_dlp_formats(dlp_formats)
    return current_quality == max_quality or current_quality > max_quality


def is_quality_at_higher_quality_than_possible_from_dlp_formats(dlp_formats, current_quality):
    max_quality = get_highest_quality_from_video_dlp_formats(dlp_formats)
    return current_quality > max_quality


def get_highest_quality_from_video_dlp_formats(dlp_formats):
    possible_qualities = get_possible_qualities_from_dlp_formats(dlp_formats)
    if not possible_qualities:
        raise ValueError('No qualities found in dlp_formats.')
    return max(possible_qualities)


def get_higher_qualities_from_video_dlp_response(dlp_response, current_quality=None):
    if current_quality is None:
        current_quality = get_video_downloaded_quality_from_dlp_response(dlp_response)

    if not current_quality:
        raise ValueError('No current quality found in dlp response.')

    return get_higher_qualities_from_video_dlp_formats(dlp_response['formats'], current_quality)


def get_higher_qualities_from_video_dlp_formats(dlp_formats, current_quality):

    possible_qualities = get_possible_qualities_from_dlp_formats(dlp_formats)
    higher_qualities = set()
    for quality in possible_qualities:
        if quality > current_quality:
            higher_qualities.add(quality)
    return higher_qualities


def get_banner_art(thumbnails):
    """extract banner artwork"""
    for i in thumbnails:
        if not i.get("width"):
            continue
        if i["width"] // i["height"] > 5:
            return i["url"]

    return False


def get_thumb_art(thumbnails):
    """extract thumb art"""
    for i in thumbnails:
        if i.get("id") == "avatar_uncropped":
            return i["url"]
    for i in thumbnails:
        if not i.get("width"):
            continue
        if i.get("width") == i.get("height"):
            return i["url"]

    return False


def get_tv_art(thumbnails):
    """extract tv artwork"""
    for i in thumbnails:
        if i.get("id") == "banner_uncropped":
            return i["url"]
    for i in thumbnails:
        if not i.get("width"):
            continue
        if i["width"] // i["height"] < 2 and not i["width"] == i["height"]:
            return i["url"]

    return False


def exception_is_live_event(exc):
    message = str(exc)
    return 'live event will' in message.lower()


def fix_quality_values(value):
    # Some videos return 360p as 352.
    if value == 352:
        return 360

    # shorts as 720p return as 640
    if value == 640:
        return 720
    return value
