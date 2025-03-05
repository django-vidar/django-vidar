from django import forms
from django.db.models import Q
from django.utils import timezone

from django_celery_results.models import TaskResult

from vidar import app_settings, tasks, utils
from vidar.helpers import video_helpers
from vidar.interactor import YTDLPInteractor
from vidar.models import Channel, DurationSkip, ExtraFile, Highlight, Playlist, PossibleQualities, Video


class VideoUpdateForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = '__all__'
        exclude = ['related', 'playlists']


class VideoDownloaderForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ["provider_object_id", "convert_to_audio", "quality",
                  "download_comments_on_index", "download_all_comments", 'mark_for_deletion', 'delete_after_watching']
        labels = {"provider_object_id": "Link To Video"}
        help_texts = {
            'download_comments_on_index': "Obtains latest 100 comments",
            'download_all_comments': "Use sparingly.",
        }

    quality = forms.ChoiceField(choices=PossibleQualities, required=True, initial=video_helpers.default_quality)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)

        if not user.is_authenticated:
            del self.fields['download_all_comments']

    def clean_provider_object_id(self):
        data = self.cleaned_data.get("provider_object_id")
        video_id = utils.get_video_id_from_url(data)

        if Video.objects.filter(provider_object_id=video_id).exists():
            raise forms.ValidationError("Video already exists.")

        return video_id

    def save(self, commit=True):
        obj = super().save(commit=commit)  # type: Video

        tasks.download_video.apply_async(
            kwargs=dict(
                pk=obj.pk,
                quality=self.cleaned_data["quality"],
                task_source='Video Downloader Form',
            )
        )
        return obj


class VideoManualEditor(forms.ModelForm):
    class Meta:
        model = Video
        fields = ['title', 'description', 'playback_speed', 'playback_volume']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.title_locked:
            self.fields.pop('title')
        if not self.instance.description_locked:
            self.fields.pop('description')


