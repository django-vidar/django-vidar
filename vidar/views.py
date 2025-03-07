import logging
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.mixins import PermissionRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import FieldDoesNotExist, FieldError
from django.db.models import Avg, Case, CharField, Count, F, Max, Q, Sum, When
from django.db.models.functions import Coalesce, TruncDate, TruncWeek, TruncYear
from django.http import HttpResponse, JsonResponse
from django.shortcuts import HttpResponseRedirect, get_object_or_404, redirect, render
from django.template import Context, Template
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView

from vidar import app_settings, forms, helpers, oneoffs, storages, tasks, utils
from vidar.exceptions import FileStorageBackendHasNoMoveError
from vidar.helpers import celery_helpers, channel_helpers, statistics_helpers
from vidar.interactor import YTDLPInteractor
from vidar.mixins import (
    FieldFilteringMixin,
    HTMXIconBooleanSwapper,
    PublicOrLoggedInUserMixin,
    RequestBasedCustomQuerysetFilteringMixin,
    RequestBasedQuerysetFilteringMixin,
    RestrictQuerySetToAuthorizedUserMixin,
    UseProviderObjectIdMatchingMixin,
)
from vidar.models import (
    Channel,
    ExtraFile,
    Highlight,
    Playlist,
    PlaylistItem,
    ScanHistory,
    UserPlaybackHistory,
    Video,
    VideoBlocked,
    VideoDownloadError,
    VideoHistory,
    VideoNote,
)
from vidar.pagination import paginator_helper
from vidar.services import crontab_services, playlist_services, video_services


log = logging.getLogger(__name__)


class GeneralUtilitiesView(UserPassesTestMixin, TemplateView):
    template_name = 'vidar/general-utilities.html'

    def test_func(self):
        return self.request.user.is_superuser

    def get_context_data(self, **kwargs):
        channel_choice_form_initial = {}
        if cid := self.request.GET.get('channel_id'):
            channel_choice_form_initial['channel'] = cid
        kwargs['channel_choice_form'] = forms.ChannelChoiceForm(initial=channel_choice_form_initial)
        kwargs['channel_cover_copy_form'] = forms.CopyVideoThumbnailAsYearlyCoverForm()
        return super().get_context_data(**kwargs)

    def post(self, request, *args, **kwargs):
        print(request.POST)

        if 'videos_rename_files' in request.POST:
            tasks.rename_all_archived_video_files.delay()
            messages.info(request, 'Video file renaming task queued.')

        if 'channel_rename_files' in request.POST:
            channel_id = request.POST['channel']
            channel = get_object_or_404(Channel, id=channel_id)
            tasks.channel_rename_files.delay(channel_id=channel.pk)
            messages.info(request, f'"{channel}" files renaming task queued.')

        if 'video_thumbnail_copy_to_year' in request.POST:
            try:
                oneoffs.assign_oldest_thumbnail_to_channel_year_directories(position=request.POST['position'])
                messages.success(request, 'Video thumbnails copied')
            except FileStorageBackendHasNoMoveError:
                messages.error(request, 'Cannot assign cover thumbnails due to storage backend has no move ability')

        if 'scan_all' in request.POST:
            countdown = 0
            wait_period = int(request.POST.get('countdown', 10))
            qs = Channel.objects.all()
            if 'indexing_enabled' in request.POST:
                qs = Channel.objects.indexing_enabled()
            for channel in qs:
                countdown = tasks.trigger_channel_scanner_tasks(
                    channel=channel,
                    countdown=countdown,
                    wait_period=wait_period,
                )

        return redirect('vidar:utilities')


class ChannelListViewContextData(FieldFilteringMixin):
    # paginate_by = 20

    FILTERING_SKIP_FIELDS = ['o', 'show']

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data(*args, **kwargs)
        qs = self.model.objects.all()
        kwargs['active_count'] = qs.filter(active=True).count()
        kwargs['download_videos_true_count'] = qs.filter(download_videos=True).count()
        kwargs['download_shorts_true_count'] = qs.filter(download_shorts=True).count()
        kwargs['download_livestreams_true_count'] = qs.filter(download_livestreams=True).count()

        kwargs['index_videos_true_count'] = qs.filter(index_videos=True).count()
        kwargs['index_shorts_true_count'] = qs.filter(index_shorts=True).count()
        kwargs['index_livestreams_true_count'] = qs.filter(index_livestreams=True).count()

        kwargs['full_archive_count'] = qs.filter(full_archive=True).count()

        kwargs['show_download_notification_column'] = qs.filter(send_download_notification=False).exists()

        kwargs['download_comments_with_video_count'] = qs.filter(download_comments_with_video=True).count()
        kwargs['download_comments_during_scan_count'] = qs.filter(download_comments_during_scan=True).count()

        return kwargs


class ChannelListView(
    PermissionRequiredMixin, ChannelListViewContextData, RequestBasedQuerysetFilteringMixin, ListView
):
    model = Channel
    permission_required = ['vidar.view_channel']
    queryset = Channel.objects.annotate(
        latest=Max('videos__upload_date'),
        file_size=Sum('videos__file_size'),
        name_sort=Coalesce(
            Case(
                When(sort_name='', then=None),
                When(sort_name__isnull=False, then='sort_name'),
                default=None,
                output_field=CharField(),
            ),
            Case(
                When(display_name='', then=None),
                When(display_name__isnull=False, then='display_name'),
                default=None,
                output_field=CharField(),
            ),
            'name',
        ),
    )
    ordering = ['name_sort']
    RequestBaseFilteringDefaultFields = ['name', 'provider_object_id']

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data(*args, **kwargs)

        qualities = {}

        for i, v in Channel._meta.get_field('quality').choices:
            qs = Video.objects.archived().filter(quality=i)
            videos_at_this_quality_counter = qs.aggregate(sumd=Sum('file_size'))['sumd'] or 0
            if videos_at_this_quality_counter:
                qualities[i] = qs.count(), videos_at_this_quality_counter

        qs = Video.objects.archived()
        qualities['Totals'] = qs.count(), qs.aggregate(sumd=Sum('file_size'))['sumd'] or 0
        kwargs['quality_counters'] = qualities

        qs = self.model.objects.all()
        kwargs['has_shorts_index'] = qs.filter(index_shorts=True).exists()
        kwargs['has_livestreams_index'] = qs.filter(index_livestreams=True).exists()
        kwargs['has_full_archive'] = qs.filter(full_archive=True).exists()
        kwargs['has_download_comments_with_video'] = qs.filter(download_comments_with_video=True).exists()
        kwargs['has_download_comments_during_scan'] = qs.filter(download_comments_during_scan=True).exists()

        return kwargs

    def get_queryset(self):
        qs = super().get_queryset()
        if ordering := self.request.GET.get('o'):
            direction = '-' if ordering.startswith('-') else ''
            ordering = ordering[1:] if direction else ordering
            if ordering == 'schedule':
                whens = utils.get_channel_ordering_by_next_crontab_whens()
                return (
                    Channel.objects.all()
                    .annotate(channel_next_based_order=Case(*whens, default=10000))
                    .order_by('channel_next_based_order', 'name')
                )
            elif ordering == 'latest_video':
                return (
                    Channel.objects.all()
                    .annotate(latest_video_upload_date=Max('videos__upload_date'))
                    .order_by(f'{direction}latest_video_upload_date', 'name')
                )

        return qs

    def get_ordering(self):
        if ordering := self.request.GET.get('o'):
            direction = '-' if ordering.startswith('-') else ''
            ordering = ordering[1:] if direction else ordering
            if ordering not in ['schedule']:
                try:
                    if ordering not in ['latest', 'file_size']:
                        # Ensure the field supplied actually exists on Channel.
                        # latest is a feature on the queryset itself.
                        self.model._meta.get_field(ordering)
                    return [f'{direction}{ordering}', 'name']
                except FieldDoesNotExist:
                    pass
        return super().get_ordering()


class ChannelBooleanSwapper(
    PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, HTMXIconBooleanSwapper, UpdateView
):
    model = Channel
    fields = [
        'index_videos',
        'download_videos',
        'full_archive',
        'index_shorts',
        'download_shorts',
        'index_livestreams',
        'download_livestreams',
        'download_comments_during_scan',
        'download_comments_with_video',
        'send_download_notification',
    ]
    permission_required = ['vidar.change_channel']


class ChannelDetailView(PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, DetailView):
    model = Channel
    permission_required = ['vidar.view_channel']
    paginate_by = 10

    def get_paginate_by(self, queryset):
        return self.request.GET.get('limit') or self.paginate_by

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['quality_form'] = forms.QualityChoiceForm(
            initial={
                'quality': self.object.quality,
            },
            channel_default_quality=self.object.quality,
        )
        kwargs['has_at_max_quality_videos'] = self.object.videos.filter(at_max_quality=True).exists()

        qs = self.object.videos.all()
        if q := self.request.GET.get('q'):
            q = q.strip()

            if ':' in q:

                field, q = q.split(':', 1)
                field = field.strip()
                q = q.strip()

                if q.lower() in ['true', 'false']:
                    q = q == 'true'
                elif q.lower() == 'none':
                    q = None

                if '__' not in field:
                    field = f"{field}__icontains"

                try:
                    qs = qs.filter(**{field: q})
                except FieldError:
                    qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(provider_object_id=q))

            else:
                qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(provider_object_id=q))

        if 'starred' in self.request.GET:
            qs = qs.exclude(starred__isnull=True).order_by('-starred')

        elif 'missing' in self.request.GET:
            qs = qs.filter(file='')

        elif 'archived' in self.request.GET:
            qs = qs.exclude(file='')

        elif 'watched' in self.request.GET:
            qs = qs.exclude(watched__isnull=True)

        if 'unwatched' in self.request.GET:
            user = self.request.user
            if user.is_authenticated and hasattr(user, 'vidar_playback_completion_percentage'):
                watched_video_ids = list(
                    UserPlaybackHistory.objects.annotate(
                        percentage_of_video=F('video__duration') * float(user.vidar_playback_completion_percentage)
                    )
                    .filter(seconds__gte=F('percentage_of_video'), user=self.request.user, video__channel=self.object)
                    .values_list('video_id', flat=True)
                )
                qs = qs.exclude(id__in=watched_video_ids)

        if quality := self.request.GET.get('quality'):
            qs = qs.filter(quality=quality)

        if ordering := self.request.GET.get('o'):
            qs = qs.order_by(ordering)

        if year := self.request.GET.get('year'):
            qs = qs.filter(upload_date__year=year)
        if month := self.request.GET.get('month'):
            qs = qs.filter(upload_date__month=month)

        kwargs.update(
            paginator_helper(
                context_key="channel_videos",
                queryset=qs,
                params=self.request.GET,
                limit=10,
            )
        )
        return kwargs

    def post(self, request, **kwargs):
        self.object = self.get_object()
        for video in self.object.videos.filter(file=''):
            if f"video-{video.pk}" in request.POST:

                quality = int(self.request.POST['quality'])

                download_video(request, video.pk, quality=quality)

        return helpers.redirect_next_or_obj(request, self.object)


