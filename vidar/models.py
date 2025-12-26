from __future__ import annotations

import datetime
import difflib
import functools
import logging
import math
import re

from django.conf import settings
from django.db import models
from django.db.models import F, Q, Sum
from django.shortcuts import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.text import slugify

from mptt.models import MPTTModel, TreeForeignKey
from positions.fields import PositionField

from vidar import app_settings, exceptions, json_encoders, utils
from vidar.helpers import channel_helpers, extrafile_helpers, json_safe_kwargs, model_helpers, video_helpers
from vidar.services import crontab_services, notification_services, ytdlp_services
from vidar.storages import vidar_storage


log = logging.getLogger(__name__)


# Reminder, when using this on a model field. After making a change to the field,
#   manually edit the migration file to reference this tuple instead of the raw strings
PossibleQualities = (
    (None, "System Default"),
    (0, "Best"),
    (480, "480p (SD)"),
    (720, "720p"),
    (1080, "1080p (HD)"),
    (1440, "2K (1440p)"),
    (2160, "4K (2160)"),
)
PossibleQualitiesList = [k for k, v in PossibleQualities]


class RightsSupport(models.Model):
    class Meta:
        managed = False

        default_permissions = ()  # disable default permissions

        permissions = (
            ("access_vidar", "General Access to Vidar"),
            ("view_index_download_stats", "Index View - See Download Stats"),
            ("view_download_queue", "View Download Queue"),
            ("view_update_details_queue", "View Update Details Queue"),
            ("access_watch_later_playlist", "Access Watch Later Functionality"),
        )


class ChannelObjectsManager(models.Manager):

    def active(self):
        return self.filter(status=channel_helpers.ChannelStatuses.ACTIVE)

    def indexing_enabled(self):
        return self.active().filter(Q(index_videos=True) | Q(index_shorts=True) | Q(index_livestreams=True))

    def actively_scanning(self):
        return self.indexing_enabled().exclude(Q(full_archive=True) | Q(scanner_crontab=""))

    def indexing_and_archiving(self):
        return (
            self.indexing_enabled()
            .filter(Q(download_videos=True) | Q(download_shorts=True) | Q(download_livestreams=True))
            .exclude(Q(full_archive=True) | Q(scanner_crontab=""))
        )

    def already_exists(self, provider_object_id):
        try:
            return self.get(Q(provider_object_id=provider_object_id) | Q(uploader_id__iexact=provider_object_id))
        except Channel.DoesNotExist:
            pass


