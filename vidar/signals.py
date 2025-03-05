from django.dispatch import Signal


pre_daily_maintenance = Signal()
post_daily_maintenance = Signal()

pre_monthly_maintenance = Signal()
post_monthly_maintenance = Signal()

video_download_successful = Signal()