class ChannelManageView(PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, DetailView):
    model = Channel
    permission_required = ['vidar.view_channel']
    template_name = 'vidar/channel_manage.html'

    def post(self, *args, **kwargs):
        self.object = self.get_object()
        if 'update_channel_details' in self.request.POST:
            tasks.update_channel_banners.delay(pk=self.object.id)
            messages.success(self.request, 'Channel detail update queued, will be processed shortly.')
        return redirect('vidar:channel-manage', pk=self.object.id)


@user_passes_test(lambda u: u.has_perm('vidar.add_channel'))
def channel_add_view(request):
    provider_object_id_raw = request.GET.get('channel')
    youtube_channel_url = request.GET.get('url')

    if provider_object_id_raw:
        if channel_exists := Channel.objects.already_exists(provider_object_id_raw):
            messages.info(request, 'Already subscribed to channel')
            return redirect(channel_exists)

    if youtube_channel_url:
        if ytdlp_channel_id := utils.get_channel_id_from_url(youtube_channel_url):
            provider_object_id_raw = ytdlp_channel_id
            if channel_exists := Channel.objects.already_exists(ytdlp_channel_id):
                messages.info(request, 'Already subscribed to channel')
                return redirect(channel_exists)

    indexing_status = request.GET.get('index', 'true').lower() == 'true'
    videos_initial, livestreams_initial = None, None
    shorts_initial = {'index_shorts': False, 'download_shorts': False}
    if not indexing_status:
        videos_initial = {'index_videos': False, 'download_videos': False}
        shorts_initial = {'index_shorts': False, 'download_shorts': False}
        livestreams_initial = {'index_livestreams': False, 'download_livestreams': False}

    general_form = forms.ChannelGeneralCreateOptionsForm(
        initial={
            'scanner_crontab': utils.generate_balanced_crontab_hourly(),
            'provider_object_id': provider_object_id_raw,
        }
    )
    sub_form = forms.ChannelSubGeneralOptionsForm()
    videos_form = forms.ChannelVideosOptionsForm(initial=videos_initial)
    shorts_form = forms.ChannelShortsOptionsForm(initial=shorts_initial)
    livestreams_form = forms.ChannelLivestreamsOptionsForm(initial=livestreams_initial)
    mirroring_form = forms.ChannelMirroringPlaylistsForm()
    playback_form = forms.ChannelPlaybackOptionsForm(user=request.user)
    admin_form = forms.ChannelAdministrativeOptionsForm()

    if request.method == 'POST':
        has_errors = False

        general_form = forms.ChannelGeneralCreateOptionsForm(request.POST)
        if general_form.is_valid():
            channel = general_form.save()

            sub_form = forms.ChannelSubGeneralOptionsForm(request.POST, instance=channel)
            videos_form = forms.ChannelVideosOptionsForm(request.POST, instance=channel)
            shorts_form = forms.ChannelShortsOptionsForm(request.POST, instance=channel)
            livestreams_form = forms.ChannelLivestreamsOptionsForm(request.POST, instance=channel)
            mirroring_form = forms.ChannelMirroringPlaylistsForm(request.POST, instance=channel)
            playback_form = forms.ChannelPlaybackOptionsForm(request.POST, instance=channel, user=request.user)
            admin_form = forms.ChannelAdministrativeOptionsForm(request.POST, instance=channel)

            if sub_form.is_valid():
                sub_form.save()
            else:
                has_errors = True

            if videos_form.is_valid():
                videos_form.save()
            else:
                has_errors = True

            if shorts_form.is_valid():
                shorts_form.save()
            else:
                has_errors = True

            if livestreams_form.is_valid():
                livestreams_form.save()
            else:
                has_errors = True

            if mirroring_form.is_valid():
                mirroring_form.save()
            else:
                has_errors = True

            if playback_form.is_valid():
                playback_form.save()
            else:
                has_errors = True

            if admin_form.is_valid():
                admin_form.save()
            else:
                has_errors = True

        else:
            has_errors = True

        if not has_errors:
            tasks.subscribe_to_channel.delay(channel.provider_object_id)

            if ccron := channel.scanner_crontab:
                if ccron.endswith('* * *'):
                    if matched_datetimes := crontab_services.calculate_schedule(ccron):
                        messages.info(request, f'Channel scanning {len(matched_datetimes)} times per day')
                else:
                    if matched_datetimes := crontab_services.calculate_schedule(ccron, check_month=True):
                        messages.info(request, f'Channel scanning {len(matched_datetimes)} times per month')

            return redirect(channel)

    return render(
        request,
        'vidar/channel_form.html',
        {
            'general_form': general_form,
            'sub_form': sub_form,
            'videos_form': videos_form,
            'shorts_form': shorts_form,
            'livestreams_form': livestreams_form,
            'mirroring_form': mirroring_form,
            'playback_form': playback_form,
            'admin_form': admin_form,
        },
    )


@user_passes_test(lambda u: u.has_perm('vidar.change_channel'))
def channel_update_view(request, pk=None, slug=None):

    if slug:
        channel = get_object_or_404(Channel, slug=slug)
    else:
        channel = get_object_or_404(Channel, pk=pk)

    general_form = forms.ChannelGeneralUpdateOptionsForm(instance=channel)
    sub_form = forms.ChannelSubGeneralOptionsForm(instance=channel)
    videos_form = forms.ChannelVideosOptionsForm(instance=channel)
    shorts_form = forms.ChannelShortsOptionsForm(instance=channel)
    livestreams_form = forms.ChannelLivestreamsOptionsForm(instance=channel)
    mirroring_form = forms.ChannelMirroringPlaylistsForm(instance=channel)
    playback_form = forms.ChannelPlaybackOptionsForm(instance=channel, user=request.user)
    admin_form = forms.ChannelAdministrativeOptionsForm(instance=channel)

    if request.method == 'POST':
        has_errors = False

        general_form = forms.ChannelGeneralUpdateOptionsForm(request.POST, instance=channel)
        if general_form.is_valid():

            sub_form = forms.ChannelSubGeneralOptionsForm(request.POST, instance=channel)
            videos_form = forms.ChannelVideosOptionsForm(request.POST, instance=channel)
            shorts_form = forms.ChannelShortsOptionsForm(request.POST, instance=channel)
            livestreams_form = forms.ChannelLivestreamsOptionsForm(request.POST, instance=channel)
            mirroring_form = forms.ChannelMirroringPlaylistsForm(request.POST, instance=channel)
            playback_form = forms.ChannelPlaybackOptionsForm(request.POST, instance=channel, user=request.user)
            admin_form = forms.ChannelAdministrativeOptionsForm(request.POST, instance=channel)

            if sub_form.is_valid():
                sub_form.save()
            else:
                has_errors = True

            if videos_form.is_valid():
                videos_form.save()
            else:
                has_errors = True

            if shorts_form.is_valid():
                shorts_form.save()
            else:
                has_errors = True

            if livestreams_form.is_valid():
                livestreams_form.save()
            else:
                has_errors = True

            if mirroring_form.is_valid():
                mirroring_form.save()
            else:
                has_errors = True

            if playback_form.is_valid():
                playback_form.save()
            else:
                has_errors = True

            if admin_form.is_valid():
                admin_form.save()
            else:
                has_errors = True

        else:
            has_errors = True

        if not has_errors:

            if channel.full_archive_after:
                fa_date = channel.full_archive_after.date()
                if oc := Channel.objects.filter(full_archive_after__date=fa_date).exclude(id=channel.id).count():
                    messages.info(request, f'Alert: {oc} other channel(s) with the same Full Archive After date exist.')

            if ccron := channel.scanner_crontab:
                if ccron.endswith('* * *'):
                    if matched_datetimes := crontab_services.calculate_schedule(ccron):
                        messages.info(request, f'Channel scanning {len(matched_datetimes)} times per day')
                else:
                    if matched_datetimes := crontab_services.calculate_schedule(ccron, check_month=True):
                        messages.info(request, f'Channel scanning {len(matched_datetimes)} times per month')

            return helpers.redirect_next_or_obj(request, channel)

    return render(
        request,
        'vidar/channel_form.html',
        {
            'object': channel,
            'channel': channel,
            'general_form': general_form,
            'sub_form': sub_form,
            'videos_form': videos_form,
            'shorts_form': shorts_form,
            'livestreams_form': livestreams_form,
            'mirroring_form': mirroring_form,
            'playback_form': playback_form,
            'admin_form': admin_form,
        },
    )


class ChannelDeleteView(PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, DeleteView):
    model = Channel
    permission_required = ['vidar.delete_channel']
    success_url = reverse_lazy('vidar:channel-index')

    def form_valid(self, form):

        keep_archived_videos = 'keep_archived_videos' in self.request.POST
        delete_playlists = 'delete_playlists' in self.request.POST

        messages.success(self.request, 'Channel deletion queued')
        tasks.delete_channel.delay(
            pk=self.object.pk,
            keep_archived_videos=keep_archived_videos,
            delete_playlists=delete_playlists,
        )

        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['starred_videos'] = self.object.videos.filter(starred__isnull=False)
        kwargs['videos_with_playlists'] = self.object.videos.filter(playlists__isnull=False)
        return kwargs