class Channel(models.Model):

    objects = ChannelObjectsManager()

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True, allow_unicode=True)
    display_name = models.CharField(max_length=255, blank=True)
    sort_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="The name to be used when sorting by name, if blank it will use display name, then name.",
    )

    description = models.TextField(blank=True)

    provider_object_id = models.CharField(max_length=250)
    uploader_id = models.CharField(max_length=250, blank=True, help_text="The @ style name of the channel")
    active = models.BooleanField(default=True)
    status = models.CharField(
        max_length=50,
        choices=channel_helpers.ChannelStatuses.choices,
        default=channel_helpers.ChannelStatuses.ACTIVE,
    )

    banner = models.ImageField(
        null=True, blank=True, upload_to=channel_helpers.upload_to_banner, storage=vidar_storage, max_length=500
    )
    thumbnail = models.ImageField(
        null=True, blank=True, upload_to=channel_helpers.upload_to_thumbnail, storage=vidar_storage, max_length=500
    )
    tvart = models.ImageField(
        null=True, blank=True, upload_to=channel_helpers.upload_to_tvart, storage=vidar_storage, max_length=500
    )

    swap_index_videos_after = models.DateTimeField(null=True, blank=True)
    index_videos = models.BooleanField(default=True, help_text="Should videos be indexed?")
    download_videos = models.BooleanField(default=True, help_text="Should videos be downloaded?")
    scanner_limit = models.PositiveIntegerField(
        default=5,
        help_text="Limit how many videos the system scans every time for this channel, "
        "How many potential videos could this channel put out in a single day?",
    )
    duration_minimum_videos = models.PositiveIntegerField(
        default=0,
        verbose_name="Duration Minimum For Videos (In Seconds)",
        help_text="Minimum duration in seconds of a video to download. "
        "Anything shorter than this will be skipped. 0 = disabled.",
    )
    duration_maximum_videos = models.PositiveIntegerField(
        default=0,
        verbose_name="Duration Maximum For Videos (In Seconds)",
        help_text="Maximum duration in seconds of a video to download. "
        "Anything longer than this will be skipped. 0 = disabled.",
    )
    delete_videos_after_days = models.PositiveIntegerField(default=0)

    swap_index_shorts_after = models.DateTimeField(null=True, blank=True)
    index_shorts = models.BooleanField(default=False, help_text="Should shorts be indexed?")
    download_shorts = models.BooleanField(default=False, help_text="Should shorts be downloaded?")
    last_scanned_shorts = models.DateTimeField(null=True, blank=True)
    scanner_limit_shorts = models.PositiveIntegerField(
        default=5,
        help_text="Limit how many shorts the system scans every time for this channel, "
        "How many potential shorts could this channel put out in a single day?",
    )
    fully_indexed_shorts = models.BooleanField(default=False)
    delete_shorts_after_days = models.PositiveIntegerField(default=0)

    swap_index_livestreams_after = models.DateTimeField(null=True, blank=True)
    index_livestreams = models.BooleanField(default=False, help_text="Should livestreams be indexed?")
    download_livestreams = models.BooleanField(default=False, help_text="Should Livestreams be downloaded?")
    last_scanned_livestreams = models.DateTimeField(null=True, blank=True)
    scanner_limit_livestreams = models.PositiveIntegerField(
        default=5,
        help_text="Limit how many livestreams the system scans every time for this channel, "
        "How many potential livestreams could this channel put out in a single day?",
    )
    duration_minimum_livestreams = models.PositiveIntegerField(
        default=0,
        verbose_name="Duration Minimum For Livestreams (In Seconds)",
        help_text="Minimum duration in seconds of a livestream to download. "
        "Anything shorter than this will be skipped. 0 = disabled.",
    )
    duration_maximum_livestreams = models.PositiveIntegerField(
        default=0,
        verbose_name="Duration Maximum For Livestreams (In Seconds)",
        help_text="Maximum duration in seconds of a livestream to download. "
        "Anything longer than this will be skipped. 0 = disabled.",
    )
    fully_indexed_livestreams = models.BooleanField(default=False)
    delete_livestreams_after_days = models.PositiveIntegerField(default=0)

    download_comments_with_video = models.BooleanField(default=False, help_text="Should video comments be downloaded?")
    download_comments_during_scan = models.BooleanField(
        default=False, help_text="Should video comments be downloaded during indexing of videos?"
    )

    scanner_crontab = models.CharField(
        max_length=50, blank=True, help_text="minute, hour, day of month, month, day of week"
    )
    scan_after_datetime = models.DateTimeField(
        null=True,
        blank=True,
        help_text="A datetime representing the next time you wish to scan the channel, "
        "outside of the crontab schedule. Format: YYYY-MM-DD HH:MM",
    )

    slow_full_archive = models.BooleanField(
        default=False,
        help_text="Enabling this setting will cause the system to download all possible videos for this channel "
        "regardless of other settings at a slower rate. To be used instead of Full Archive option.",
    )

    full_archive = models.BooleanField(
        default=False,
        help_text="Enabling this setting will cause the system to download all possible videos for this channel "
        "regardless of other settings.",
    )
    full_archive_after = models.DateTimeField(
        null=True, blank=True, help_text="Instead of full archiving right now, enable full archive after this date."
    )
    full_archive_cutoff = models.DateField(
        null=True,
        blank=True,
        help_text="If full archive is enabled, only videos uploaded after this date will be downloaded.",
    )

    fully_indexed = models.BooleanField(default=False)

    full_index_after = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Instead of fully indexing right now, trigger a full indexing scan after this date.",
    )

    convert_videos_to_mp3 = models.BooleanField(default=False)

    title_skips = models.TextField(
        blank=True,
        verbose_name="Skip DL by Title contains",
        help_text="If any of these words appear in the title, do not download the video. ONE PER LINE. i.e. #shorts",
    )
    title_forces = models.TextField(
        blank=True,
        verbose_name="Force DL by Title contains",
        help_text="If any of these words appear in the title, force download the video regardless of settings. "
        "ONE PER LINE. Overrides all other restriction settings.",
    )

    quality = models.PositiveIntegerField(null=True, blank=True, choices=PossibleQualities)

    allow_library_quality_upgrade = models.BooleanField(
        default=False,
        help_text="Changing the channel quality will cause all videos to redownload. Do you want this to happen?",
    )

    playback_speed = models.CharField(max_length=10, null=True, blank=True, choices=model_helpers.PlaybackSpeed.choices)
    playback_volume = models.CharField(
        max_length=10,
        blank=True,
        choices=model_helpers.PlaybackVolume.choices,
    )

    store_videos_by_year_separation = models.BooleanField(default=True)
    store_videos_in_separate_directories = models.BooleanField(
        default=True,
        help_text="Should videos be stored in separate directories for each video? Each directory will then "
        "contain the video file, info.json, and it's thumbnail.",
    )
    video_filename_schema = models.CharField(
        max_length=500,
        blank=True,
        help_text=model_helpers.FILENAME_SCHEMA_HELP_TEXT,
    )
    video_directory_schema = models.CharField(
        max_length=500,
        blank=True,
        help_text=model_helpers.DIRECTORY_SCHEMA_HELP_TEXT,
    )

    directory_schema = models.CharField(max_length=500, blank=True)

    inserted = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    last_scanned = models.DateTimeField(null=True, blank=True)

    send_download_notification = models.BooleanField(default=True)

    skip_intro_duration = models.PositiveIntegerField(
        default=0, help_text="How many seconds of intro should be skipped?"
    )
    skip_outro_duration = models.PositiveIntegerField(
        default=0, help_text="How many seconds of outro should be skipped?"
    )

    skip_next_downloads = models.PositiveIntegerField(default=0, help_text="Skip next X number of downloads")
    force_next_downloads = models.PositiveIntegerField(
        default=0,
        help_text="Force next X number of downloads",
    )
    watched_percentage = models.PositiveIntegerField(
        default=95,
        choices=[
            (50, "50%"),
            (55, "55%"),
            (60, "60%"),
            (65, "65%"),
            (70, "70%"),
            (75, "75%"),
            (80, "80%"),
            (85, "85%"),
            (90, "90%"),
            (95, "95%"),
            (100, "100%"),
        ],
        help_text="At what percentage of watching a video on this channel should the video be marked as watched.",
        validators=[channel_helpers.watched_percentage_minimum, channel_helpers.watched_percentage_maximum],
    )

    mirror_playlists = models.BooleanField(
        default=False,
        help_text="Mirror all live playlists from this channel",
    )
    mirror_playlists_hidden = models.BooleanField(
        default=False,
        help_text="When adding a new playlist as a mirror, apply this checkbox value to the playlists hidden option.",
    )
    mirror_playlists_crontab = models.CharField(
        max_length=50,
        blank=True,
        choices=crontab_services.CrontabOptions.choices,
        help_text="When adding a new playlist as a mirror, apply a crontab that matches this type.",
    )
    mirror_playlists_restrict = models.BooleanField(
        default=False, help_text='Sets the playlists "Restrict to assigned channel" field value.'
    )

    delete_videos_after_watching = models.BooleanField(
        default=False,
        help_text="Delete videos once they has been watched?",
    )

    delete_shorts_after_watching = models.BooleanField(
        default=False,
        help_text="Delete shorts once they has been watched?",
    )

    delete_livestreams_after_watching = models.BooleanField(
        default=False,
        help_text="Delete livestreams once they has been watched?",
    )

    block_rescan_window_in_hours = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="If you manually scan a channel and the crontab tries to run within "
        "this many hours of the manual scan, don't rescan.",
    )

    check_videos_privacy_status = models.BooleanField(default=True)

    needs_cookies = models.BooleanField(
        default=False,
        help_text="Does access to this channels content require cookies?",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):  # pragma: no cover
        return self.display_name or self.name or str(self.pk)

    def get_absolute_url(self):  # pragma: no cover
        return reverse("vidar:channel-details", args=[self.slug or self.pk])

    @property
    def system_safe_name(self):
        replaceables = {
            "&": "and",
            "–": "-",
        }
        keepers = "&– -"
        safe_name = "".join([c for c in self.name if c.isalnum() or c in keepers]).rstrip()
        for k, v in replaceables.items():
            safe_name = safe_name.replace(k, v)
        safe_string = re.sub(" +", " ", safe_name)
        safe_string_without_multiple_spaces = " ".join(safe_string.split())
        return safe_string_without_multiple_spaces

    @property
    def system_safe_name_the(self):
        current_name = self.system_safe_name
        if current_name.lower().startswith("the "):
            cased_the = current_name[:4].strip()
            title_without_the = current_name[4:]
            current_name = f"{title_without_the}, {cased_the}"
        return current_name

    @property
    def base_url(self):  # pragma: no cover
        return f"https://www.youtube.com/channel/{self.provider_object_id}"

    @property
    def url(self):  # pragma: no cover
        return f"{self.base_url}/videos"

    @property
    def shorts_url(self):  # pragma: no cover
        return f"{self.base_url}/shorts"

    @property
    def livestreams_url(self):  # pragma: no cover
        return f"{self.base_url}/live"

    @property
    def banner_url(self):  # pragma: no cover
        if self.banner:
            return self.banner.url
        return ""

    @property
    def thumbnail_url(self):  # pragma: no cover
        if self.thumbnail:
            return self.thumbnail.url
        return ""

    @property
    def tvart_url(self):  # pragma: no cover
        if self.tvart:
            return self.tvart.url
        return ""

    @property
    def videos_archived(self):
        return self.videos.exclude(file="")

    @property
    def videos_at_max_quality(self):
        return self.videos_archived.filter(at_max_quality=True)

    @cached_property
    def next_runtime(self):
        now = timezone.localtime()

        while True:

            if crontab_services.is_active_now(self.scanner_crontab, now):
                break

            now = now + timezone.timedelta(minutes=1)

        if self.scan_after_datetime and self.scan_after_datetime < now:
            return self.scan_after_datetime

        return now

    def save(self, *args, **kwargs):
        changed_fields = []

        if self.name:
            slug = slugify(self.name)
            if self.slug != slug:
                self.slug = slug
                changed_fields.append("slug")

        if self.status == channel_helpers.ChannelStatuses.ACTIVE:

            is_indexing_something = self.index_videos or self.index_shorts or self.index_livestreams

            # If index_videos==True and no crontab assigned, assign one.
            if is_indexing_something and not self.scanner_crontab:
                self.scanner_crontab = crontab_services.generate_daily()
                changed_fields.append("scanner_crontab")

            # Ensure no crontab exists if disabled
            if not is_indexing_something and self.scanner_crontab:
                self.scanner_crontab = ""
                changed_fields.append("scanner_crontab")

            if self.full_archive and self.full_archive_after:
                self.full_archive_after = None
                changed_fields.append("full_archive_after")

        if self.pk:
            try:
                orig = Channel.objects.get(pk=self.pk)

                # if the original was not set to index an item, but
                # it is now set to index, reset fully_indexed flag
                if self.index_videos != orig.index_videos:
                    self.fully_indexed = False
                    changed_fields.append("fully_indexed")
                if self.index_shorts != orig.index_shorts:
                    self.fully_indexed_shorts = False
                    changed_fields.append("fully_indexed_shorts")
                if self.index_livestreams != orig.index_livestreams:
                    self.fully_indexed_livestreams = False
                    changed_fields.append("fully_indexed_livestreams")

                # Disabling full archive cutoff clears the fully_indexed flag as videos could have been missed.
                # Changing the cutoff date will clear the fully_indexed flag
                if (
                    orig.full_archive_cutoff
                    and (not self.full_archive_cutoff or orig.full_archive_cutoff != self.full_archive_cutoff)
                    and (self.fully_indexed or self.fully_indexed_shorts or self.fully_indexed_livestreams)
                ):
                    self.fully_indexed = False
                    self.fully_indexed_shorts = False
                    self.fully_indexed_livestreams = False
                    changed_fields.extend(["fully_indexed", "fully_indexed_shorts", "fully_indexed_livestreams"])

            except Channel.DoesNotExist:  # pragma: no cover
                pass

        if changed_fields and "update_fields" in kwargs:  # pragma: no cover
            kwargs["update_fields"].extend(changed_fields)

        return super().save(*args, **kwargs)

    def average_days_between_upload(self, limit_to_latest_videos=5):
        # return None
        if self.videos.count() < 2:
            return

        days_between = []
        prev = None

        qs = self.videos.all().exclude(upload_date__isnull=True)

        if limit_to_latest_videos:
            qs = qs[:limit_to_latest_videos]

        for video in qs:

            if prev:
                diff = prev.upload_date - video.upload_date
                days_between.append(diff.days)

            prev = video

        channel_video_average = round(sum(days_between) / len(days_between))
        # print(f"{self.name: >40} {channel_video_average: >20} {sum(days_between): >20} {len(days_between):>20}")
        return channel_video_average

    def days_since_last_upload(self):

        for video in self.videos.exclude(upload_date__isnull=True):
            diff = timezone.now().date() - video.upload_date
            return diff.days

    def calculated_file_size(self):
        return self.videos.exclude(file="").aggregate(sumd=models.Sum("file_size"))["sumd"] or 0

    def existing_video_qualities(self):

        qualities = {}

        for i in Video.objects.distinct("quality").order_by("quality").values_list("quality"):
            i = i[0]
            base_qs = self.videos.filter(quality=i)
            sumd = base_qs.exclude(file="").aggregate(sumd=models.Sum("file_size"))
            videos_at_this_quality_counter = sumd["sumd"] or 0
            if videos_at_this_quality_counter:
                qualities[i] = (
                    base_qs.count(),
                    videos_at_this_quality_counter,
                    base_qs.filter(at_max_quality=True).count(),
                )

        return qualities

    def total_video_durations(self):
        return self.videos.aggregate(sumd=Sum("duration"))["sumd"]

    def total_archived_video_durations(self):
        return self.videos.exclude(file="").aggregate(sumd=Sum("duration"))["sumd"]

    def existing_video_privacy_statuses(self):

        statuses = {}

        for i in Video.objects.distinct("privacy_status").order_by("privacy_status").values_list("privacy_status"):
            i = i[0]
            base_qs = self.videos.filter(privacy_status=i).exclude(file="")
            videos_counter = base_qs.aggregate(sumd=models.Sum("file_size"))["sumd"] or 0
            if videos_counter:
                statuses[i] = base_qs.count(), videos_counter

        return statuses

    def all_video_privacy_statuses(self):

        statuses = {}

        for i in Video.objects.distinct("privacy_status").order_by("privacy_status").values_list("privacy_status"):
            i = i[0]
            base_qs = self.videos.filter(privacy_status=i)
            videos_counter = base_qs.aggregate(sumd=models.Sum("file_size"))["sumd"] or 0
            if bqs := base_qs.count():
                statuses[i] = bqs, videos_counter

        return statuses

    def is_indexing(self):
        return self.index_videos or self.index_shorts or self.index_livestreams

    def is_downloading(self):
        return self.download_videos or self.download_shorts or self.download_livestreams