class PlaylistAdderForm(forms.ModelForm):
    class Meta:
        model = Playlist
        fields = ["provider_object_id", "convert_to_audio", "sync_deletions", "crontab", "channel", "title_skips",
                  "disable_when_string_found_in_video_title", "quality", 'playback_speed', "playback_volume",
                  "videos_playback_ordering", "videos_display_ordering", "hidden", "restrict_to_assigned_channel",
                  "download_comments_on_index"]
        labels = {"provider_object_id": "Link To Playlist"}
        widgets = {
            'title_skips': forms.Textarea(attrs={'rows': 2}),
            'disable_when_string_found_in_video_title': forms.Textarea(attrs={'rows': 2}),
        }
        help_texts = {
            'crontab': 'minute, hour, day of month, month, day of week. '
                       'assign <a href="javascript:;" onclick="assign_crontab(\'hourly\')">hourly</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'daily\')">daily</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'weekly\')">weekly</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'monthly\')">monthly</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'biyearly\')">bi-yearly</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'yearly\')">yearly</a> ',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['disable_when_string_found_in_video_title'].strip = False

    def clean_provider_object_id(self):
        data = self.cleaned_data.get("provider_object_id")
        video_id = utils.get_video_id_from_url(data, playlist=True)

        if Playlist.objects.filter(Q(provider_object_id=video_id) | Q(provider_object_id_old=video_id)).exists():
            raise forms.ValidationError("Playlist already exists.")

        return video_id

    def save(self, commit=True):
        obj = super().save(commit=commit)  # type: Playlist
        tasks.sync_playlist_data.delay(pk=obj.pk, initial_sync=True)
        return obj


class PlaylistEditForm(forms.ModelForm):
    class Meta:
        model = Playlist
        fields = ["convert_to_audio", "sync_deletions", "crontab", "channel", "title_skips",
                  "disable_when_string_found_in_video_title", "quality", 'playback_speed', "playback_volume",
                  "videos_playback_ordering", "videos_display_ordering", "hidden", "restrict_to_assigned_channel",
                  "download_comments_on_index", "provider_object_id", "provider_object_id_old"]
        widgets = {
            'title_skips': forms.Textarea(attrs={'rows': 2}),
            'disable_when_string_found_in_video_title': forms.Textarea(attrs={'rows': 2}),
        }
        help_texts = {
            'crontab': 'minute, hour, day of month, month, day of week. '
                       'assign <a href="javascript:;" onclick="assign_crontab(\'hourly\')">hourly</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'daily\')">daily</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'weekly\')">weekly</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'monthly\')">monthly</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'biyearly\')">bi-yearly</a> '
                       'or <a href="javascript:;" onclick="assign_crontab(\'yearly\')">yearly</a> ',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['disable_when_string_found_in_video_title'].strip = False


class PlaylistManualAddForm(forms.ModelForm):

    title = forms.CharField(max_length=500, required=True)

    class Meta:
        model = Playlist
        fields = ['title', 'description', 'convert_to_audio', 'channel', 'quality',
                  'videos_display_ordering', 'videos_playback_ordering',
                  "video_indexing_add_by_title", "video_indexing_add_by_title_limit_to_channels",
                  "download_comments_on_index", "restrict_to_assigned_channel",
                  'remove_video_from_playlist_on_watched']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'video_indexing_add_by_title': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['video_indexing_add_by_title'].strip = False
        if instance := kwargs.get('instance'):
            if instance.id:
                original_label = self.fields['video_indexing_add_by_title_limit_to_channels'].label
                num_sel_channels = instance.video_indexing_add_by_title_limit_to_channels.count()
                label = f"{original_label} ({num_sel_channels} selected)"
                self.fields['video_indexing_add_by_title_limit_to_channels'].label = label


class PlaylistManualEditForm(PlaylistManualAddForm):

    class Meta:
        model = Playlist
        fields = ['title', 'description', 'convert_to_audio', 'channel', 'quality',
                  'videos_display_ordering', 'videos_playback_ordering',
                  "video_indexing_add_by_title", "video_indexing_add_by_title_limit_to_channels",
                  "download_comments_on_index", "restrict_to_assigned_channel", "provider_object_id",
                  "provider_object_id_old", 'remove_video_from_playlist_on_watched']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'video_indexing_add_by_title': forms.Textarea(attrs={'rows': 3}),
        }


class PlaylistDeleteForm(forms.Form):

    delete_videos = forms.BooleanField(
        initial=False, required=False, help_text="Delete the video and audio file from the system?"
    )

    class Meta:
        model = Playlist
        fields = ['delete_videos']


class PlaylistAddVideoBySearchForm(forms.Form):
    channel = forms.ModelChoiceField(
        queryset=Channel.objects.all(),
        required=False,
        help_text="Optional. If selected the search value is limited to this channel.",
    )
    search = forms.CharField(
        max_length=500,
        required=True,
        help_text="Case insensitive. Matches title only.",
    )


class QualityChoiceForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = ["quality"]
        widgets = {"quality": forms.Select(attrs={"class": "form-control-input"})}

    def __init__(self, *args, channel_default_quality=None, **kwargs):
        super().__init__(*args, **kwargs)
        qualities = []
        for k, v in PossibleQualities:
            if channel_default_quality and channel_default_quality == k:
                v = f"Channel: {v}"
            qualities.append((k, v))
        self.fields['quality'].choices = qualities

    def save(self, commit=False):
        raise ValueError("QualityChoiceForm cannot be used for editing an instance.")


class ChannelChoiceForm(forms.Form):
    channel = forms.ModelChoiceField(queryset=Channel.objects.all())


class CrontabCatchupForm(forms.Form):

    start = forms.DateTimeField(help_text='Remove the seconds, round the minutes to nearest 5')
    end = forms.DateTimeField(
        initial=timezone.localtime,
        help_text='Remove the seconds, round the minutes to nearest 5',
    )

    def __init__(self, *args, **kwargs):
        initial = kwargs.pop('initial', {})
        initial['start'] = timezone.localtime() - timezone.timedelta(hours=1)
        if task_last_run := TaskResult.objects.filter(task_name='vidar.tasks.trigger_crontab_scans').first():
            initial['start'] = task_last_run.date_done + timezone.timedelta(minutes=1)
        kwargs['initial'] = initial
        super().__init__(*args, **kwargs)

    def scan(self):

        start_raw = self.cleaned_data['start']
        end_raw = self.cleaned_data['end']

        def round_to_nearest(x, base=5):
            rounded = base * round(x / base)
            if rounded > 59:
                rounded = 59
            return rounded

        start = start_raw.replace(minute=round_to_nearest(start_raw.minute))
        end = end_raw.replace(minute=round_to_nearest(end_raw.minute))

        return tasks.check_missed_channel_scans_since_last_ran(start=start, end=end, force=True)


class ChannelGeneralCreateOptionsForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = [
            'provider_object_id', "display_name", 'sort_name', "quality", "allow_library_quality_upgrade",
            "full_archive", "full_archive_after", "full_archive_cutoff", "slow_full_archive",
            "full_index_after", "convert_videos_to_mp3",
        ]

        help_texts = {
            'provider_object_id': "Supply one url (with YouTube ID) for the channel you wish to subscribe to. "
                                  "URL should look like https://www.youtube.com/channel/UCOix6FvdT2i7TLMbgtcyMKQ<br />"
                                  "OR you can supply a video url and the channel will be obtained from there.",
        }
        labels = {
            'provider_object_id': "Channel ID (funny id, not human friendly).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        faa = []
        for channel in Channel.objects.exclude(full_archive_after__isnull=True):
            faa.append(f"{channel}: {channel.full_archive_after.date()}")

        self.fields['full_archive_after'].widget.attrs['placeholder'] = ", ".join(faa) or "Full archive after"

    def clean_provider_object_id(self):
        data = self.cleaned_data.get("provider_object_id")

        # Videos are ?v=
        if '?v=' in data:

            raw_id = utils.get_video_id_from_url(data)

            url = f"https://www.youtube.com/watch?v={raw_id}"

            video_data = YTDLPInteractor.video_details(url)

            channel_id = video_data['channel_id']

        else:
            channel_id = utils.get_channel_id_from_url(data)

        if Channel.objects.filter(provider_object_id=channel_id).exists():
            raise forms.ValidationError("Channel already exists.")

        return channel_id


class ChannelSubGeneralOptionsForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = [
            'scanner_crontab',
            "scan_after_datetime",
            "title_forces",
            "title_skips",
            'skip_next_downloads',
            "force_next_downloads",
        ]
        help_texts = {
            'scanner_crontab': 'minute, hour, day of month, month, day of week. '
                               'assign <a href="javascript:;" onclick="assign_crontab(\'hourly\')">hourly</a> '
                               'or <a href="javascript:;" onclick="assign_crontab(\'daily\')">daily</a> '
                               'or <a href="javascript:;" onclick="assign_crontab(\'weekly\')">weekly</a> '
                               'or <a href="javascript:;" onclick="assign_crontab(\'monthly\')">monthly</a> '
                               'or <a href="javascript:;" onclick="assign_crontab(\'biyearly\')">bi-yearly</a> '
                               'or <a href="javascript:;" onclick="assign_crontab(\'yearly\')">yearly</a> ',
        }
        widgets = {
            'title_forces': forms.Textarea(attrs={'rows': 2}),
            'title_skips': forms.Textarea(attrs={'rows': 2}),
        }


class ChannelGeneralUpdateOptionsForm(forms.ModelForm):
    class Meta(ChannelGeneralCreateOptionsForm.Meta):
        exclude = ['provider_object_id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        faa = []
        for channel in Channel.objects.exclude(full_archive_after__isnull=True):
            faa.append(f"{channel}: {channel.full_archive_after.date()}")

        self.fields['full_archive_after'].widget.attrs['placeholder'] = ", ".join(faa) or "Full archive after"

        self.fields['display_name'].widget.attrs['placeholder'] = self.instance.name
        self.fields['sort_name'].widget.attrs['placeholder'] = self.instance.name


class ChannelVideosOptionsForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = [
            'index_videos',
            'download_videos',
            'scanner_limit',
            'duration_minimum_videos',
            'duration_maximum_videos',
            'download_comments_with_video',
            'download_comments_during_scan',
            'swap_index_videos_after',
            'delete_videos_after_days',
            'delete_videos_after_watching',
        ]
        labels = {
            'index_videos': 'Index',
            'download_videos': 'Download',
            'scanner_limit': 'Scanning Index Limit',
            'duration_minimum_videos': 'Minimum Duration (In Seconds)',
            'duration_maximum_videos': 'Maximum Duration (In Seconds)',
        }


class ChannelShortsOptionsForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = ['index_shorts', 'download_shorts', 'scanner_limit_shorts',
                  'fully_indexed_shorts', 'swap_index_shorts_after',
                  'delete_shorts_after_days', 'delete_shorts_after_watching']
        labels = {
            'index_shorts': 'Index',
            'download_shorts': 'Download',
            'scanner_limit_shorts': 'Scanning Index Limit',
        }
        help_texts = {
            "fully_indexed_shorts": "Do not change this unless you know what you are doing.",
        }


class ChannelLivestreamsOptionsForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = [
            'index_livestreams',
            'download_livestreams',
            'scanner_limit_livestreams',
            'duration_minimum_livestreams',
            'duration_maximum_livestreams',
            'fully_indexed_livestreams',
            'swap_index_livestreams_after',
            'delete_livestreams_after_days',
            'delete_livestreams_after_watching',
        ]
        labels = {
            'index_livestreams': 'Index',
            'download_livestreams': 'Download',
            'scanner_limit_livestreams': 'Scanning Index Limit',
            'duration_minimum_livestreams': 'Minimum Duration (In Seconds)',
            'duration_maximum_livestreams': 'Maximum Duration (In Seconds)',
        }
        help_texts = {
            "fully_indexed_livestreams": "Do not change this unless you know what you are doing.",
        }


class ChannelMirroringPlaylistsForm(forms.ModelForm):

    force_mirror_now = forms.BooleanField(required=False, initial=False)

    class Meta:
        model = Channel
        fields = ['mirror_playlists', 'mirror_playlists_hidden', 'mirror_playlists_crontab',
                  "mirror_playlists_restrict", 'force_mirror_now']

    def save(self, *args, **kwargs):
        output = super().save(*args, *kwargs)

        if self.cleaned_data['mirror_playlists'] and self.cleaned_data['force_mirror_now']:
            tasks.mirror_live_playlist.delay(self.instance.pk)

        return output


class ChannelPlaybackOptionsForm(forms.ModelForm):

    class Meta:
        model = Channel
        fields = [
            "playback_speed",
            "playback_volume",
            "skip_intro_duration",
            "skip_outro_duration",
            "watched_percentage",
        ]

    def __init__(self, *args, **kwargs):
        user = None
        if 'user' in kwargs:
            user = kwargs.pop('user')

        super().__init__(*args, **kwargs)

        if user and hasattr(user, 'vidar_playback_speed'):
            self.fields['playback_speed'].help_text = f"Current User Default: {user.vidar_playback_speed} " \
                                                      "Leave blank for user default."


class ChannelAdministrativeOptionsForm(forms.ModelForm):

    class Meta:
        model = Channel
        fields = [
            "send_download_notification",
            'fully_indexed',
            "store_videos_by_year_separation",
            "store_videos_in_separate_directories",
            "status",
            "directory_schema",
            "video_directory_schema",
            "video_filename_schema",
            "block_rescan_window_in_hours",
            "check_videos_privacy_status",
        ]
        help_texts = {
            "fully_indexed": "Do not change this unless you know what you are doing.",
            "directory_schema": "The very root folder all videos for this channel "
                                "are stored within. Blank for system default.",
            "video_directory_schema": "If videos are stored in separate directories (enabled above), "
                                      "this controls that directory name. Blank for system default.",
            "video_filename_schema": "How video filenames are built. Do not add an "
                                     "extension to the end. Blank for system default."

        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['video_directory_schema'].widget.attrs['placeholder'] = app_settings.VIDEO_DIRECTORY_SCHEMA
        self.fields['video_filename_schema'].widget.attrs['placeholder'] = app_settings.VIDEO_FILENAME_SCHEMA
        self.fields['directory_schema'].widget.attrs['placeholder'] = app_settings.CHANNEL_DIRECTORY_SCHEMA


class ChannelIndexingForm(forms.ModelForm):
    limit = forms.IntegerField(
        required=False, initial='',
        help_text="How many videos to index? Optional."
    )

    class Meta:
        model = Channel
        fields = ['limit']


class CopyVideoThumbnailAsYearlyCoverForm(forms.Form):

    position = forms.ChoiceField(
        choices=(
            ('first', 'First video of the year'),
            ('latest', 'Latest/last video of the year'),
            ('random', 'Random video from the year'),
        )
    )


def convert_timeformat_to_seconds(data):
    if data.count(':') == 2:
        hours, minutes, seconds = data.split(':')
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    elif data.count(':') == 1:
        minutes, seconds = data.split(':')
        return int(minutes) * 60 + int(seconds)
    else:
        raise forms.ValidationError('Invalid time format')


class DurationSkipForm(forms.ModelForm):
    start = forms.CharField(required=True)
    end = forms.CharField(required=True)

    class Meta:
        model = DurationSkip
        fields = ['start', 'end']
        help_texts = {
            'start': 'In seconds',
            'end': 'In seconds',
        }

    def __init__(self, *args, existing_skips, **kwargs):
        self.existing_skips = existing_skips
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        start = int(cleaned_data['start'])
        end = int(cleaned_data['end'])

        if start is not None and end is not None:
            if start > end:
                self.add_error('end', 'End must be greater than start time')

            if utils.do_new_start_end_points_overlap_existing(start, end, self.existing_skips):
                self.add_error('start', 'Chosen time range overlaps another skip.')

        return cleaned_data

    def clean_start(self):
        data = self.cleaned_data['start']
        if isinstance(data, str) and ':' in data:
            return convert_timeformat_to_seconds(data)
        return int(data)

    def clean_end(self):
        data = self.cleaned_data['end']
        if isinstance(data, str) and ':' in data:
            return convert_timeformat_to_seconds(data)
        return int(data)


class HighlightForm(forms.ModelForm):
    point = forms.CharField(required=True)
    end_point = forms.CharField(required=False)

    class Meta:
        model = Highlight
        fields = ['point', 'end_point', 'note']
        help_texts = {
            'point': 'Seconds or HH:MM:SS within video',
            'end_point': 'Seconds or HH:MM:SS within video',
        }

    def clean_point(self):
        data = self.cleaned_data.get('point')
        if isinstance(data, str) and ':' in data:
            return convert_timeformat_to_seconds(data)
        return int(data)

    def clean_end_point(self):
        data = self.cleaned_data.get('end_point')
        if isinstance(data, str) and ':' in data:
            return convert_timeformat_to_seconds(data)
        try:
            return int(data)
        except (ValueError, TypeError):
            return None

    def clean(self):
        cleaned_data = super().clean()
        start_point = cleaned_data.get('point')
        end_point = cleaned_data.get('end_point')
        if start_point and end_point and start_point > end_point:
            self.add_error('end_point', 'Start cannot be before End')
        elif start_point and end_point and start_point == end_point:
            self.cleaned_data['end_point'] = None
        return cleaned_data


class ChapterForm(forms.ModelForm):
    point = forms.CharField(required=True)

    class Meta:
        model = Highlight
        fields = ['point', 'note']
        help_texts = {
            'point': 'Seconds or HH:MM:SS within video',
        }

    def clean_point(self):
        data = self.cleaned_data.get('point')
        if isinstance(data, str) and ':' in data:
            return convert_timeformat_to_seconds(data)
        return int(data)


class ExtraFileForm(forms.ModelForm):
    class Meta:
        model = ExtraFile
        fields = ['file', 'note']
        widgets = {
            'note': forms.Textarea(attrs={'rows': 2}),
        }


class BulkChannelForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = ['scanner_crontab']
        labels = {
            'scanner_crontab': ''
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        cid = self.instance.pk

        self.fields['scanner_crontab'].help_text = \
            f'<a href="javascript:;" onclick="assign_crontab(\'hourly\', {cid})">hourly</a> ' \
            f'or <a href="javascript:;" onclick="assign_crontab(\'daily\', {cid})">daily</a> ' \
            f'or <a href="javascript:;" onclick="assign_crontab(\'weekly\', {cid})">weekly</a> ' \
            f'or <a href="javascript:;" onclick="assign_crontab(\'monthly\', {cid})">monthly</a> ' \
            f'or <a href="javascript:;" onclick="assign_crontab(\'biyearly\', {cid})">bi-yearly</a> ' \
            f'or <a href="javascript:;" onclick="assign_crontab(\'yearly\', {cid})">yearly</a> '

        self.fields['scanner_crontab'].widget.attrs['class'] = f'form-control channel-{cid}'


BulkChannelModelFormSet = forms.modelformset_factory(model=Channel, form=BulkChannelForm, edit_only=True, extra=0)
