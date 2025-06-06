import math
import warnings

from django import template
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.db.utils import NotSupportedError

from vidar.models import Playlist, UserPlaybackHistory, Video


User = get_user_model()


register = template.Library()


@register.simple_tag
def is_subscribed_to_playlist(playlist_id):
    try:
        return Playlist.objects.get(Q(provider_object_id=playlist_id) | Q(provider_object_id_old=playlist_id))
    except Playlist.DoesNotExist:
        pass
    return


@register.simple_tag
def user_played_entire_playlist(playlist: Playlist, user, raise_error=False):
    if not user.is_authenticated:
        return False
    if not hasattr(user, "vidar_playback_completion_percentage"):
        return False

    base_qs = playlist.videos.exclude(file="")
    base_qs_count = base_qs.count()

    if not base_qs_count:
        return False

    try:
        return (
            base_qs.annotate(percentage_of_video=F("duration") * float(user.vidar_playback_completion_percentage))
            .filter(user_playback_history__user=user, user_playback_history__seconds__gte=F("percentage_of_video"))
            .distinct("id")
            .order_by()
            .count()
            == base_qs_count
        )
    except NotSupportedError:  # pragma: no cover
        if raise_error:
            raise
        warnings.warn("Call to templatetags.playlist_tools.user_played_entire_playlist without DB support")
        return False


@register.simple_tag
def get_next_unwatched_video_on_playlist(playlist: Playlist, user: User):
    if not user.is_authenticated:
        return False
    if not hasattr(user, "vidar_playback_completion_percentage"):
        return False

    qs = playlist.playlistitem_set.exclude(video__file="")
    qs = playlist.apply_display_ordering_to_queryset(qs)

    for pi in qs:
        video = pi.video
        if (
            UserPlaybackHistory.objects.filter(
                user=user,
                video=video,
            )
            .annotate(percentage_of_video=F("video__duration") * float(user.vidar_playback_completion_percentage))
            .filter(seconds__gte=F("percentage_of_video"))
            .exists()
        ):
            continue
        return pi


@register.simple_tag
def get_next_unwatched_audio_on_playlist(playlist: Playlist, user: User):
    if not user.is_authenticated:
        return False
    if not hasattr(user, "vidar_playback_completion_percentage"):
        return False

    qs = playlist.playlistitem_set.exclude(video__audio="")
    qs = playlist.apply_display_ordering_to_queryset(qs)

    for pi in qs:
        video = pi.video
        if (
            UserPlaybackHistory.objects.filter(
                user=user,
                video=video,
            )
            .annotate(percentage_of_video=F("video__duration") * float(user.vidar_playback_completion_percentage))
            .filter(seconds__gte=F("percentage_of_video"))
            .exists()
        ):
            continue
        return pi


@register.simple_tag
def link_to_playlist_page(playlist: Playlist, video: Video, num_per_page=50):

    qs = playlist.playlistitem_set.all()

    qs = playlist.apply_playback_ordering_to_queryset(qs)

    object_ids = list(qs.values_list("video_id", flat=True))
    try:
        current_pos = object_ids.index(video.id)
    except ValueError:
        return

    max_possible_pages = int(math.ceil(len(object_ids) / num_per_page))
    if max_possible_pages > 1:
        return math.ceil((current_pos + 1) / num_per_page)
