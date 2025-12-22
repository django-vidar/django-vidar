import logging

from django import template
from django.db.models import F, Q
from django.utils.safestring import mark_safe

from vidar.models import Playlist, UserPlaybackHistory, Video
from vidar.services import video_services


log = logging.getLogger(__name__)


register = template.Library()


@register.simple_tag
def next_by_playlist(playlist: Playlist, video: Video, view=""):

    qs = playlist.playlistitem_set.all()
    if view == "audio":
        qs = playlist.playlistitem_set.exclude(video__audio="")

    qs = playlist.apply_playback_ordering_to_queryset(qs)

    object_ids = list(qs.values_list("video_id", flat=True))
    try:
        current_pos = object_ids.index(video.id)
    except ValueError:
        return

    if current_pos < len(object_ids) - 1:
        next_id = object_ids[current_pos + 1]
        return playlist.playlistitem_set.get(video_id=next_id)
    else:
        if next_playlist := playlist.next_playlist:
            qs = next_playlist.playlistitem_set.all()
            if view == "audio":
                qs = next_playlist.playlistitem_set.exclude(video__audio="")

            if qs.exists():
                return qs.first()


@register.simple_tag
def previous_by_playlist(playlist: Playlist, video: Video, view=""):

    qs = playlist.playlistitem_set.all()
    if view == "audio":
        qs = playlist.playlistitem_set.exclude(video__audio="")

    qs = playlist.apply_playback_ordering_to_queryset(qs)

    object_ids = list(qs.values_list("video_id", flat=True))

    try:
        current_pos = object_ids.index(video.id)
    except ValueError:
        return

    if current_pos > 0:
        previous_id = object_ids[current_pos - 1]
        return playlist.playlistitem_set.get(video_id=previous_id)
    else:
        try:
            if previous_playlist := playlist.previous_playlist:
                qs = previous_playlist.playlistitem_set.all()
                if view == "audio":
                    qs = previous_playlist.playlistitem_set.exclude(video__audio="")

                if qs.exists():
                    return qs.last()
        except playlist.DoesNotExist:
            pass


@register.filter()
def convert_seconds_to_hh_mm_ss(seconds):
    if seconds is None:
        return ""
    if seconds <= 60:
        return f"{seconds}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    output = ""
    if hours:
        output += f"{hours}:"
    return output + f"{minutes:02d}:{seconds:02d}"


@register.simple_tag(takes_context=True)
def get_lowest_playback_speed(context, video: Video, playlist: Playlist = None):
    request = context["request"]

    speeds = []

    if video.playback_speed:
        speeds.append(float(video.playback_speed))

    if video.channel and video.channel.playback_speed:
        speeds.append(float(video.channel.playback_speed))

    if playlist and playlist.playback_speed:
        speeds.append(float(playlist.playback_speed))

    if request.user.is_authenticated:
        if hasattr(request.user, "vidar_playback_speed") and request.user.vidar_playback_speed:
            speeds.append(float(request.user.vidar_playback_speed))

    if speeds:
        return min(speeds)

    return 1.0


@register.simple_tag()
def get_playback_speed(user, video: Video, playlist: Playlist = None, audio=False):

    if video.playback_speed:
        if vs := float(video.playback_speed):
            return vs

    if playlist and playlist.playback_speed:
        if pv := float(playlist.playback_speed):
            return pv

    if video.channel and video.channel.playback_speed:
        if cv := float(video.channel.playback_speed):
            return cv

    if user and user.is_authenticated and hasattr(user, "vidar_playback_speed"):
        if audio:
            if user.vidar_playback_speed_audio:
                if uav := float(user.vidar_playback_speed_audio):
                    return uav
        else:
            if user.vidar_playback_speed:
                if uav := float(user.vidar_playback_speed):
                    return uav

    return 1.0


@register.simple_tag(takes_context=True)
def get_lowest_playback_volume(context, video: Video, playlist: Playlist = None):
    request = context["request"]

    volumes = []

    if video.playback_volume:
        volumes.append(float(video.playback_volume))

    if video.channel and video.channel.playback_volume:
        volumes.append(float(video.channel.playback_volume))

    if playlist and playlist.playback_volume:
        volumes.append(float(playlist.playback_volume))

    if request.user.is_authenticated:
        if hasattr(request.user, "vidar_playback_volume") and request.user.vidar_playback_volume:
            volumes.append(float(request.user.vidar_playback_volume))

    if volumes:
        return min(volumes)

    return 1.0


