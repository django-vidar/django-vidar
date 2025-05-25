from django.dispatch import Signal


pre_daily_maintenance = Signal()
post_daily_maintenance = Signal()

pre_monthly_maintenance = Signal()
post_monthly_maintenance = Signal()

# Related to the act of downloading the video itself, processing still to be done.
video_download_started = Signal()
video_download_finished = Signal()
video_download_failed = Signal()
video_download_retry = Signal()

# Download and processing success, basically everything is done.
video_download_successful = Signal()