class VideoObjectsManager(models.Manager):

    def archived(self):
        return self.exclude(file="")

    def get_or_create_from_ytdlp_response(
        self, data, is_video=False, is_short=False, is_livestream=False
    ) -> [Video, bool]:
        try:
            video = self.get(provider_object_id=data["id"])
            created = False
        except self.model.DoesNotExist:
            # Don't use get_or_create, we need Video.save to be called.
            video = self.model(provider_object_id=data["id"])
            created = True

        video.set_details_from_yt_dlp_response(
            data=data, is_video=is_video, is_short=is_short, is_livestream=is_livestream
        )
        video.save()

        return video, created


class Video(model_helpers.CeleryLockableModel, models.Model):

    class Meta:
        ordering = ["-upload_date", "-inserted"]
        permissions = [
            ("play_videos", "Can play video"),
            ("star_video", "Can Star video"),
        ]

    objects = VideoObjectsManager()

    channel = models.ForeignKey(Channel, on_delete=models.SET_NULL, null=True, blank=True, related_name="videos")

    provider_object_id = models.CharField(max_length=255)
    channel_provider_object_id = models.CharField(max_length=255, blank=True)

    title = models.CharField(max_length=500, blank=True)
    title_locked = models.BooleanField(default=False)

    inserted = models.DateTimeField(null=True, blank=True)
    updated = models.DateTimeField(null=True, blank=True)

    file = models.FileField(upload_to=video_helpers.upload_to_file, blank=True, storage=vidar_storage, max_length=500)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    file_not_found = models.BooleanField(default=False)

    info_json = models.FileField(
        upload_to=video_helpers.upload_to_infojson, blank=True, storage=vidar_storage, max_length=500
    )

    description = models.TextField(blank=True)
    description_locked = models.BooleanField(default=False)

    thumbnail = models.ImageField(
        upload_to=video_helpers.upload_to_thumbnail, storage=vidar_storage, null=True, blank=True, max_length=500
    )

    view_count = models.PositiveIntegerField(null=True, blank=True)
    like_count = models.PositiveIntegerField(null=True, blank=True)

    audio = models.FileField(
        upload_to=video_helpers.upload_to_audio,
        storage=vidar_storage,
        blank=True,
        max_length=500,
    )

    upload_date = models.DateField(null=True, blank=True)

    is_video = models.BooleanField(default=False, help_text="Is this video under the Video tab for this channel?")
    is_short = models.BooleanField(default=False, help_text="Is this video under the Shorts tab for this channel?")
    is_livestream = models.BooleanField(default=False, help_text="Is this video under the Live tab for this channel?")

    force_download = models.BooleanField(default=False)
    watched = models.DateTimeField(null=True, blank=True)

    date_added_to_system = models.DateTimeField(auto_now_add=True)
    date_downloaded = models.DateTimeField(null=True, blank=True)

    duration = models.IntegerField(default=0, blank=True)

    quality = models.PositiveIntegerField(
        help_text="To be set by Channel quality setting.", choices=PossibleQualities, null=True, blank=True
    )
    at_max_quality = models.BooleanField(default=False)

    starred = models.DateTimeField(null=True, blank=True)

    mark_for_deletion = models.BooleanField(
        default=False,
        help_text="Used when downloading music videos and not wanting to keep the resulting files "
        "beyond the daily maintenance task runtime.",
    )

    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    fps = models.IntegerField(default=0)
    format_note = models.TextField(blank=True)
    format_id = models.CharField(max_length=255, blank=True)

    dlp_formats = models.JSONField(null=True, blank=True)

    download_kwargs = models.JSONField(null=True, blank=True, encoder=json_encoders.JSONSetToListEncoder)

    download_comments_on_index = models.BooleanField(default=False)
    download_all_comments = models.BooleanField(default=False)

    convert_to_audio = models.BooleanField(default=False)

    playlists = models.ManyToManyField(
        "vidar.Playlist",
        related_name="videos",
        through="vidar.PlaylistItem",
        through_fields=("video", "playlist"),
        blank=True,
    )

    class VideoPrivacyStatuses(models.TextChoices):
        PUBLIC = "Public"
        PRIVATE = "Private"
        UNLISTED = "Unlisted"
        UNAVAILABLE = "Unavailable"
        DELETED = "Deleted"
        MISSING = "Missing"
        BLOCKED = "Blocked"
        AUTH = "needs_auth", "Needs Auth"

    VideoPrivacyStatuses_Publicly_Visible = [
        VideoPrivacyStatuses.PUBLIC,
        VideoPrivacyStatuses.UNLISTED,
        # VideoPrivacyStatuses.BLOCKED,
    ]

    VideoPrivacyStatuses_Not_Accessible = [
        VideoPrivacyStatuses.PRIVATE,
        VideoPrivacyStatuses.DELETED,
        VideoPrivacyStatuses.MISSING,
        VideoPrivacyStatuses.BLOCKED,
        VideoPrivacyStatuses.AUTH,
        VideoPrivacyStatuses.UNAVAILABLE,
    ]

    privacy_status = models.CharField(
        max_length=255,
        choices=VideoPrivacyStatuses.choices,
        default=VideoPrivacyStatuses.PUBLIC,
    )
    last_privacy_status_check = models.DateTimeField(null=True, blank=True)
    privacy_status_checks = models.IntegerField(default=0)

    system_notes = models.JSONField(blank=True, default=dict, encoder=json_encoders.JSONSetToListEncoder)

    related = models.ManyToManyField("self", blank=True)

    prevent_deletion = models.BooleanField(default=False)

    permit_download = models.BooleanField(default=True)

    sort_ordering = models.PositiveIntegerField(default=0)

    requested_max_quality = models.BooleanField(
        default=False,
        help_text="Tracks whether or not the system requested the max quality be downloaded. "
        "If at a later date the quality upgrades, this could catch those changes.",
    )

    playback_speed = models.CharField(max_length=10, blank=True, choices=model_helpers.PlaybackSpeed.choices)
    playback_volume = models.CharField(
        max_length=10,
        blank=True,
        choices=model_helpers.PlaybackVolume.choices,
    )

    delete_after_watching = models.BooleanField(
        default=False,
        help_text="Delete video once it has been watched?",
    )

    download_requested_by = models.CharField(
        max_length=255, blank=True, help_text="What triggered this video to download?"
    )
    filename_schema = models.CharField(
        max_length=500,
        blank=True,
        help_text=model_helpers.FILENAME_SCHEMA_HELP_TEXT,
    )
    directory_schema = models.CharField(
        max_length=500,
        blank=True,
        help_text=model_helpers.DIRECTORY_SCHEMA_HELP_TEXT,
    )

    needs_cookies = models.BooleanField(
        default=False,
        help_text="Does access to this video require cookies?",
    )

    def __str__(self):
        return self.title or "<Title Placeholder>"

    def __repr__(self):
        return f"<{self.__class__.__name__}.pk={self.pk}: {self.title}>"

    def get_absolute_url(self):  # pragma: no cover
        return reverse("vidar:video-detail", args=[self.pk])

    @property
    def url(self):  # pragma: no cover
        return f"https://www.youtube.com/watch?v={self.provider_object_id}"

    def save(self, *args, **kwargs):

        if not self.inserted:
            self.inserted = timezone.now()
            if "update_fields" in kwargs and "inserted" not in kwargs["update_fields"]:
                kwargs["update_fields"].append("inserted")

        self.updated = timezone.now()

        if "update_fields" in kwargs and "updated" not in kwargs["update_fields"]:
            kwargs["update_fields"].append("updated")

        if self.pk:
            original_obj = Video.objects.get(pk=self.pk)
            values = {}

            # Video must have a title because the way our system works is that it create the
            # video entry with just the youtube_id and then applies the details.
            if original_obj.title and self.title != original_obj.title:
                values["new_title"] = self.title
                values["old_title"] = original_obj.title

            if original_obj.description and self.description != original_obj.description:
                values["new_description"] = self.description
                values["old_description"] = original_obj.description

            if original_obj.privacy_status and self.privacy_status != original_obj.privacy_status:
                values["new_privacy_status"] = self.privacy_status
                values["old_privacy_status"] = original_obj.privacy_status

            if values:
                self.change_history.create(**values)

        if self.channel and not self.sort_ordering:
            last_obj = self.channel.videos.order_by("sort_ordering").last()
            last_id = 0
            if last_obj:
                last_id = last_obj.sort_ordering

            new_id = last_id + 1

            self.sort_ordering = new_id

            if "update_fields" in kwargs:
                kwargs["update_fields"].append("sort_ordering")

        return super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False, deletion_permitted=False):
        if not deletion_permitted:
            raise exceptions.UnauthorizedVideoDeletionError("Use video_services to delete a Video object.")
        return super().delete(using=using, keep_parents=keep_parents)

    def embed_url(self):  # pragma: no cover
        return f"https://www.youtube.com/embed/{self.provider_object_id}"

    @property
    def system_safe_title(self):
        safe_string = "".join([c for c in self.title if c.isalnum() or c == " "]).rstrip()
        safe_string_without_multiple_spaces = " ".join(safe_string.split())
        return safe_string_without_multiple_spaces

    @property
    def system_safe_title_the(self):
        current_title = self.system_safe_title
        if current_title.lower().startswith("the "):
            cased_the = current_title[:4].strip()
            title_without_the = current_title[4:]
            current_title = f"{title_without_the}, {cased_the}"
        return current_title

    def set_details_from_yt_dlp_response(self, data, is_video=False, is_short=False, is_livestream=False):

        if not self.title:
            if title := data.get("title"):
                if title != f"youtube video #{self.provider_object_id}":
                    self.title = title
        elif not self.title_locked:
            if title := data.get("title"):
                if title != f"youtube video #{self.provider_object_id}":
                    self.title = title

        if not self.description:
            if description := data.get("description"):
                self.description = description
        elif not self.description_locked:
            if description := data.get("description"):
                self.description = description

        simple_fields = ["view_count", "like_count", "duration", "width", "height", "fps"]
        for field in simple_fields:
            if live_data := data.get(field):
                setattr(self, field, live_data)

        if channel_provider_object_id := data.get("channel_id"):
            self.channel_provider_object_id = channel_provider_object_id

            if not self.channel:
                try:
                    self.channel = Channel.objects.get(provider_object_id=self.channel_provider_object_id)
                except Channel.DoesNotExist:
                    pass

        if live_upload_date_raw := data.get("upload_date"):
            self.upload_date = datetime.datetime.strptime(live_upload_date_raw, "%Y%m%d").date()
        elif not self.upload_date:
            self.upload_date = timezone.make_aware(timezone.datetime.fromtimestamp(0))

        if formats := data.get("formats"):
            self.dlp_formats = formats

        if live_status := data.get("availability"):
            status_mapping = {
                "unlisted": Video.VideoPrivacyStatuses.UNLISTED,
                "public": Video.VideoPrivacyStatuses.PUBLIC,
                "private": Video.VideoPrivacyStatuses.PRIVATE,
                "deleted": Video.VideoPrivacyStatuses.DELETED,
            }
            if wanted_status := status_mapping.get(live_status.lower()):
                self.privacy_status = wanted_status

            elif data["title"] and data["description"]:
                self.privacy_status = Video.VideoPrivacyStatuses.PUBLIC
            else:
                self.privacy_status = live_status

            self.last_privacy_status_check = timezone.now()

        if (
            any([is_video, is_short, is_livestream])
            and not self.is_video
            and not self.is_short
            and not self.is_livestream
        ):
            if is_video:
                self.is_video = True
            if is_short:
                self.is_short = True
            if is_livestream:
                self.is_livestream = True
        else:
            if not self.is_video and not self.is_short and not self.is_livestream:
                if orig_url := data.get("original_url"):
                    if "/shorts/" in orig_url:
                        self.is_short = True

            if not self.is_video and not self.is_short and not self.is_livestream:
                if data.get("was_live"):
                    self.is_livestream = True

            if not self.is_video and not self.is_short and not self.is_livestream:
                self.is_video = True

    def duration_as_timedelta(self):
        return datetime.timedelta(seconds=self.duration)

    def qualities_upgradable(self):

        if self.dlp_formats:
            if self.quality is not None:
                return ytdlp_services.get_higher_qualities_from_video_dlp_formats(self.dlp_formats, self.quality)
            return ytdlp_services.get_possible_qualities_from_dlp_formats(self.dlp_formats)

        return [self.quality]

    def qualities_available(self):
        if self.dlp_formats:
            return ytdlp_services.get_possible_qualities_from_dlp_formats(self.dlp_formats)

        if self.quality is None:
            return [app_settings.DEFAULT_QUALITY]

        return [self.quality]

    def log_to_scanhistory(self):
        if not self.channel:
            return

        try:
            history = self.channel.scan_history.latest("inserted")
            # history = self.channel.scan_history.create()

            self.channel.scan_history.filter(pk=history.pk).update(
                videos_downloaded=F("videos_downloaded") + int(self.is_video),
                shorts_downloaded=F("shorts_downloaded") + int(self.is_short),
                livestreams_downloaded=F("livestreams_downloaded") + int(self.is_livestream),
            )
            return True
        except ScanHistory.DoesNotExist:
            pass

    def channel_page_number(self):
        return math.ceil(
            self.channel.videos.filter(
                upload_date__gt=self.upload_date or timezone.now(),
            ).count()
            / 10
        )

    def save_download_kwargs(self, kwargs):
        self.download_kwargs = json_safe_kwargs(kwargs)
        self.save()

    def save_system_notes(self, kwargs, commit=True):

        kwargs = json_safe_kwargs(kwargs)

        if "proxy" in kwargs:
            proxies_attempted = self.system_notes.get("proxies_attempted", [])
            proxies_attempted.append(kwargs["proxy"])
            self.system_notes["proxies_attempted"] = proxies_attempted

            if commit:
                self.save()

    def at_max_download_errors_for_period(self, period=None):
        if period is None:
            period = timezone.timedelta(hours=24)
        time_ago = timezone.localtime() - period
        max_dl_attempts = app_settings.VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS
        return self.download_errors.filter(inserted__gt=time_ago).count() >= max_dl_attempts

    def is_at_max_quality(self):
        if self.at_max_quality:
            return True
        if self.dlp_formats:
            if ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, self.quality):
                log.info(f"Setting at_max_quality=True on Video.id={self.pk} : True based on dlp_formats.")
                self.at_max_quality = True
                self.save()
        return self.at_max_quality

    def check_and_add_video_to_playlists_based_on_title_matching(self):
        playlists_with_potential_matches = Playlist.objects.exclude(video_indexing_add_by_title="")
        playlists_added_to = set()
        for playlist in playlists_with_potential_matches:

            # If videos must be on a specific channel, only add if the video is on that channel,
            #   if it has no channel, skip as well.
            these_channels_only = playlist.video_indexing_add_by_title_limit_to_channels
            if these_channels_only.exists():
                if not self.channel:
                    continue
                if not these_channels_only.filter(id=self.channel_id).exists():
                    continue

            for potential_match in playlist.video_indexing_add_by_title.splitlines():
                if potential_match.lower() in self.title.lower():
                    playlists_added_to.add(playlist)
                    pli, pli_created = playlist.playlistitem_set.get_or_create(
                        video=self, defaults={"manually_added": True}
                    )
                    if pli_created:
                        notification_services.video_added_to_playlist(video=self, playlist=playlist)
                    break

        return playlists_added_to

    def search_description_for_related_videos(self):
        if not self.description:
            log.info(f"No description found on {self=}")
            return

        for url in re.findall(r"(https?://[^\s]+)", self.description):

            if "yout" not in url:
                continue

            url = url.replace("(", "").replace(")", "").replace(":", "").replace(",", "")

            if ytid := utils.get_video_id_from_url(url):

                ytid = ytid.strip()

                if ytid == self.provider_object_id:
                    continue

                for video2 in Video.objects.filter(provider_object_id=ytid):
                    log.info(f"Relating {self=} to {video2=}")
                    self.related.add(video2)

    def apply_privacy_status_based_on_dlp_exception_message(self, exception_message):
        exc_msg = str(exception_message).lower()
        if "blocked" in exc_msg and "country" in exc_msg:
            self.privacy_status = Video.VideoPrivacyStatuses.BLOCKED
            self.last_privacy_status_check = timezone.now()
            self.save()
            return True
        if "private video" in exc_msg:
            self.privacy_status = Video.VideoPrivacyStatuses.PRIVATE
            self.last_privacy_status_check = timezone.now()
            self.save()
            return True
        if "video unavailable" in exc_msg or "video is not available" in exc_msg:
            self.privacy_status = Video.VideoPrivacyStatuses.UNAVAILABLE
            self.last_privacy_status_check = timezone.now()
            self.save()
            return True
        if (
            "deleted video" in exc_msg
            or "copyright claim" in exc_msg
            or "terminated" in exc_msg
            or ("closed" in exc_msg and "account" in exc_msg)
            or ("removed" in exc_msg and "harassment" in exc_msg)
            or ("removed" in exc_msg and "violating" in exc_msg)
            or ("removed" in exc_msg and "bullying" in exc_msg)
        ):
            self.privacy_status = Video.VideoPrivacyStatuses.DELETED
            self.last_privacy_status_check = timezone.now()
            self.save()
            return True

    def set_latest_download_stats(self, commit=True, **kwargs):
        if "downloads" not in self.system_notes:
            self.system_notes["downloads"] = []

        kwargs = json_safe_kwargs(kwargs)

        self.system_notes["downloads"].append(kwargs)
        if commit:
            self.save()

        return kwargs

    def get_latest_download_stats(self) -> dict:
        if not self.system_notes.get("downloads"):
            return {}
        return self.system_notes["downloads"][-1]

    def append_to_latest_download_stats(self, commit=True, **kwargs):
        latest = self.get_latest_download_stats()

        kwargs = json_safe_kwargs(kwargs)

        if latest:
            latest.update(kwargs)
            if commit:
                self.save()
        else:
            return self.set_latest_download_stats(commit=commit, **kwargs)

        return latest

    def metadata_album(self):
        return app_settings.METADATA_ALBUM(video=self)

    def metadata_artist(self):
        return app_settings.METADATA_ARTIST(video=self)