@register.simple_tag()
def get_playback_volume(user, video: Video, playlist: Playlist = None):

    if video.playback_volume:
        if vv := float(video.playback_volume):
            return vv

    if playlist and playlist.playback_volume:
        if pv := float(playlist.playback_volume):
            return pv

    if video.channel and video.channel.playback_volume:
        if cv := float(video.channel.playback_volume):
            return cv

    if user and user.is_authenticated and hasattr(user, "vidar_playback_volume") and user.vidar_playback_volume:
        if uav := float(user.vidar_playback_volume):
            return uav

    return 1.0


@register.filter()
def get_playlist_position(video: Video, playlist: Playlist):

    qs = playlist.playlistitem_set.all()

    qs = playlist.apply_playback_ordering_to_queryset(qs)

    object_ids = list(qs.values_list("video_id", flat=True))

    try:
        return object_ids.index(video.id) + 1
    except ValueError:
        return


@register.simple_tag(takes_context=True)
def user_watched_video(context, video: Video):
    request = context["request"]

    if not request.user.is_authenticated:
        return
    if not hasattr(request.user, "vidar_playback_completion_percentage"):
        return

    return (
        UserPlaybackHistory.objects.filter(
            user=request.user,
            video=video,
        )
        .annotate(percentage_of_video=F("video__duration") * float(request.user.vidar_playback_completion_percentage))
        .filter(seconds__gte=F("percentage_of_video"))
        .first()
    )


@register.simple_tag
def next_by_channel(video: Video, view=""):
    if not video.channel_id:
        return
    return (
        video.channel.videos.order_by("sort_ordering")
        .filter(sort_ordering__lt=video.sort_ordering)
        .exclude(Q(pk=video.id) | Q(file=""))
        .last()
    )


@register.simple_tag
def previous_by_channel(video: Video, view=""):
    if not video.channel_id:
        return
    return (
        video.channel.videos.order_by("sort_ordering")
        .filter(
            sort_ordering__gt=video.sort_ordering,
        )
        .exclude(Q(pk=video.id) | Q(file=""))
        .first()
    )


@register.simple_tag
def next_by_upload_date(video: Video, view=""):
    if view == "audio":
        return (
            Video.objects.archived()
            .order_by("-upload_date", "-inserted")
            .filter(
                upload_date__lte=video.upload_date,
                inserted__lte=video.inserted,
            )
            .exclude(Q(pk=video.id) | Q(audio=""))
            .first()
        )

    return (
        Video.objects.archived()
        .order_by("-upload_date", "-inserted")
        .filter(
            upload_date__lte=video.upload_date,
            inserted__lte=video.inserted,
        )
        .exclude(pk=video.id)
        .first()
    )


@register.simple_tag
def previous_by_upload_date(video: Video, view=""):
    if view == "audio":
        return (
            Video.objects.archived()
            .order_by("-upload_date", "-inserted")
            .filter(
                upload_date__gte=video.upload_date,
                inserted__gte=video.inserted,
            )
            .exclude(Q(pk=video.id) | Q(audio=""))
            .last()
        )

    return (
        Video.objects.archived()
        .order_by("-upload_date", "-inserted")
        .filter(
            upload_date__gte=video.upload_date,
            inserted__gte=video.inserted,
        )
        .exclude(pk=video.id)
        .last()
    )


@register.simple_tag
def previous_by_date_downloaded(video: Video, view=""):
    if view == "audio":
        return (
            Video.objects.archived()
            .order_by("-date_downloaded")
            .filter(
                date_downloaded__gte=video.date_downloaded,
            )
            .exclude(Q(pk=video.id) | Q(audio=""))
            .last()
        )

    return (
        Video.objects.archived()
        .order_by("-date_downloaded")
        .filter(
            date_downloaded__gte=video.date_downloaded,
        )
        .exclude(pk=video.id)
        .last()
    )


@register.simple_tag
def next_by_date_downloaded(video: Video, view=""):
    if view == "audio":
        return (
            Video.objects.archived()
            .order_by("-date_downloaded")
            .filter(
                date_downloaded__lte=video.date_downloaded,
            )
            .exclude(Q(pk=video.id) | Q(audio=""))
            .first()
        )

    return (
        Video.objects.archived()
        .order_by("-date_downloaded")
        .filter(
            date_downloaded__lte=video.date_downloaded,
        )
        .exclude(pk=video.id)
        .first()
    )


@register.simple_tag
def previous_by_starred(video: Video, view=""):
    if view == "audio":
        return (
            Video.objects.archived()
            .order_by("-starred")
            .filter(
                starred__gte=video.starred,
            )
            .exclude(Q(pk=video.id) | Q(audio=""))
            .last()
        )

    return (
        Video.objects.archived()
        .order_by("-starred")
        .filter(
            starred__gte=video.starred,
        )
        .exclude(pk=video.id)
        .last()
    )