class ChannelDeleteVideosView(PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, DeleteView):
    model = Channel
    permission_required = ['vidar.delete_channel', 'vidar.delete_video']
    template_name = 'vidar/channel_confirm_delete_videos.html'

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['starred_videos'] = self.object.videos.filter(starred__isnull=False)
        kwargs['videos_with_playlists'] = self.object.videos.filter(playlists__isnull=False)
        return kwargs

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        keep_archived_videos = 'keep_archived_videos' in request.POST

        messages.success(self.request, 'Channel videos deletion queued')
        tasks.delete_channel_videos.delay(pk=self.object.pk, keep_archived_videos=keep_archived_videos)

        return HttpResponseRedirect(self.object.get_absolute_url())


class ChannelRescanView(PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, DetailView):
    model = Channel
    permission_required = ['vidar.view_channel']

    def get(self, *args, **kwargs):
        channel = self.get_object()

        if channel.index_videos or channel.index_shorts or channel.index_livestreams:
            messages.success(self.request, f'Indexing {channel} now')

            tasks.trigger_channel_scanner_tasks(channel=channel)
        else:
            messages.info(self.request, 'Channel is not set to index anything. Enable indexing first.')

        return helpers.redirect_next_or_obj(self.request, channel)


class ChannelIndexOnlyView(PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, UpdateView):
    model = Channel
    form_class = forms.ChannelIndexingForm
    permission_required = ['vidar.view_channel']
    template_name = 'vidar/channel_indexing_form.html'

    def form_valid(self, form):
        channel = self.get_object()
        if channel.index_videos or channel.index_shorts or channel.index_livestreams:
            limit = form.cleaned_data['limit']
            msg = f'Indexing {channel} now'
            if limit:
                msg = f"{msg} up to {limit} items."
            messages.success(self.request, msg)
            tasks.fully_index_channel.delay(pk=channel.pk, limit=limit)
        return redirect(channel)


@user_passes_test(lambda u: u.has_perms(['vidar.change_channel']))
def channel_alter_integer(request, pk):
    channel = get_object_or_404(Channel, pk=pk)
    direction = request.GET.get('direction', 'increment')
    field = request.GET['field']
    orig_value = getattr(channel, field)
    if request.method == 'POST':

        value = orig_value
        if direction == 'increment':
            value = F(field) + 1
        elif value and direction == 'decrement':
            value = F(field) - 1
        setattr(channel, field, value)
        channel.save(update_fields=[field])
        channel.refresh_from_db()
    field_value = getattr(channel, field)
    log.debug(f'{channel.id=} {field=} {direction=} {request.method=} {orig_value=} {field_value=}')
    return HttpResponse(str(field_value))


class ChannelLivePlaylistsView(PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, DetailView):
    model = Channel
    permission_required = ['vidar.view_channel', 'vidar.view_playlist']
    template_name = 'vidar/channel_playlists_live.html'

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.live_playlists = YTDLPInteractor.channel_playlists(self.object.provider_object_id)
        if not self.live_playlists:
            messages.error(request, 'Channel has no playlists')
            return redirect(self.object)
        return super().dispatch(request=request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['playlists'] = self.live_playlists['entries']
        mirroring_playlists_form = forms.ChannelMirroringPlaylistsForm(instance=self.object)
        if self.request.method == 'POST':
            mirroring_playlists_form = forms.ChannelMirroringPlaylistsForm(self.request.POST, instance=self.object)
            if mirroring_playlists_form.is_valid():
                mirroring_playlists_form.save()
        kwargs['mirroring_playlists_form'] = mirroring_playlists_form
        return kwargs

    def post(self, *args, **kwargs):
        return self.get(*args, **kwargs)


def generate_crontab(request):

    hours = None
    playlist = None
    channel = None
    field = request.GET.get('field', 'upload_date')

    if pid := request.GET.get('playlist'):
        playlist = get_object_or_404(Playlist, id=pid)
        hours = [14, 15, 16, 17]

    if cid := request.GET.get('channel'):
        channel = get_object_or_404(Channel, id=cid)

    if request.GET.get('type') == 'weekly':

        day_of_week = None
        if channel:
            base_day_of_week = statistics_helpers.most_common_date_weekday(queryset=channel.videos, date_field=field)
            day_of_week = helpers.convert_to_next_day_of_week(base_day_of_week)
        elif playlist:
            day_of_week = statistics_helpers.most_common_date_weekday(queryset=playlist.videos, date_field=field)

        return HttpResponse(crontab_services.generate_weekly(hour=hours, day_of_week=day_of_week))

    elif request.GET.get('type') == 'monthly':

        day_of_month = None
        if channel:
            day_of_month = statistics_helpers.most_common_date_day_of_month(queryset=channel.videos, date_field=field)
        elif playlist:
            day_of_month = statistics_helpers.most_common_date_day_of_month(queryset=playlist.videos, date_field=field)

        return HttpResponse(crontab_services.generate_monthly(hour=hours, day=day_of_month))

    elif request.GET.get('type') == 'biyearly':
        return HttpResponse(crontab_services.generate_biyearly(hour=hours))

    elif request.GET.get('type') == 'yearly':
        return HttpResponse(crontab_services.generate_yearly(hour=hours))

    elif request.GET.get('type') == 'hourly':
        return HttpResponse(utils.generate_balanced_crontab_hourly())

    return HttpResponse(crontab_services.generate_daily(hour=hours))


class CrontabCatchupView(PermissionRequiredMixin, FormView):
    form_class = forms.CrontabCatchupForm
    template_name = 'vidar/crontab_catchup.html'
    permission_required = ['vidar.change_channel']

    def form_valid(self, form):
        channels_queued, playlists_queued = form.scan()
        messages.success(
            self.request,
            f'Channel and Playlists crontabs scanners ran for every 5 minutes between the '
            f'datetimes supplied finding {len(channels_queued)} channels '
            f'and {len(playlists_queued)} to index.',
        )
        return redirect('vidar:channel-index')


class ChannelVideosManagerView(PermissionRequiredMixin, UseProviderObjectIdMatchingMixin, DetailView):
    model = Channel
    template_name = 'vidar/channel_videos_manager.html'
    permission_required = ['vidar.view_channel', 'vidar.delete_video']

    def post(self, request, **kwargs):
        self.object = self.get_object()
        button_clicked = self.request.POST['submit']
        keep_record = button_clicked == 'Delete file but keep video in system'
        countdown = 0
        for video in self.object.videos.all():
            if f"video-{video.pk}" in request.POST:

                if button_clicked in ['Delete file but keep video in system', 'Delete video from system entirely']:

                    if button_clicked == 'Delete video from system entirely' and 'block' in self.request.POST:
                        video_services.block(video=video)

                    video_services.delete_video(video=video, keep_record=keep_record)

                elif button_clicked == 'Fix file paths':
                    if video.file:
                        tasks.rename_video_files.delay(pk=video.pk)
                    else:
                        messages.error(request, f'{video=} has no file to rename.')

                elif button_clicked == 'Load SponsorBlock Skips':
                    if video.file:
                        tasks.load_sponsorblock_data.apply_async(args=[video.id], countdown=countdown)
                        countdown += 5

        return redirect('vidar:channel-videos-manager', pk=self.object.pk)

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)

        qs = self.object.videos.all()

        if show := self.request.GET.get('show'):
            if show == 'all':
                pass
            elif show == 'missing':
                qs = qs.filter(file='')
            elif show == 'archived':
                qs = qs.exclude(file='')
        else:
            qs = qs.exclude(file='')

        if ordering := self.request.GET.get('o'):
            qs = qs.exclude(file='').order_by(ordering)

        if query := self.request.GET.get('q'):
            qs = qs.filter(title__icontains=query)

        kwargs['videos_list'] = qs

        kwargs['all_shorts_count'] = qs.filter(is_short=True).count()
        kwargs['all_livestreams_count'] = qs.filter(is_livestream=True).count()
        kwargs['all_videos_count'] = qs.filter(is_video=True).count()

        kwargs['archived_shorts_count'] = qs.filter(is_short=True).exclude(file='').count()
        kwargs['archived_livestreams_count'] = qs.filter(is_livestream=True).exclude(file='').count()
        kwargs['archived_videos_count'] = qs.filter(is_video=True).exclude(file='').count()

        kwargs['missing_shorts_count'] = qs.filter(is_short=True, file='').count()
        kwargs['missing_livestreams_count'] = qs.filter(is_livestream=True, file='').count()
        kwargs['missing_videos_count'] = qs.filter(is_video=True, file='').count()

        return kwargs


