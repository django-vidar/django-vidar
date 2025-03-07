import logging

from django.template import Context, Template

from vidar import app_settings, exceptions


log = logging.getLogger(__name__)


def _render_string_using_object_data(string, **kwargs):
    """
    Renders a string using the Django template engine.

    Returns:
        str: The rendered string.
    """
    template = Template(string)
    context = Context(kwargs)
    safe_string = template.render(context)

    # Convert SafeString into str with strip
    rendered_string = safe_string.strip()

    return rendered_string


def channel_directory_name(channel):

    if channel.directory_schema:
        if rendered_value := _render_string_using_object_data(channel.directory_schema, self=channel, channel=channel):
            return rendered_value

        log.critical(f"{channel=} has an invalid directory schema {channel.directory_schema=}. Using system default.")

    if rendered_value := _render_string_using_object_data(
        app_settings.CHANNEL_DIRECTORY_SCHEMA, self=channel, channel=channel
    ):
        return rendered_value

    raise exceptions.DirectorySchemaInvalidError(
        f"VIDAR_CHANNEL_DIRECTORY_SCHEMA has an invalid schema of {app_settings.CHANNEL_DIRECTORY_SCHEMA}.",
        app_settings.CHANNEL_DIRECTORY_SCHEMA,
    )


def video_directory_name(video):

    if video.directory_schema:
        if rendered_value := _render_string_using_object_data(
            video.directory_schema,
            self=video,
            video=video,
        ):
            return rendered_value

        log.critical(f"{video.pk=} has an invalid value in {video.directory_schema=}.")

    if video.channel and video.channel.video_directory_schema:
        if rendered_value := _render_string_using_object_data(
            video.channel.video_directory_schema, self=video, video=video
        ):
            return rendered_value

        log.critical(f"{video.pk=} {video.channel=} has an invalid value in {video.channel.video_directory_schema=}.")

    if rendered_value := _render_string_using_object_data(app_settings.VIDEO_DIRECTORY_SCHEMA, self=video, video=video):
        return rendered_value

    raise exceptions.DirectorySchemaInvalidError(
        f"VIDAR_VIDEO_DIRECTORY_SCHEMA has an invalid schema of {app_settings.VIDEO_DIRECTORY_SCHEMA}.",
        app_settings.VIDEO_DIRECTORY_SCHEMA,
    )


def video_file_name(video, ext):

    rendered_value = None

    if not rendered_value and video.filename_schema:
        rendered_value = _render_string_using_object_data(
            video.filename_schema,
            self=video,
            video=video,
        )
        if not rendered_value:
            log.critical(f"{video.pk=} has an invalid value in {video.filename_schema=}.")

    if not rendered_value and video.channel and video.channel.video_filename_schema:
        rendered_value = _render_string_using_object_data(
            video.channel.video_filename_schema, self=video, video=video, channel=video.channel
        )
        if not rendered_value:
            log.critical(f"{video.pk=} {video.channel=} has an invalid schema {video.channel.video_filename_schema=}.")

    if not rendered_value:
        rendered_value = _render_string_using_object_data(app_settings.VIDEO_FILENAME_SCHEMA, self=video, video=video)

    if not rendered_value:
        raise exceptions.FilenameSchemaInvalidError(
            f"System VIDAR_VIDEO_FILENAME_SCHEMA has an invalid schema of {app_settings.VIDEO_FILENAME_SCHEMA}.",
            app_settings.VIDEO_FILENAME_SCHEMA,
        )

    if ext:
        return f"{rendered_value}.{ext}"

    return rendered_value