class VideoBlocked(models.Model):
    provider_object_id = models.CharField(max_length=255)
    channel_id = models.CharField(max_length=255, blank=True)

    title = models.CharField(max_length=500, blank=True)

    inserted = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-inserted"]

    def __str__(self):  # pragma: no cover
        return self.provider_object_id

    @property
    def url(self):  # pragma: no cover
        return f"https://www.youtube.com/watch?v={self.provider_object_id}"

    def is_still_local(self):
        return Video.objects.filter(provider_object_id=self.provider_object_id).exists()

    def local_url(self):  # pragma: no cover
        return reverse("vidar:video-detail", args=[self.provider_object_id])


class VideoDownloadError(models.Model):

    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="download_errors")

    traceback = models.TextField(blank=True)

    kwargs = models.JSONField(null=True, blank=True, encoder=json_encoders.JSONSetToListEncoder)

    quality = models.CharField(max_length=255, blank=True, null=True)
    selected_quality = models.CharField(max_length=255, blank=True, null=True)

    retries = models.PositiveIntegerField(default=0)

    inserted = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-inserted"]
        get_latest_by = "inserted"

    def save_kwargs(self, kwargs, commit=True):
        self.kwargs = json_safe_kwargs(kwargs)
        if commit:
            self.save()


class VideoNote(models.Model):

    class Meta:
        ordering = ["-inserted"]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="notes")

    note = models.TextField()

    inserted = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)