@register.simple_tag
def next_by_starred(video: Video, view=""):
    if view == "audio":
        return (
            Video.objects.archived()
            .order_by("-starred")
            .filter(
                starred__lte=video.starred,
            )
            .exclude(Q(pk=video.id) | Q(audio=""))
            .first()
        )

    return (
        Video.objects.archived()
        .order_by("-starred")
        .filter(
            starred__lte=video.starred,
        )
        .exclude(pk=video.id)
        .first()
    )


@register.simple_tag(takes_context=True)
def previous_by_unwatched(context, video: Video, view=""):

    if not video.channel_id:
        return

    channel = video.channel
    qs = channel.videos.exclude(file="")

    user = context["request"].user
    if not user.is_authenticated or not hasattr(user, "vidar_playback_completion_percentage"):
        return

    watched_video_ids = list(
        UserPlaybackHistory.objects.annotate(
            percentage_of_video=F("video__duration") * float(user.vidar_playback_completion_percentage)
        )
        .filter(seconds__gte=F("percentage_of_video"), user=user, video__channel=video.channel)
        .values_list("video_id", flat=True)
    )
    qs = qs.exclude(id__in=watched_video_ids)

    if view == "audio":
        return (
            qs.order_by("-upload_date", "-inserted")
            .filter(
                upload_date__gte=video.upload_date,
                inserted__gte=video.inserted,
            )
            .exclude(Q(pk=video.id) | Q(audio=""))
            .last()
        )

    return (
        qs.order_by("-upload_date", "-inserted")
        .filter(
            upload_date__gte=video.upload_date,
            inserted__gte=video.inserted,
        )
        .exclude(pk=video.id)
        .last()
    )


@register.simple_tag(takes_context=True)
def next_by_unwatched(context, video: Video, view=""):

    if not video.channel_id:
        return

    channel = video.channel
    qs = channel.videos.exclude(file="")

    user = context["request"].user
    if not user.is_authenticated or not hasattr(user, "vidar_playback_completion_percentage"):
        return

    watched_video_ids = list(
        UserPlaybackHistory.objects.annotate(
            percentage_of_video=F("video__duration") * float(user.vidar_playback_completion_percentage)
        )
        .filter(seconds__gte=F("percentage_of_video"), user=user, video__channel=video.channel)
        .values_list("video_id", flat=True)
    )
    qs = qs.exclude(id__in=watched_video_ids)

    if view == "audio":
        return (
            qs.order_by("-upload_date", "-inserted")
            .filter(
                upload_date__lte=video.upload_date,
                inserted__lte=video.inserted,
            )
            .exclude(Q(pk=video.id) | Q(audio=""))
            .first()
        )

    return (
        qs.order_by("-upload_date", "-inserted")
        .filter(
            upload_date__lte=video.upload_date,
            inserted__lte=video.inserted,
        )
        .exclude(pk=video.id)
        .first()
    )


@register.simple_tag
def is_on_watch_later(video: Video, user):
    playlist = Playlist.objects.get_user_watch_later(user=user)
    return playlist.videos.filter(pk=video.pk).exists()


@register.simple_tag
def description_with_linked_timestamps(video_description):
    output = []

    for line in video_description.splitlines():

        if ":" in line:

            for possible_timestamp in line.split(" "):
                if ":" not in possible_timestamp:
                    continue

                possible_timestamp = possible_timestamp.strip()

                minute, sep, second = possible_timestamp.partition(":")
                hour = None

                # 1:03:42 turns into
                # >>> '1:03:42'.partition(':')
                # ('1', ':', '03:42')
                if ":" in second:
                    k, sep, v = second.partition(":")
                    hour = minute
                    minute = k
                    second = v

                if not minute.isdigit() or not second.isdigit():
                    continue

                if hour is not None:
                    if not hour.isdigit():
                        continue

                    hour = int(hour)
                else:
                    hour = 0

                minute = int(minute)
                second = int(second)

                total_seconds = (hour * 60 * 60) + (minute * 60) + second

                html = f'<a href="javascript:;" onclick="setVideoTime({total_seconds})">{possible_timestamp}</a>'
                line = line.replace(possible_timestamp, html, 1)

        output.append(line)

    return mark_safe("\n".join(output))


@register.simple_tag()
def user_watch_history_for_video(video: Video, user):
    return video.user_playback_history.filter(user=user)


@register.simple_tag()
def video_can_be_deleted(video: Video, skip_playlist_ids=None):
    return video_services.can_delete(video=video, skip_playlist_ids=skip_playlist_ids)