class VideoListView(PermissionRequiredMixin, RequestBasedQuerysetFilteringMixin, ListView):
    model = Video
    permission_required = ['vidar.access_vidar']
    paginate_by = 10
    ordering = ['-upload_date', '-inserted']
    RequestBaseFilteringDefaultFields = ['title', 'provider_object_id']

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data(*args, **kwargs)

        if self.request.user.is_authenticated:
            wlp = Playlist.get_user_watch_later(user=self.request.user)
            kwargs['watch_later_videos'] = wlp.videos.values_list('pk', flat=True)

        qs = self.get_queryset()
        kwargs['total_videos_count'] = qs.count()
        seconds = qs.aggregate(sumd=Sum('duration'))['sumd'] or 0
        kwargs['total_videos_duration_sum'] = timezone.timedelta(seconds=seconds)

        dl_qs = qs.exclude(file='')
        kwargs['downloaded_videos_count'] = dl_qs.count()
        seconds = dl_qs.aggregate(sumd=Sum('duration'))['sumd'] or 0
        kwargs['downloaded_videos_duration_sum'] = timezone.timedelta(seconds=seconds)

        kwargs['blocked_video_count'] = VideoBlocked.objects.all().count()

        kwargs.update(
            paginator_helper(
                context_key='object_list',
                queryset=self.get_queryset(),
                limit=self.paginate_by,
                params=self.request.GET,
            )
        )
        return kwargs

    def get_template_names(self):
        if not self.request.user.is_authenticated:
            return ['vidar/video_list_public.html']
        return super().get_template_names()

    def get_queryset(self):
        qs = super().get_queryset()

        if 'starred' in self.request.GET:
            qs = qs.exclude(starred__isnull=True).order_by('-starred')

        if 'watched' in self.request.GET:
            qs = qs.exclude(watched__isnull=True).order_by('-watched')

        if 'missing' in self.request.GET:
            qs = qs.filter(file='')

        elif 'archived' in self.request.GET:
            qs = qs.exclude(file='')

        if ordering := self.request.GET.get('o'):
            if ordering.endswith(('filesize', 'file_size', 'downloaded')):
                qs = qs.exclude(file='')
            elif ordering.endswith('last_privacy_status_check'):
                qs = qs.exclude(last_privacy_status_check__isnull=True)

        if selected_date := self.request.GET.get('date'):
            qs = qs.filter(date_downloaded__date=selected_date)

        if upload_date := self.request.GET.get('upload_date'):
            qs = qs.filter(upload_date=upload_date)

        if date_downloaded := self.request.GET.get('date_downloaded'):
            qs = qs.filter(date_downloaded__date=date_downloaded)

        if quality := self.request.GET.get('quality'):
            qs = qs.filter(quality=quality)

        if channel_id := self.request.GET.get('channel'):
            if channel_id.lower() in ['none', '0']:
                qs = qs.filter(channel__isnull=True)
            else:
                qs = qs.filter(channel_id=channel_id)

        if year := self.request.GET.get('year'):
            qs = qs.filter(upload_date__year=year)
        if month := self.request.GET.get('month'):
            qs = qs.filter(upload_date__month=month)

        if self.request.GET.get('view') == "audio":
            return qs.exclude(audio='')
        if not self.request.user.is_authenticated:
            return qs.filter(provider_object_id__in=helpers.unauthenticated_permitted_videos(self.request))
        return qs

    def get_paginate_by(self, queryset):
        return self.request.GET.get('limit') or self.paginate_by

    def get_ordering(self):
        if ordering := self.request.GET.get('o'):
            direction = '-' if ordering.startswith('-') else ''
            ordering = ordering[1:] if direction else ordering
            try:
                if ordering == 'added':
                    return [f'{direction}date_added_to_system']
                if ordering == 'downloaded':
                    return [f'{direction}date_downloaded']
                if ordering not in ['filesize', 'fs']:
                    # Ensure the field supplied actually exists on Video.
                    self.model._meta.get_field(ordering)
                return [f'{direction}{ordering}']
            except FieldDoesNotExist:
                pass
        return super().get_ordering()


class AllVideoStatistics(PermissionRequiredMixin, TemplateView):
    permission_required = ['vidar.view_index_download_stats']
    template_name = 'vidar/statistics.html'

    def get_queryset(self):
        return Video.objects.all().order_by('-upload_date', '-inserted')

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data(*args, **kwargs)

        def get_period_counters(field):
            periods = {}
            total_videos_archived_today_counter = 0
            total_videos_uploaded_today_counter = 0
            total_videos_archived_filesize = 0

            for day_num in range(0, 7):
                days_ago = timezone.localdate() - timezone.timedelta(days=day_num)

                videos_uploaded_today_count = Video.objects.all().filter(**{f"{field}": days_ago}).count()

                videos_archived_today = Video.objects.archived().filter(**{f"{field}": days_ago})

                videos_archived_today_count = videos_archived_today.count()
                videos_archived_today_size = videos_archived_today.aggregate(sumd=Sum('file_size'))['sumd'] or 0

                periods[days_ago] = videos_archived_today_count, videos_archived_today_size, videos_uploaded_today_count

                total_videos_archived_filesize += videos_archived_today_size
                total_videos_archived_today_counter += videos_archived_today_count
                total_videos_uploaded_today_counter += videos_uploaded_today_count

            periods['Total'] = (
                total_videos_archived_today_counter,
                total_videos_archived_filesize,
                total_videos_uploaded_today_counter,
            )
            return periods

        kwargs['upload_date_period_counters'] = get_period_counters('upload_date')
        kwargs['date_downloaded_period_counters'] = get_period_counters('date_downloaded__date')

        kwargs['average_day_download_size'] = (
            Video.objects.archived()
            .annotate(dl=TruncDate('date_downloaded'))
            .values('dl')
            .annotate(fs=Sum('file_size'))
            .aggregate(Avg('fs'))['fs__avg']
            or 0
        )

        kwargs['average_year_date_downloaded_size'] = (
            Video.objects.archived()
            .annotate(dl=TruncYear('date_downloaded'))
            .order_by('-dl')
            .values('dl')
            .annotate(fs=Sum('file_size'), count=Count('id'))
        )

        kwargs['average_year_upload_date_size'] = (
            Video.objects.archived()
            .annotate(dl=TruncYear('upload_date'))
            .order_by('-dl')
            .values('dl')
            .annotate(fs=Sum('file_size'), count=Count('id'))
        )

        kwargs['average_ddl_week_size'] = (
            Video.objects.archived()
            .annotate(dl=TruncWeek('date_downloaded'))
            .order_by('-dl')
            .values('dl')
            .annotate(fs=Sum('file_size'), count=Count('id'))
        )

        kwargs['total_videos_count'] = self.get_queryset().count()
        kwargs['downloaded_videos_count'] = self.get_queryset().exclude(file='').count()
        return kwargs


class VideoRequestView(PermissionRequiredMixin, CreateView):
    model = Video
    form_class = forms.VideoDownloaderForm
    # success_url = reverse_lazy("vidar:video-index")
    permission_required = ['vidar.add_video']

    def get(self, request, *args, **kwargs):
        if url := self.request.GET.get('url'):
            ytid = utils.get_video_id_from_url(url)
            if video := Video.objects.filter(provider_object_id=ytid):
                return redirect(video.first())
        return super().get(*args, request=request, **kwargs)

    def get_initial(self):
        if url := self.request.GET.get('url'):
            return {'provider_object_id': utils.get_video_id_from_url(url)}
        return super().get_initial()

    def form_valid(self, form):
        if not self.request.user.is_authenticated:
            helpers.unauthenticated_allow_view_video(self.request, form.cleaned_data['provider_object_id'])
        return super().form_valid(form=form)

    def form_invalid(self, form):
        if possible_ytid := form.data.get('provider_object_id'):
            if ytid := utils.get_video_id_from_url(possible_ytid):
                if video := Video.objects.filter(provider_object_id=ytid):
                    if not self.request.user.is_authenticated:
                        helpers.unauthenticated_allow_view_video(self.request, ytid)
                    return redirect(video.first())
        return super().form_invalid(form=form)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class VideoDeleteView(PermissionRequiredMixin, DeleteView):
    model = Video
    success_url = reverse_lazy("vidar:video-index")
    permission_required = ["vidar.delete_video"]

    def get(self, *args, **kwargs):
        resp = super().get(*args, **kwargs)
        if self.object.prevent_deletion:
            messages.error(self.request, 'Video is blocked from deletion.')
            return redirect(self.object)
        return resp

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        if channel := self.object.channel:
            latest_videos = channel.videos.all()[: channel.scanner_limit]
            if self.object in latest_videos and channel.index_videos and channel.download_videos:
                messages.error(
                    self.request,
                    "Warning: This video is still within the scan limit range and it will "
                    "re-download on the next scan depending on settings.",
                )
        return kwargs

    def form_valid(self, form):

        if 'block' in self.request.POST:
            video_services.block(video=self.object)

        if 'delete_audio_only' in self.request.POST:
            if self.object.audio:
                self.object.convert_to_audio = False
                self.object.audio.delete()
                messages.success(self.request, 'Audio file deleted.')
            else:
                messages.error(self.request, 'Audio file does not exist.')
            return redirect(self.object)

        # If the video has no associated channel and no playlist, then it was manually added.
        # Properly delete it.
        delete_entirely = 'delete_entirely' in self.request.POST
        if (not self.object.channel_id and not self.object.playlists.exists()) or delete_entirely:
            video_services.delete_video(video=self.object, keep_record=False)
            if self.object.channel:
                return redirect(self.object.channel)
            return redirect("vidar:video-index")

        video_services.delete_video(video=self.object, keep_record=True)
        return helpers.redirect_next_or_obj(self.request, self.object)


class VideoDetailView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_video']
    slug_url_kwarg = 'provider_object_id'
    slug_field = 'provider_object_id'

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['highlights'] = self.object.highlights.filter(source=Highlight.Sources.USER)
        kwargs['chapters'] = self.object.highlights.filter(source=Highlight.Sources.CHAPTERS)
        if playlist_id := self.request.GET.get('playlist'):
            kwargs['playlist'] = get_object_or_404(Playlist, id=playlist_id)
        if self.request.user.is_authenticated:
            time = timezone.now() - timezone.timedelta(days=14)
            qs = UserPlaybackHistory.objects.filter(user=self.request.user, video=self.object, inserted__gt=time)
            if qs.exists():
                if self.object.duration > 120:
                    ninty_percent_complete = int(self.object.duration * 0.9)
                    current_seconds = qs.first().seconds
                    if current_seconds < ninty_percent_complete:
                        kwargs['user_playback_currenttime_seconds'] = current_seconds
        return kwargs

    def has_permission(self):
        if not self.request.user.is_authenticated:
            obj = self.get_object()
            return helpers.unauthenticated_check_if_can_view_video(self.request, obj.provider_object_id)
        return super().has_permission()


class VideoWatchedView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_video']

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.watched = timezone.now()
        self.object.save()
        for p in self.object.playlists.filter(remove_video_from_playlist_on_watched=True):
            p.videos.remove(self.object)
        timer = timezone.localtime(self.object.watched)
        output = Template('{{ timer }}').render(context=Context({'timer': timer}))
        return HttpResponse(output)


class VideoUpdateView(PermissionRequiredMixin, UpdateView):
    model = Video
    form_class = forms.VideoUpdateForm
    permission_required = ['vidar.change_video']


class VideoBooleanSwapper(PermissionRequiredMixin, HTMXIconBooleanSwapper, UpdateView):
    model = Video
    fields = ['title_locked', 'description_locked', 'prevent_deletion']
    permission_required = ['vidar.change_video']


class VideoDatetimeSwapper(PermissionRequiredMixin, HTMXIconBooleanSwapper, UpdateView):
    model = Video
    fields = ['starred']
    permission_required = ['vidar.change_video']

    HTMX_ICON_TRUE = "fa-solid fa-star"
    HTMX_ICON_FALSE = "fa-regular fa-star"

    def htmx_swapper_calculate_new_field_value(self, field_name, current_value):
        if field_name == 'starred':
            if not current_value:
                return timezone.now()
            return None
        return super().htmx_swapper_calculate_new_field_value(field_name, current_value)

    def htmx_swapper_check_value_is_valid(self, field_name, value):
        if field_name == 'starred':
            return
        return super().htmx_swapper_check_value_is_valid(field_name=field_name, value=value)