class VideoHistory(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="change_history")
    inserted = models.DateTimeField(auto_now_add=True)

    old_title = models.CharField(max_length=500, blank=True)
    new_title = models.CharField(max_length=500, blank=True)

    old_description = models.TextField(blank=True)
    new_description = models.TextField(blank=True)

    old_privacy_status = models.TextField(blank=True)
    new_privacy_status = models.TextField(blank=True)

    class Meta:
        ordering = ["-inserted"]
        verbose_name = "Video Change History"
        verbose_name_plural = "Video Change History"

    def title_changed(self):
        return self.old_title != self.new_title

    def description_changed(self):
        return self.old_description != self.new_description

    def privacy_status_changed(self):
        return self.old_privacy_status != self.new_privacy_status

    def diff(self):
        line_diffs = []
        titles = []
        if self.title_changed():
            titles.append("<h3>Title</h3>\n")
            diff = difflib.Differ().compare(self.old_title.splitlines(), self.new_title.splitlines())
            line_diffs.append("\n".join([line for line in diff if not line.startswith(" ")]))
        if self.description_changed():
            titles.append("<h3>Description</h3>\n")
            diff = difflib.Differ().compare(self.old_description.splitlines(), self.new_description.splitlines())
            line_diffs.append("\n".join([line for line in diff if not line.startswith(" ")]))
        if self.privacy_status_changed():
            titles.append("<h3>Status</h3>\n")
            diff = difflib.Differ().compare(self.old_privacy_status.splitlines(), self.new_privacy_status.splitlines())
            line_diffs.append("\n".join([line for line in diff if not line.startswith(" ")]))

        if len(line_diffs) > 1:
            output = []
            for t, l in zip(titles, line_diffs):
                output.append(t + l)
            return "\n".join(output)

        return "\n".join(line_diffs)


