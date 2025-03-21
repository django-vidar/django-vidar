from django.contrib import admin

from vidar.models import (
    Channel,
    Comment,
    DurationSkip,
    ExtraFile,
    Highlight,
    Playlist,
    ScanHistory,
    UserPlaybackHistory,
    Video,
    VideoBlocked,
    VideoDownloadError,
    VideoHistory,
    VideoNote,
)


@admin.register(
    Channel,
    Comment,
    DurationSkip,
    ExtraFile,
    Highlight,
    Playlist,
    ScanHistory,
    VideoDownloadError,
    VideoBlocked,
    VideoNote,
    UserPlaybackHistory,
)
class GeneralAdmin(admin.ModelAdmin):
    pass


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("channel", "title")
    list_display_links = ("title",)
    search_fields = ("title",)
    exclude = ["related"]


@admin.register(VideoHistory)
class VideoHistoryAdmin(admin.ModelAdmin):
    raw_id_fields = ("video",)
    list_display = ["video", "old_title", "new_title", "old_description", "new_description"]
