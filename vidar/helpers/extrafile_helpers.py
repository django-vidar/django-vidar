from vidar.helpers.video_helpers import video_upload_to_side_by_side


def extrafile_file_upload_to(instance, filename):
    return video_upload_to_side_by_side(instance.video, filename)