class PlaylistObjectsManager(models.Manager):

    @functools.lru_cache(maxsize=50)
    def get_user_watch_later(self, user) -> Playlist:
        playlist, _ = self.get_or_create(
            user=user,
            title="Watch Later",
            provider_object_id="",
        )
        return playlist

    def already_exists(self, provider_object_id):
        try:
            return self.get(Q(provider_object_id=provider_object_id) | Q(provider_object_id_old=provider_object_id))
        except Playlist.DoesNotExist:
            pass


class Playlist(models.Model):

    objects = PlaylistObjectsManager()

    provider_object_id = models.CharField(max_length=255, blank=True)
    provider_object_id_old = models.CharField(
        max_length=255,
        blank=True,
        help_text="System Internal ID. Used when converting playlist to custom and "
        "preventing user/mirroring from adding it again.",
    )
    title = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True, null=True)

    last_scanned = models.DateTimeField(null=True, blank=True)

    crontab = models.CharField(max_length=50, blank=True, help_text="minute, hour, day of month, month, day of week")

    convert_to_audio = models.BooleanField(default=False, help_text="Create an mp3 file of the video?")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    channel_provider_object_id = models.CharField(max_length=255, blank=True, null=True)
    channel = models.ForeignKey(Channel, on_delete=models.SET_NULL, null=True, blank=True, related_name="playlists")

    title_skips = models.TextField(
        blank=True,
        verbose_name="Skip DL by Title contains",
        help_text="If any of these words appear in the title, do not download the video. ONE PER LINE. i.e. #shorts",
    )

    sync_deletions = models.BooleanField(default=False)

    disable_when_string_found_in_video_title = models.TextField(
        blank=True,
        help_text="Disable this playlist when this string is found in the a videos title. Case-insensitive e.g. finale."
        " Spaces are preserved, one per line.",
    )

    quality = models.PositiveIntegerField(
        help_text="What minimum quality do you want these videos to be? "
        "Quality will be disabled automatically when the playlist is not "
        "enabled and all videos reach this quality selection. Videos that cannot "
        "reach this quality will be downloaded at the best available.",
        choices=PossibleQualities,
        null=True,
        blank=True,
        default=None,
    )

    playback_speed = models.CharField(max_length=10, blank=True, choices=model_helpers.PlaybackSpeed.choices)
    playback_volume = models.CharField(
        max_length=10,
        blank=True,
        choices=model_helpers.PlaybackVolume.choices,
    )
    filename_schema = models.CharField(
        max_length=500,
        blank=True,
        help_text=model_helpers.FILENAME_SCHEMA_HELP_TEXT,
    )
    directory_schema = models.CharField(
        max_length=500,
        blank=True,
        help_text=model_helpers.DIRECTORY_SCHEMA_HELP_TEXT,
    )

    class PlaylistVideoOrderingChoices(models.TextChoices):
        DEFAULT = "default", "Default (display order)"
        DEFAULT_REVERSED = "default_reversed", "Reversed display order"
        VIDEO_UPLOAD_DATE_ASC = "video_upload_date_asc", "Upload Date Ascending (oldest first)"
        VIDEO_UPLOAD_DATE_DESC = "video_upload_date_desc", "Upload Date Descending (newest first)"

    videos_display_ordering = models.CharField(
        max_length=255,
        choices=PlaylistVideoOrderingChoices.choices,
        default=PlaylistVideoOrderingChoices.DEFAULT,
        help_text="How do you want the videos in this playlist to be displayed?",
    )
    videos_playback_ordering = models.CharField(
        max_length=255,
        choices=PlaylistVideoOrderingChoices.choices,
        default=PlaylistVideoOrderingChoices.DEFAULT,
        help_text="How do you want the videos in this playlist to be played during automated playback?",
    )

    inserted = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    not_found_failures = models.PositiveIntegerField(default=0)

    video_indexing_add_by_title = models.TextField(
        blank=True,
        help_text="When indexing videos, if the video title contains the following text, "
        "add it to this playlist. One match per line.",
    )
    video_indexing_add_by_title_limit_to_channels = models.ManyToManyField(
        Channel,
        blank=True,
        related_name="+",
        help_text="When indexing videos and attempting to match video titles, "
        "the video must be uploaded by these channels. Use CTRL+Click to select or de-select channels.",
    )

    hidden = models.BooleanField(
        default=False,
        help_text="Hide this playlist from list view. This also prevents "
        "the system from downloading any videos attached to it.",
    )

    download_comments_on_index = models.BooleanField(default=False)

    restrict_to_assigned_channel = models.BooleanField(
        default=False,
        help_text="Videos on playlist must also be assigned to the same channel that the playlist is assigned to.",
    )

    remove_video_from_playlist_on_watched = models.BooleanField(
        default=False, help_text="Watch Later playlist allows videos to be auto-removed from list upon watching."
    )

    next_playlist = models.OneToOneField(
        "vidar.Playlist",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="previous_playlist",
        help_text="When auto-playing, you can set the next playlist to automatically go into. " "i.e. music playlists.",
    )

    class Meta:
        ordering = ["channel", "title"]

    def __str__(self):  # pragma: no cover
        if self.channel:
            return f"{self.channel}: {self.title}"
        return self.title

    def get_absolute_url(self):  # pragma: no cover
        return reverse("vidar:playlist-detail", args=[self.pk])

    def save(self, *args, **kwargs):

        if not self.provider_object_id:
            self.crontab = ""
        else:
            self.video_indexing_add_by_title = ""

        if self.hidden:
            self.crontab = ""
            self.video_indexing_add_by_title = ""
            self.disable_when_string_found_in_video_title = ""

        value = super().save(*args, **kwargs)

        if self.provider_object_id:
            for c in self.video_indexing_add_by_title_limit_to_channels.all():
                self.video_indexing_add_by_title_limit_to_channels.remove(c)

        return value

    @property
    def url(self):  # pragma: no cover
        return f"https://www.youtube.com/playlist?list={self.provider_object_id}"

    def missing_videos(self):
        return self.playlistitem_set.filter(Q(video__isnull=True) | Q(video__file=""))

    def archived_videos(self):
        return self.playlistitem_set.exclude(Q(video__isnull=True) | Q(video__file=""))

    def items_missing_from_live(self):
        return self.playlistitem_set.filter(missing_from_playlist_on_provider=True)

    def latest_video_by_upload_date(self):
        try:
            return self.playlistitem_set.order_by("-video__upload_date").first().video
        except AttributeError:
            pass

    def apply_display_ordering_to_queryset(self, queryset):
        if self.videos_display_ordering != Playlist.PlaylistVideoOrderingChoices.DEFAULT:
            if self.videos_display_ordering == Playlist.PlaylistVideoOrderingChoices.DEFAULT_REVERSED:
                return queryset.order_by("-display_order")
            elif self.videos_display_ordering == Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_ASC:
                return queryset.order_by("video__upload_date")
            elif self.videos_display_ordering == Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_DESC:
                return queryset.order_by("-video__upload_date")
        return queryset.order_by("display_order")

    def apply_playback_ordering_to_queryset(self, queryset):
        if self.videos_playback_ordering != Playlist.PlaylistVideoOrderingChoices.DEFAULT:
            if self.videos_playback_ordering == Playlist.PlaylistVideoOrderingChoices.DEFAULT_REVERSED:
                return queryset.order_by("-pk")
            elif self.videos_playback_ordering == Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_ASC:
                return queryset.order_by("video__upload_date")
            elif self.videos_playback_ordering == Playlist.PlaylistVideoOrderingChoices.VIDEO_UPLOAD_DATE_DESC:
                return queryset.order_by("-video__upload_date")
        return queryset

    def calculated_file_size(self):
        return self.videos.exclude(file="").aggregate(sumd=models.Sum("file_size"))["sumd"] or 0

    def calculated_duration(self):
        return self.videos.exclude(file="").aggregate(sumd=models.Sum("duration"))["sumd"] or 0

    def calculated_duration_as_timedelta(self):
        return datetime.timedelta(seconds=self.calculated_duration())

    @cached_property
    def next_runtime(self):
        if not self.crontab:
            return

        now = timezone.localtime()

        # Round to nearest 5 minutes
        rounded_minute = 10 * round(now.minute / 10)
        hour = now.hour

        if rounded_minute >= 60:
            rounded_minute = 0
            hour = now.hour + 1
        now = now.replace(
            hour=hour,
            minute=rounded_minute,
        )

        while True:

            if crontab_services.is_active_now(self.crontab, now):
                return now

            now = now + timezone.timedelta(minutes=5)