class VideoVideoDownloadErrorDetailView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_videodownloaderror']
    template_name = 'vidar/video_download_error.html'

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()  # type: Video
        if 'delete_errors' in request.POST:
            qs = self.object.download_errors.all()
            count = qs.count()
            qs.delete()
            messages.success(request, f'Deleted {count} error entries.')
        return helpers.redirect_next_or_obj(request, self.object)


@user_passes_test(lambda u: u.has_perms(['vidar.add_video']))
def download_video(request, pk, quality):
    if isinstance(pk, Video):
        pk = pk.pk

    Video.objects.filter(pk=pk).update(force_download=True, requested_max_quality=quality == 0)

    obj = Video.objects.get(pk=pk)

    messages.success(request, f'{obj} queued for download.')
    tasks.download_provider_video.delay(
        pk=obj.pk,
        quality=quality,
        task_source='Manual Download Selection',
    )

    return helpers.redirect_next_or_obj(request, "vidar:video-index")


@user_passes_test(lambda u: u.has_perms(['vidar.add_comment']))
def download_video_comments(request, pk):
    if isinstance(pk, Video):
        pk = pk.pk

    obj = Video.objects.get(pk=pk)

    if request.method == 'POST':
        messages.success(request, f'{obj} comments queued for download.')
        all_comments = 'Get All Comments' in request.POST.get('download-comments')
        tasks.download_provider_video_comments.delay(pk=obj.pk, all_comments=all_comments)

    return HttpResponseRedirect(obj.get_absolute_url() + '#yt-comments')


@user_passes_test(lambda u: u.has_perms(['vidar.change_video']))
def video_convert_to_mp3(request, pk):
    obj = get_object_or_404(Video, pk=pk)
    messages.success(request, f'{obj} queued for conversion.')
    tasks.convert_video_to_audio.delay(obj.pk)

    return helpers.redirect_next_or_obj(request, obj)


@user_passes_test(lambda u: u.has_perms(['vidar.add_comment']))
def add_video_comment(request, pk):
    video = get_object_or_404(Video, pk=pk)
    note = None
    if request.method == 'POST' and request.POST.get('comment'):
        note = video.notes.create(
            note=request.POST['comment'], user=request.user if request.user.is_authenticated else None
        )
    if request.is_ajax():
        if note:
            return JsonResponse({'inserted': note.inserted.isoformat(), 'text': note.note.replace('\n', '<br />')})
        else:
            return JsonResponse({})

    if request.method == 'POST' and request.POST.get('comment'):
        messages.success(request, 'Note added Thank-You')

    return redirect(video)


@user_passes_test(lambda u: u.has_perms(['vidar.add_channel']))
def video_sub_to_channel(request, pk):
    video = get_object_or_404(Video, pk=pk)
    channel_provider_object_id = video.channel_provider_object_id
    if not channel_provider_object_id:
        data = YTDLPInteractor.video_details(url=video.url)
        video.channel_provider_object_id = data['channel_id']
        video.save()
    url = reverse_lazy('vidar:channel-create')
    return HttpResponseRedirect(f"{url}?channel={video.channel_provider_object_id}&index=False")


@user_passes_test(lambda u: u.has_perms(['vidar.view_video']))
@csrf_exempt
def video_save_user_current_view_time(request, pk):

    seconds = int(request.POST['current_time'])
    if seconds:
        qs = UserPlaybackHistory.objects.filter(
            video_id=pk,
            user_id=request.user.id,
            updated__date=timezone.localdate(),
        )

        try:
            obj = qs.latest()

            diff_seconds = seconds - obj.seconds
            diff_time = timezone.now() - obj.updated

            # If the difference between the last log's seconds and now is greater than 120 seconds,
            #   AND the amount of time between the two logs is more than X time old, then create a new one.
            # So in this case, if the user hasn't updated this log entry (isn't watching) for over 10 minutes
            #   AND the seconds has gone from say 500 seconds to 0 seconds, then the browser delayed loading
            #   the video file and sent the save-watch-time log entry as 0 seconds despite the video_detail.html
            #   having told the player to load to the currentTime of 500
            if diff_seconds < -120 and diff_time > timezone.timedelta(minutes=10):
                UserPlaybackHistory.objects.create(
                    video_id=pk, user_id=request.user.id, seconds=seconds, playlist_id=request.POST.get('playlist')
                )
            else:
                obj.seconds = seconds
                obj.playlist_id = request.POST.get('playlist')
                obj.save()

        except UserPlaybackHistory.DoesNotExist:
            UserPlaybackHistory.objects.create(
                video_id=pk, user_id=request.user.id, seconds=seconds, playlist_id=request.POST.get('playlist')
            )

    return HttpResponse('ok')


class VideoUpdateAvailableQualitiesView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_video']

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        try:
            tasks.update_video_details.delay(pk=self.object.pk).get()
            messages.success(request, 'Video qualities updated successfully')
        except:  # noqa: E722
            log.exception('Failure to check and update video status and details from view')
            messages.error(request, 'Failure to obtain video qualities.')

        return helpers.redirect_next_or_obj(request, self.object)


class VideoDownloadErrorListView(PermissionRequiredMixin, ListView):
    model = VideoDownloadError
    permission_required = ['vidar.view_videodownloaderror']


