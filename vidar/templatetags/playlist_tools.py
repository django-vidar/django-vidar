import warnings

from django import template
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.db.utils import NotSupportedError

from vidar.models import Playlist, UserPlaybackHistory


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
    if not hasattr(user, 'vidar_playback_completion_percentage'):
        return False
    if not playlist.videos.exists():
        return False

    try:
        return playlist.videos.annotate(
            percentage_of_video=F('duration') * float(user.vidar_playback_completion_percentage)
        ).filter(
            user_playback_history__user=user,
            user_playback_history__seconds__gte=F('percentage_of_video')
        ).distinct('id').order_by().count() == playlist.videos.count()
    except NotSupportedError:
        if raise_error:
            raise
        warnings.warn('Call to templatetags.playlist_tools.user_played_entire_playlist without DB support')
        return False


@register.simple_tag
def get_next_unwatched_video_on_playlist(playlist: Playlist, user: User):
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'vidar_playback_completion_percentage'):
        return False

    qs = playlist.playlistitem_set.exclude(video__file='')
    qs = playlist.apply_display_ordering_to_queryset(qs)

    for pi in qs:
        video = pi.video
        if UserPlaybackHistory.objects.filter(
                user=user,
                video=video,
        ).annotate(
            percentage_of_video=F('video__duration') * float(user.vidar_playback_completion_percentage)
        ).filter(
            seconds__gte=F('percentage_of_video')
        ).exists():
            continue
        return pi


@register.simple_tag
def get_next_unwatched_audio_on_playlist(playlist: Playlist, user: User):
    if not user.is_authenticated:
        return False
    if not hasattr(user, 'vidar_playback_completion_percentage'):
        return False

    qs = playlist.playlistitem_set.exclude(video__audio='')
    qs = playlist.apply_display_ordering_to_queryset(qs)

    for pi in qs:
        video = pi.video
        if UserPlaybackHistory.objects.filter(
                user=user,
                video=video,
        ).annotate(
            percentage_of_video=F('video__duration') * float(user.vidar_playback_completion_percentage)
        ).filter(
            seconds__gte=F('percentage_of_video')
        ).exists():
            continue
        return pi