class PlaylistItem(models.Model):
    class Meta:
        ordering = ["display_order"]

    provider_object_id = models.CharField(max_length=255)

    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE)

    video = models.ForeignKey(Video, on_delete=models.CASCADE)

    missing_from_playlist_on_provider = models.BooleanField(default=False)

    display_order = PositionField(default=-1, collection="playlist")

    manually_added = models.BooleanField(default=False)

    download = models.BooleanField(default=True)

    wl_playlist = models.ForeignKey(
        Playlist,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Internal system field, do not use. Links watch later item to a specific playlist.",
    )

    inserted = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __repr__(self):
        return f"PLI:{self.pk} : V:{self.video} : P:{self.playlist}"

    def get_absolute_url(self):  # pragma: no cover
        return self.video.get_absolute_url()

    def get_playback_url(self):
        return mark_safe(f"{self.video.get_absolute_url()}?next=playlist&playlist={self.playlist_id}")


class Comment(MPTTModel):
    """
    [
        {
            'author': 'Advoko MAKES',
            'author_id': 'UCc1ufNROdAxto9Fr0jnEE2Q',
            'author_is_uploader': True,
            'author_thumbnail': 'http...',
            'id': 'UgynJfLhxc5OXSVduop4AaABAg',
            'is_favorited': False,
            'like_count': 185,
            'parent': 'root',
            'text': 'Friends, thank your patients during these months I filled a lot of '
                 'content at my log cabin camp which prevented me from producing new '
                 'video. At the very end of this video, you can catch a glimpse at '
                 'what is to come. Happy Holidays!!!',
            'time_text': '3 hours ago',
            'timestamp': 1671577200
        },
        {
            'author': 'Wesley Sturgis',
            'author_id': 'UCdqj4IyueP-hVX6PgxDrEvw',
            'author_is_uploader': False,
            'author_thumbnail': 'http...',
            'id': 'UgynJfLhxc5OXSVduop4AaABAg.9jsXwRiSQw29jsZBZ4jFc9',
            'is_favorited': False,
            'like_count': 8,
            'parent': 'UgynJfLhxc5OXSVduop4AaABAg',
            'text': 'It is wonderful to see you back.😍',
            'time_text': '3 hours ago',
            'timestamp': 1671577200
        }
    ]
    """

    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="comments")

    id = models.CharField(max_length=255, primary_key=True)

    author = models.CharField(max_length=500, blank=True, null=True)
    author_id = models.CharField(max_length=255, blank=True, null=True)
    author_is_uploader = models.BooleanField(default=False)
    author_thumbnail = models.CharField(max_length=500, null=True, blank=True)

    parent_youtube_id = models.CharField(max_length=255, blank=True, null=True)
    parent = TreeForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")

    text = models.TextField(blank=True)

    timestamp = models.DateTimeField(null=True, blank=True)
    like_count = models.PositiveIntegerField(default=0)
    is_favorited = models.BooleanField(default=False)

    inserted = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)