class AddVideoToPlaylistView(PermissionRequiredMixin, CreateView):
    model = PlaylistItem
    fields = ['playlist']
    permission_required = ['vidar.add_playlistitem']

    def get_video(self):
        return get_object_or_404(Video, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        kwargs = super(AddVideoToPlaylistView, self).get_context_data(**kwargs)
        kwargs['video'] = self.get_video()
        kwargs['playlists'] = Playlist.objects.all()
        if 'show-all' not in self.request.GET:
            kwargs['playlists'] = Playlist.objects.filter(provider_object_id='')
        return kwargs

    def get_success_url(self):
        return reverse_lazy('vidar:video-playlists', args=[self.kwargs['pk']])

    def form_valid(self, form):
        playlist = form.cleaned_data['playlist']
        video = self.get_video()

        if not playlist.videos.filter(pk=video.pk).exists():
            playlist.playlistitem_set.create(
                video=video, manually_added=True, provider_object_id=video.provider_object_id
            )
            messages.success(self.request, 'Video added to playlist')
            return redirect('vidar:video-playlists', pk=video.pk)

        messages.error(self.request, 'Video already exists on playlist')
        return redirect('vidar:video-playlists-add', pk=video.pk)


class AddVideoToWatchLaterPlaylistView(PermissionRequiredMixin, DetailView):
    model = Video
    fields = ['playlist']
    permission_required = ['vidar.access_watch_later_playlist']

    def dispatch(self, request, *args, **kwargs):
        if not self.has_permission():
            return self.handle_no_permission()
        playlist = Playlist.get_user_watch_later(user=request.user)
        video = self.get_object()

        if playlist.videos.filter(pk=video.pk).exists():
            playlist.videos.remove(video)
            return HttpResponse('<i class="fa fa-2xl fa-plus"></i>')

        wl_playlist = None
        if pid := request.GET.get('playlist'):
            wl_playlist = Playlist.objects.get(pk=pid)

        playlist.playlistitem_set.create(
            video=video,
            manually_added=True,
            provider_object_id=video.provider_object_id,
            wl_playlist=wl_playlist,
        )
        return HttpResponse('<i class="fa fa-xl fa-minus"></i>')


class RemoveVideoFromPlaylistView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.delete_playlistitem']

    def get(self, request, *args, **kwargs):
        video = self.get_object()
        playlist = get_object_or_404(Playlist, pk=kwargs['playlist_pk'])
        if playlist.playlistitem_set.filter(
            Q(missing_from_playlist_on_provider=True) | Q(manually_added=True), video=video
        ).exists():
            playlist.videos.remove(video)
        else:
            messages.error(
                request,
                'Video on playlist and not missing from youtube live playlist, '
                'removing from playlist would cause it to redownload automatically',
            )
        return redirect(playlist)


class VideoRelatedVideosView(PermissionRequiredMixin, RequestBasedCustomQuerysetFilteringMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_video']
    template_name = 'vidar/video_related_videos.html'

    def post(self, *args, **kwargs):

        self.object = self.get_object()  # type: Video

        selected_video = Video.objects.get(pk=self.request.POST['related_id'])

        if selected_video in self.object.related.all():
            self.object.related.remove(selected_video)
        else:
            self.object.related.add(selected_video)

        return self.get(*args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data(*args, **kwargs)

        kwargs['related_video_pks'] = self.object.related.all().values_list('pk', flat=True)

        qs = Video.objects.exclude(pk=self.kwargs['pk'])
        qs = self.apply_queryset_filtering(qs, ['title', 'description', 'provider_object_id'])

        # if 'show-all' not in self.request.GET:
        #     qs = qs.filter(related__isnull=False)
        if 'related' in self.request.GET:
            qs = qs.filter(id__in=kwargs['related_video_pks'])

        qs = qs.order_by('-related')

        kwargs.update(
            paginator_helper(
                context_key='object_list',
                queryset=qs,
                params=self.request.GET,
                limit=10,
            )
        )
        return kwargs


class DisableVideoFromPlaylistView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.delete_playlistitem']

    def get(self, request, *args, **kwargs):
        video = self.get_object()
        playlist = get_object_or_404(Playlist, pk=kwargs['playlist_pk'])
        playlist.playlistitem_set.filter(video=video).update(download=Q(download=False))
        return redirect(playlist)


class MoveVideoUpInPlaylistView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.change_playlistitem']

    def get(self, request, pk, playlist_pk, *args, **kwargs):
        pli = get_object_or_404(PlaylistItem, playlist_id=playlist_pk, video_id=pk)
        if request.GET.get('direction') == 'down':
            pli.display_order += 1
            messages.success(request, 'Video moved down')
        else:
            pli.display_order -= 1
            messages.success(request, 'Video moved up')
        pli.save()
        return redirect(pli.playlist)


class VideoPlaylistsListView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_video']
    template_name = 'vidar/video_playlists.html'


class VideoDurationSkipsListView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_video', 'vidar.view_durationskip']
    template_name = 'vidar/durationskip_list.html'

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['main_categories'] = ['sponsor', 'selfpromo', 'outro', 'interaction', 'poi_highlight']
        kwargs['extra_categories'] = ['intro', 'preview', 'music_offtopic', 'filler']
        return kwargs

    def post(self, *args, **kwargs):
        self.object = self.get_object()  # type: Video
        if 'skip' in self.request.POST:
            self.object.duration_skips.filter(id=self.request.POST['skip']).delete()

        elif 'start' in self.request.POST:
            form = forms.DurationSkipForm(
                self.request.POST, existing_skips=self.object.duration_skips.all().values_list('start', 'end')
            )
            if form.is_valid():
                form.instance.video = self.object
                form.instance.user = self.request.user
                form.save()
            else:
                for f, msgs in form.errors.items():
                    for msg in msgs:
                        messages.error(self.request, msg)

        elif 'load-sb' in self.request.POST:
            status = video_services.load_live_sponsorblock_video_data_into_duration_skips(
                video=self.object,
                categories=self.request.POST.getlist('category[]'),
                user=self.request.user,
            )
            if status is None:
                messages.error(self.request, 'No records in SponsorBlock')
            else:
                messages.info(self.request, f'{len(status)} records loaded from SponsorBlock.')

        return redirect('vidar:video-duration-skip-list', pk=self.object.id)


class VideoHighlightsListView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_video', 'vidar.view_highlight']
    template_name = 'vidar/video_highlight_list.html'

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['highlights'] = self.object.highlights.filter(source=Highlight.Sources.USER)
        return kwargs

    def post(self, *args, **kwargs):
        self.object = self.get_object()  # type: Video
        if 'highlight' in self.request.POST:
            self.object.highlights.filter(id=self.request.POST['highlight'], source=Highlight.Sources.USER).delete()
        elif 'point' in self.request.POST:
            form = forms.HighlightForm(self.request.POST)
            if form.is_valid():
                form.instance.video = self.object
                form.instance.user = self.request.user
                form.instance.source = Highlight.Sources.USER
                form.save()
            else:
                for f, msgs in form.errors.items():
                    for msg in msgs:
                        messages.error(self.request, msg)

        return redirect('vidar:video-highlight-list', pk=self.object.id)


class HighlightUpdateView(PermissionRequiredMixin, UpdateView):
    model = Highlight
    form_class = forms.HighlightForm
    permission_required = ['vidar.view_video', 'vidar.change_highlight']

    def get_queryset(self):
        return super().get_queryset().filter(source=Highlight.Sources.USER)


class VideoChaptersListView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.view_video', 'vidar.view_chapter']
    template_name = 'vidar/video_chapter_list.html'

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['chapters'] = self.object.highlights.filter(source=Highlight.Sources.CHAPTERS)
        return kwargs

    def post(self, *args, **kwargs):
        self.object = self.get_object()  # type: Video
        if 'chapter' in self.request.POST:
            self.object.highlights.filter(id=self.request.POST['chapter'], source=Highlight.Sources.CHAPTERS).delete()
        elif 'point' in self.request.POST:
            form = forms.ChapterForm(self.request.POST)
            if form.is_valid():
                form.instance.video = self.object
                form.instance.user = self.request.user
                form.instance.source = Highlight.Sources.CHAPTERS
                form.save()
            else:
                for f, msgs in form.errors.items():
                    for msg in msgs:
                        messages.error(self.request, msg)

        return redirect('vidar:video-chapter-list', pk=self.object.id)


class ChapterUpdateView(PermissionRequiredMixin, UpdateView):
    model = Highlight
    form_class = forms.ChapterForm
    permission_required = ['vidar.view_video', 'vidar.change_chapter']
    template_name = 'vidar/chapter_form.html'

    def get_queryset(self):
        return super().get_queryset().filter(source=Highlight.Sources.CHAPTERS)


class VideoManageView(PermissionRequiredMixin, DetailView):
    model = Video
    permission_required = ['vidar.change_video']
    template_name = 'vidar/video_manage.html'

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)
        kwargs['video_form'] = forms.VideoManualEditor(instance=self.object)
        kwargs['does_file_need_fixing'] = video_services.does_file_need_fixing(video=self.object)
        kwargs['is_object_locked'] = celery_helpers.is_object_locked(obj=self.object)
        kwargs['is_blocked'] = video_services.is_blocked(self.object.provider_object_id)
        kwargs['extrafile_form'] = forms.ExtraFileForm()
        if 'extrafile' in self.request.POST:
            extrafile_form = forms.ExtraFileForm(self.request.POST, self.request.FILES)
            extrafile_form.is_valid()
            kwargs['extrafile_form'] = extrafile_form
        if self.object.file:
            ext = self.object.file.name.rsplit('.', 1)[-1]
            new_full_filepath, new_storage_path = video_services.generate_filepaths_for_storage(
                video=self.object,
                ext=ext,
            )
            kwargs['expected_video_filepath'] = new_storage_path
            kwargs['current_video_filepath_already_exists'] = storages.vidar_storage.exists(self.object.file.name)
            kwargs['expected_video_filepath_already_exists'] = storages.vidar_storage.exists(new_storage_path)
        else:
            kwargs['expected_video_filepath'] = 'No file attached to video'
        return kwargs

    def post(self, request, pk):
        url_anchor = ''
        self.object = self.get_object()
        if 'fix-filepaths' in request.POST:
            if self.object.file:
                tasks.rename_video_files.delay(pk=pk)
            else:
                messages.error(request, f'{self.object} has no file attached to rename.')

        if 'expected-filepaths-are-correct' in request.POST:
            if self.object.file:
                ext = self.object.file.name.rsplit('.', 1)[-1]
                new_full_filepath, new_storage_path = video_services.generate_filepaths_for_storage(
                    video=self.object,
                    ext=ext,
                )
                self.object.file.name = str(new_storage_path)
                self.object.save()

        if 'release-object-lock' in request.POST:
            celery_helpers.object_lock_release(obj=self.object)
            if celery_helpers.is_object_locked(obj=self.object):
                messages.error(request, 'Object lock failed to release')
            else:
                messages.success(request, 'Object lock released successfully')

        if 'save-fields' in request.POST:
            form = forms.VideoManualEditor(request.POST, instance=self.object)
            form.save()
        if 'convert-to-mp4' in request.POST:
            tasks.trigger_convert_video_to_mp4.delay(pk=self.object.id)
            messages.success(self.request, 'Video sent for rendering, give it time.')
        if 'extrafile' in request.POST:
            form = forms.ExtraFileForm(request.POST, self.request.FILES)
            if form.is_valid():
                form.instance.video = self.object
                form.save()
            url_anchor = 'extrafiles'
        if 'extrafile-delete' in request.POST:
            efid = request.POST['extrafile-id']
            ef = ExtraFile.objects.get(id=efid)
            ef.file.delete(save=False)
            ef.delete()
            messages.success(request, 'Extra File Deleted')
            url_anchor = 'extrafiles'
        if 'retry-processing' in request.POST:
            download_data = self.object.system_notes['downloads'][-1]

            tasks.post_download_processing.delay(
                pk=self.object.pk,
                filepath=download_data['raw_file_path'],
                download_started=download_data['download_started'],
                download_finished=download_data['download_finished'],
                task_source='Manual video retry',
            )
        if 'unblock' in request.POST:
            video_services.unblock(self.object.provider_object_id)
        if 'block' in request.POST:
            video_services.block(video=self.object)
        if 'refresh_thumbnail' in request.POST:
            dlp_output = YTDLPInteractor.video_details(self.object.url, quiet=True)
            video_services.load_thumbnail_from_info_json(video=self.object, info_json_data=dlp_output)
        return HttpResponseRedirect(reverse('vidar:video-manage', args=[pk]) + f'#{url_anchor}')


class PlaylistListView(PermissionRequiredMixin, RequestBasedQuerysetFilteringMixin, ListView):
    model = Playlist
    queryset = (
        Playlist.objects.all()
        .annotate(
            daily_crontab_first=Case(
                When(title='Watch Later', then=2), When(crontab__endswith=' * * *', then=1), default=0
            )
        )
        .order_by('-daily_crontab_first', 'channel', 'title')
    )
    permission_required = ['vidar.view_playlist']

    RequestBaseFilteringDefaultFields = ['title', 'description', 'channel__name']

    def get_queryset(self):
        qs = super().get_queryset()

        if channel_id := self.request.GET.get('channel'):
            qs = qs.filter(Q(channel_provider_object_id=channel_id) | Q(channel_id=channel_id))
        # elif 'hidden' in self.request.GET:
        #     qs = qs.filter(hidden=True)
        # elif 'q' not in self.request.GET:
        #     qs = qs.filter(hidden=False)

        if 'custom' in self.request.GET:
            qs = qs.filter(provider_object_id='')

        return qs

    def get_ordering(self):
        if ordering := self.request.GET.get('o'):
            direction = '-' if ordering.startswith('-') else ''
            ordering = ordering[1:] if direction else ordering
            try:
                self.model._meta.get_field(ordering)
                return [f'{direction}{ordering}']
            except (FieldError, FieldDoesNotExist):
                messages.error(self.request, 'Field does not exist')
        return super().get_ordering()

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data(*args, **kwargs)

        limit = 20
        if channel_id := self.request.GET.get('channel'):
            kwargs['channel'] = get_object_or_404(Channel, Q(provider_object_id=channel_id) | Q(id=channel_id))
            limit = 100

        kwargs['playlists_with_crontab'] = Playlist.objects.exclude(crontab='')
        kwargs['playlists_with_daily_crontab'] = Playlist.objects.filter(crontab__endswith='* * *')
        kwargs['playlists_with_monthly_crontab'] = Playlist.objects.filter(crontab__endswith='* *').exclude(
            crontab__endswith='* * *'
        )

        kwargs.update(
            paginator_helper(
                context_key='object_list',
                queryset=self.object_list,
                params=self.request.GET,
                limit=limit,
            )
        )
        return kwargs


class PlaylistDetailView(PermissionRequiredMixin, DetailView):
    model = Playlist
    permission_required = ['vidar.view_playlist']

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()  # type: Playlist
        if 'convert-to-custom' in request.POST and self.object.provider_object_id:
            self.object.description = f"{self.object.description}\nOld YouTube ID: {self.object.provider_object_id}"
            self.object.provider_object_id_old = self.object.provider_object_id
            self.object.provider_object_id = ''
            self.object.save()
            self.object.playlistitem_set.update(manually_added=True)
        if 'download-video-comments' in request.POST:
            countdown = 0
            for video in self.object.videos.all():
                download_all_comments = 'download_all_comments' in request.POST
                tasks.download_provider_video_comments.apply_async(
                    args=[video.pk, download_all_comments], countdown=countdown
                )
                countdown += 67
        return redirect(self.object)

    def get_context_data(self, **kwargs):
        kwargs = super().get_context_data(**kwargs)

        qs = self.object.playlistitem_set.all()

        if 'missing' in self.request.GET:
            qs = qs.filter(video__file='')
        if 'archived' in self.request.GET:
            qs = qs.exclude(video__file='')

        if ordering := self.request.GET.get('o'):
            direction = '-' if ordering.startswith('-') else ''
            if ordering.endswith('inserted'):
                qs = qs.order_by(f'{direction}inserted')
        else:
            qs = self.object.apply_display_ordering_to_queryset(qs)

        if self.object.channel_id:
            kwargs['videos_have_single_channel'] = not self.object.videos.exclude(
                channel_id=self.object.channel_id
            ).exists()

        # If you change limit, change it in templatetags/video_tools.py def link_to_playlist_page...
        kwargs.update(
            paginator_helper(
                context_key="playlist_videos",
                queryset=qs,
                params=self.request.GET,
                limit=50,
            )
        )
        return kwargs


class PlaylistCreateView(PermissionRequiredMixin, CreateView):
    model = Playlist
    form_class = forms.PlaylistAdderForm
    # success_url = reverse_lazy("vidar:playlist-index")
    permission_required = ["vidar.add_playlist"]

    def get_initial(self):
        youtube_id = self.request.GET.get('youtube_id', '')
        return {
            'youtube_id': f"https://www.youtube.com/playlist?list={youtube_id}",
        }

    def form_valid(self, form):
        val = super().form_valid(form=form)

        if self.object.crontab:
            if self.object.crontab.endswith(' * * *'):
                matched_datetimes = crontab_services.calculate_schedule(self.object.crontab)
                messages.info(self.request, f'Playlist scanning {len(matched_datetimes)} times per day')
            else:
                matched_datetimes = crontab_services.calculate_schedule(self.object.crontab, check_month=True)
                messages.info(self.request, f'Playlist scanning {len(matched_datetimes)} times per month')

        return val


class PlaylistCustomCreateView(PermissionRequiredMixin, CreateView):
    model = Playlist
    form_class = forms.PlaylistManualAddForm
    permission_required = ["vidar.add_playlist"]

    def get_initial(self):
        initial = super().get_initial()
        if channel_id := self.request.GET.get('channel'):
            initial['channel'] = get_object_or_404(Channel, id=channel_id)
        return initial

    def get_context_data(self, **kwargs):
        kwargs['custom_playlist'] = True
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form=form)


class PlaylistEditView(PermissionRequiredMixin, UpdateView):
    model = Playlist
    form_class = forms.PlaylistEditForm
    permission_required = ["vidar.change_playlist"]

    def get_form_class(self):
        if not self.object.provider_object_id:
            return forms.PlaylistManualEditForm
        return super().get_form_class()

    def form_valid(self, form):
        val = super().form_valid(form=form)

        if self.object.crontab:
            if self.object.crontab.endswith(' * * *'):
                matched_datetimes = crontab_services.calculate_schedule(self.object.crontab)
                messages.info(self.request, f'Playlist scanning {len(matched_datetimes)} times per day')
            else:
                matched_datetimes = crontab_services.calculate_schedule(self.object.crontab, check_month=True)
                messages.info(self.request, f'Playlist scanning {len(matched_datetimes)} times per month')

        return val


class PlaylistDeleteView(PermissionRequiredMixin, DeleteView):
    model = Playlist
    form_class = forms.PlaylistDeleteForm
    success_url = reverse_lazy("vidar:playlist-index")
    permission_required = ["vidar.delete_playlist"]

    def form_valid(self, form):

        if form.cleaned_data['delete_videos']:
            total_videos = self.object.videos.count()

            deleted_videos = playlist_services.delete_playlist_videos(playlist=self.object)

            if deleted_videos:
                messages.success(
                    self.request,
                    f'{deleted_videos}/{total_videos} videos deleted from the system. '
                    f'Remaining videos were protected.',
                )

        return super().form_valid(form=form)


class PlaylistScanView(PublicOrLoggedInUserMixin, DetailView):
    model = Playlist

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.provider_object_id:
            tasks.sync_playlist_data.delay(pk=self.object.pk, detailed_video_data=True)
        return redirect(self.object)


class PlaylistBooleanSwapper(PermissionRequiredMixin, HTMXIconBooleanSwapper, UpdateView):
    model = Playlist
    fields = '__all__'
    permission_required = ['vidar.change_playlist']


class PlaylistAddVideosBySearch(PermissionRequiredMixin, DetailView):
    model = Playlist
    permission_required = ['vidar.add_playlistitem']
    template_name = 'vidar/playlist_add_videos_by_search.html'

    def get_context_data(self, **kwargs):
        initial = {}
        if self.object.channel_id:
            initial['channel'] = self.object.channel

        kwargs['form'] = forms.PlaylistAddVideoBySearchForm(self.request.POST or None, initial=initial)
        return super().get_context_data(**kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()  # type: Playlist
        form = forms.PlaylistAddVideoBySearchForm(request.POST)
        qs = Video.objects.all()
        if form.is_valid():
            if channel_id := form.cleaned_data['channel']:
                qs = qs.filter(channel_id=channel_id)
            qs = qs.filter(title__icontains=form.cleaned_data['search'])

            messages.success(self.request, f"{qs.count()} videos found and added to playlist")

            for video in qs:
                self.object.playlistitem_set.get_or_create(
                    video=video,
                    provider_object_id=video.provider_object_id,
                    manually_added=True,
                )

        return redirect('vidar:playlist-detail', pk=self.object.id)


class PlaylistWatchLaterView(PlaylistDetailView):

    def get_object(self, queryset=None):
        return Playlist.get_user_watch_later(user=self.request.user)


class VideoHistoryListView(PermissionRequiredMixin, ListView):
    model = VideoHistory
    permission_required = ['vidar.view_videohistory']
    paginate_by = 50

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data()
        kwargs.update(
            paginator_helper(
                context_key='object_list',
                queryset=self.get_queryset(),
                params=self.request.GET,
                limit=self.paginate_by,
            )
        )
        return kwargs


class VideoNoteListView(PermissionRequiredMixin, ListView):
    model = VideoNote
    permission_required = ['vidar.view_videonote']
    paginate_by = 20


class HighlightListView(PermissionRequiredMixin, ListView):
    model = Highlight
    queryset = Highlight.objects.all().order_by('-inserted')
    permission_required = ['vidar.view_highlight']
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        if source := self.request.GET.get('source', Highlight.Sources.USER):
            qs = qs.filter(source__iexact=source)
        if q := self.request.GET.get('q'):
            qs = qs.filter(note__icontains=q)
        if cid := self.request.GET.get('channel'):
            qs = qs.filter(video__channel_id=cid)
        return qs

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data(*args, **kwargs)
        kwargs.update(
            paginator_helper(
                context_key='object_list',
                queryset=self.get_queryset(),
                params=self.request.GET,
                limit=self.paginate_by,
            )
        )
        return kwargs


class WatchHistoryListView(PermissionRequiredMixin, RestrictQuerySetToAuthorizedUserMixin, ListView):
    model = UserPlaybackHistory
    permission_required = ['vidar.view_userplaybackhistory']
    paginate_by = 20
    ordering = ['-updated']
    template_name = 'vidar/watch_history.html'

    def get_queryset(self):
        qs = super().get_queryset()
        if vid := self.request.GET.get('video'):
            qs = qs.filter(video_id=vid)
        if cid := self.request.GET.get('channel'):
            qs = qs.filter(video__channel_id=cid)
        return qs


class WatchHistoryDelete(PermissionRequiredMixin, RestrictQuerySetToAuthorizedUserMixin, DeleteView):
    model = UserPlaybackHistory
    permission_required = ['vidar.delete_userplaybackhistory']

    def delete(self, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        return HttpResponse('')


@user_passes_test(lambda u: u.has_perms(['vidar.view_download_queue']))
def download_queue(request):
    tdl = []

    # Copy this from tasks.automated_archiver

    for playlist in Playlist.objects.filter(hidden=False).order_by('inserted'):

        public_playlist_videos = playlist.playlistitem_set.filter(
            video__file='',
            video__privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible,
            download=True,
        )

        for pli in public_playlist_videos:
            video = pli.video

            if video.download_errors.exists():
                continue

            video.download_source = playlist
            tdl.append(video)

    for channel in Channel.objects.filter(full_archive=True):

        full_archive_videos_to_process = channel.videos.filter(
            file='', privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible
        )

        if channel.full_archive_cutoff:
            full_archive_videos_to_process = full_archive_videos_to_process.filter(
                upload_date__gte=channel.full_archive_cutoff
            )

        for video in full_archive_videos_to_process:

            if video.download_errors.exists():
                continue

            video.download_source = f"Full Archive {channel}"
            tdl.append(video)

    # defaults are 5 errors a day, lets set it to 14 days worth of attempts.
    maximum_attempts_erroring_downloads = app_settings.VIDEO_DOWNLOAD_ERROR_ATTEMPTS
    minutes_to_wait_between_error_attempts = app_settings.VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD

    videos_with_download_errors = Video.objects.annotate(total_download_errors=Count('download_errors')).filter(
        total_download_errors__lt=maximum_attempts_erroring_downloads, total_download_errors__gte=1
    )

    for video in videos_with_download_errors:

        if video.at_max_download_errors_for_period():
            log.debug(f"{video=} at max daily errors. Skipping.")
            continue

        # If its under X time since the last download error, wait.
        diff = timezone.now() - video.download_errors.latest().inserted
        if diff < timezone.timedelta(minutes=minutes_to_wait_between_error_attempts):
            log.debug(f"{video=} retried too soon, waiting longer.")
            continue

        video.download_source = "Download Errors"
        tdl.append(video)

    for video in Video.objects.filter(file__endswith='.mkv'):
        video.download_source = "MKV Conversion"
        tdl.append(video)

    for video in Video.objects.filter(
        requested_max_quality=True, at_max_quality=False, system_notes__max_quality_upgraded__isnull=True
    ).exclude(file=''):
        video.download_source = "Quality upgraded on provider after the fact."
        tdl.append(video)

    hours = app_settings.VIDEO_LIVE_DOWNLOAD_RETRY_HOURS
    for video in Video.objects.filter(system_notes__video_was_live_at_last_attempt=True):
        video.download_source = f'Video was live, retry after {hours=}'
        tdl.append(video)

    return render(
        request,
        'vidar/queue.html',
        {
            'videos': tdl,
        },
    )


@user_passes_test(lambda u: u.has_perms(['vidar.view_update_details_queue']))
def update_video_details_queue(request):

    videos_that_are_checkable = (
        Video.objects.archived()
        .filter(
            # privacy_status__in=Video.VideoPrivacyStatuses_Publicly_Visible
            Q(channel__status=channel_helpers.ChannelStatuses.ACTIVE, channel__check_videos_privacy_status=True)
            | Q(channel__isnull=True),
        )
        .annotate(
            last_checked_null_first=Case(When(last_privacy_status_check__isnull=True, then=1), default=0),
            zero_quality_first=Case(When(quality=0, then=1), default=0),
        )
        .filter(
            privacy_status_checks__lt=app_settings.PRIVACY_STATUS_CHECK_MAX_CHECK_PER_VIDEO,
        )
        .order_by('-zero_quality_first', '-last_checked_null_first', 'last_privacy_status_check', 'upload_date')
    )

    checks_video_age_days = app_settings.PRIVACY_STATUS_CHECK_MIN_AGE
    thirty_days_ago = timezone.localtime() - timezone.timedelta(days=checks_video_age_days)

    qs = Q(last_privacy_status_check__lt=thirty_days_ago) | Q(last_privacy_status_check__isnull=True)
    if app_settings.SAVE_INFO_JSON_FILE:
        qs |= Q(info_json='')

    videos_needing_an_update = videos_that_are_checkable.filter(qs)

    context = paginator_helper(
        context_key='videos',
        queryset=videos_needing_an_update,
        params=request.GET,
    )
    context['total_checkable_videos'] = videos_that_are_checkable.count()

    return render(request, 'vidar/queue_update_video_details.html', context)


@user_passes_test(lambda u: u.has_perms(['vidar.update_channel']))
def update_channels_bulk(request):

    qs = Channel.objects.active().exclude(scanner_crontab='').order_by('name')
    formset = forms.BulkChannelModelFormSet(queryset=qs)

    if request.method == 'POST':
        formset = forms.BulkChannelModelFormSet(request.POST, queryset=qs)

        if formset.is_valid():
            print('is valid')
            formset.save()

            return redirect('vidar:channel-bulk-update')

    return render(
        request,
        'vidar/channel_form_bulk.html',
        {
            'formset': formset,
        },
    )


class ScheduleView(PermissionRequiredMixin, TemplateView):
    permission_required = ['vidar.view_channel']
    template_name = 'vidar/schedule.html'

    def get_context_data(self, **kwargs):
        kwargs['schedule'] = {}
        todays_schedule = {}

        channel_qs = Channel.objects.exclude(scanner_crontab='')
        playlist_qs = Playlist.objects.exclude(crontab='')
        if 'sparse' in self.request.GET:
            channel_qs = channel_qs.exclude(scanner_crontab__endswith='* * *')
            playlist_qs = playlist_qs.exclude(crontab__endswith='* * *')

        if 'channels' in self.request.GET:
            playlist_qs = playlist_qs.filter(id=0)
        if 'playlists' in self.request.GET:
            channel_qs = channel_qs.filter(id=0)

        if cid := self.request.GET.get('channel'):
            kwargs['channel'] = get_object_or_404(Channel, id=cid)
            channel_qs = channel_qs.filter(id=cid)
            playlist_qs = playlist_qs.filter(id=0)
        if pid := self.request.GET.get('playlist'):
            playlist_qs = playlist_qs.filter(id=pid)
            channel_qs = channel_qs.filter(id=0)

        total_scans_per_day = 0

        now = None
        kwargs['date_selected'] = ""
        if date_str := self.request.GET.get('date'):
            year, month, day = date_str.split('-')
            now = timezone.localtime().replace(year=int(year), month=int(month), day=int(day))
            kwargs['date_selected'] = f"{date_str} - "

        for c in channel_qs:
            channels_crontab_executions = crontab_services.calculate_schedule(
                crontab=c.scanner_crontab,
                now=now,
            )
            for dt in channels_crontab_executions:
                if dt not in todays_schedule:
                    todays_schedule[dt] = []
                todays_schedule[dt].append(c)
                total_scans_per_day += 1

        for p in playlist_qs:
            playlists_crontab_executions = crontab_services.calculate_schedule(
                crontab=p.crontab,
                now=now,
            )
            for dt in playlists_crontab_executions:
                if dt not in todays_schedule:
                    todays_schedule[dt] = []
                todays_schedule[dt].append(p)
                total_scans_per_day += 1

        sorted_dict = dict(sorted(todays_schedule.items()))
        kwargs['todays_schedule'] = sorted_dict
        kwargs['total_scans_per_day'] = total_scans_per_day
        return super().get_context_data(**kwargs)


class ScheduleCalendarView(PermissionRequiredMixin, TemplateView):
    permission_required = ['vidar.view_channel']
    template_name = 'vidar/schedule_calendar.html'

    def get_context_data(self, **kwargs):

        start = timezone.localtime().replace(day=1)

        datetimes_to_objects = defaultdict(list)

        playlist_qs = Playlist.objects.exclude(crontab__endswith='* * *')
        channel_qs = Channel.objects.exclude(scanner_crontab__endswith='* * *')

        if 'all' in self.request.GET:
            playlist_qs = Playlist.objects.exclude(crontab='')
            channel_qs = Channel.objects.exclude(scanner_crontab='')
        elif 'daily' in self.request.GET:
            playlist_qs = Playlist.objects.filter(crontab__endswith='* * *')
            channel_qs = Channel.objects.filter(scanner_crontab__endswith='* * *')

        for playlist in playlist_qs:
            if not playlist.crontab:
                continue

            matched_datetimes = crontab_services.calculate_schedule(playlist.crontab, now=start, check_month=True)

            for dt in matched_datetimes:
                datetimes_to_objects[dt].append(playlist)

        for channel in channel_qs:
            if not channel.scanner_crontab:
                continue

            matched_datetimes = crontab_services.calculate_schedule(
                channel.scanner_crontab, now=start, check_month=True
            )

            for dt in matched_datetimes:
                datetimes_to_objects[dt].append(channel)

        datetimes_to_objects.default_factory = None

        kwargs['datetimes_to_objects'] = datetimes_to_objects

        return super().get_context_data(**kwargs)


class ScheduleHistoryView(PermissionRequiredMixin, ListView):
    model = ScanHistory
    permission_required = ['vidar.view_scanhistory']
    paginate_by = 50
    template_name = 'vidar/schedule_history.html'

    def get_queryset(self):
        qs = super().get_queryset()
        if selected_date := self.request.GET.get('date'):
            if selected_date != 'all':
                qs = qs.filter(inserted__date=selected_date)
        else:
            qs = qs.filter(inserted__date=timezone.localdate())
        if channel_id := self.request.GET.get('channel'):
            qs = qs.filter(channel_id=channel_id)
        if playlist_id := self.request.GET.get('playlist'):
            qs = qs.filter(playlist_id=playlist_id)
        if 'downloaded' in self.request.GET:
            qs = qs.filter(Q(videos_downloaded__gt=0) | Q(shorts_downloaded__gt=0) | Q(livestreams_downloaded__gt=0))
        return qs

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data()
        if channel_id := self.request.GET.get('channel'):
            kwargs['channel'] = Channel.objects.get(pk=channel_id)
        if playlist_id := self.request.GET.get('playlist'):
            kwargs['playlist'] = Playlist.objects.get(pk=playlist_id)

        sd = timezone.localdate()
        if self.request.GET.get('date') and self.request.GET['date'] != 'all':
            sd = timezone.datetime.strptime(self.request.GET['date'], '%Y-%m-%d').date()
            kwargs['previous_date'] = sd - timezone.timedelta(days=1)
            kwargs['selected_date'] = sd
            next_date = sd + timezone.timedelta(days=1)
            if next_date <= timezone.localdate():
                kwargs['next_date'] = next_date
        else:
            kwargs['previous_date'] = sd - timezone.timedelta(days=1)
            kwargs['selected_date'] = sd
            next_date = sd + timezone.timedelta(days=1)
            if next_date <= timezone.localdate():
                kwargs['next_date'] = next_date

        kwargs.update(
            paginator_helper(
                context_key='object_list',
                queryset=self.get_queryset(),
                params=self.request.GET,
                limit=self.paginate_by,
            )
        )
        return kwargs


class VideoBlockedListView(PermissionRequiredMixin, RequestBasedQuerysetFilteringMixin, ListView):
    model = VideoBlocked
    permission_required = ['vidar.view_videoblocked']
    RequestBaseFilteringDefaultFields = ['provider_object_id', 'title']

    def get_context_data(self, *args, **kwargs):
        kwargs = super().get_context_data(*args, **kwargs)

        kwargs.update(
            paginator_helper(
                context_key='object_list',
                queryset=self.get_queryset(),
                params=self.request.GET,
            )
        )
        return kwargs


class VideoBlockedDeleteView(PermissionRequiredMixin, SuccessMessageMixin, DeleteView):
    model = VideoBlocked
    permission_required = ['vidar.delete_videoblocked']
    success_url = reverse_lazy('vidar:blocked-index')

    def get_success_message(self, cleaned_data):
        return f"Video unblocked: {self.object.title}"