class ScanHistory(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="scan_history", null=True, blank=True)
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="scan_history", null=True, blank=True)

    videos_downloaded = models.PositiveIntegerField(default=0)
    shorts_downloaded = models.PositiveIntegerField(default=0)
    livestreams_downloaded = models.PositiveIntegerField(default=0)

    inserted = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-inserted"]

    def __str__(self):  # pragma: no cover
        return (
            f"{self.channel=} {self.inserted=} {self.updated=} "
            f"{self.videos_downloaded=} {self.shorts_downloaded=} {self.livestreams_downloaded=}"
        )


class UserPlaybackHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="video_playback_history")
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="user_playback_history")

    playlist = models.ForeignKey(Playlist, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    seconds = models.PositiveBigIntegerField()

    inserted = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated"]
        get_latest_by = ["updated"]

    def completion_percentage(self):
        percentage = math.ceil((self.seconds / self.video.duration) * 100)
        if percentage > 99.0:
            return 100
        return percentage

    def considered_fully_played(self):
        if not hasattr(self.user, "vidar_playback_completion_percentage"):  # pragma: no cover
            return False
        return self.completion_percentage() >= (float(self.user.vidar_playback_completion_percentage) * 100)


class DurationSkip(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="duration_skips")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()

    inserted = models.DateTimeField(auto_now_add=True)

    sb_uuid = models.CharField(max_length=255, blank=True)
    sb_category = models.CharField(max_length=255, blank=True)
    sb_votes = models.IntegerField(default=0, blank=True)
    sb_data = models.JSONField(blank=True, default=dict)

    class Meta:
        ordering = ["video", "start"]


class Highlight(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="highlights")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="video_highlights"
    )

    point = models.PositiveIntegerField()
    end_point = models.PositiveIntegerField(blank=True, null=True, default=None)
    note = models.TextField(blank=True)

    class Sources(models.TextChoices):
        USER = "User"
        CHAPTERS = "Chapters"
        POI = "POI"

    source = models.CharField(max_length=50, choices=Sources.choices)

    inserted = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["video", "point"]
        permissions = [
            ("change_chapter", "Can change chapters"),
        ]

    def get_absolute_url(self):
        if self.source == Highlight.Sources.CHAPTERS:
            return reverse("vidar:video-chapter-list", args=[self.video_id])
        return reverse("vidar:video-highlight-list", args=[self.video_id])

    def get_live_url(self):
        return f"{self.video.url}&t={self.point}s"


class ExtraFile(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="extra_files")

    file = models.FileField(upload_to=extrafile_helpers.extrafile_file_upload_to, storage=vidar_storage, max_length=500)

    note = models.TextField(blank=True)

    inserted = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
