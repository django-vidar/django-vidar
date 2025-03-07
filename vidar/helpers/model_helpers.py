from django.db import models


class CeleryLockableModel(models.Model):
    class Meta:
        abstract = True

    def celery_object_lock_key(self, action="processing"):
        return f"{self.__class__.__name__}-{self.pk}-{action}"

    def celery_object_lock_timeout(self):
        return 6 * 60 * 60  # Lock expires in 6 hours


class PlaybackCompletionPercentage(models.TextChoices):
    FIFTY = "0.5", "50%"
    SEVENTY_FIVE = "0.75", "75%"
    EIGHTY = "0.8", "80%"
    EIGHTY_FIVE = "0.85", "85%"
    NINTY = "0.9", "90%"
    NINTY_FIVE = "0.95", "95%"
    FULL = "1.0", "100%"


class PlaybackSpeed(models.TextChoices):
    NORMAL = "1.0", "1.0"
    ONE_TWENTY_FIVE = "1.25", "1.25"
    ONE_FIFTY = "1.5", "1.5"
    ONE_SEVENTY_FIVE = "1.75", "1.75"
    TWO = "2.0", "2.0"


class PlaybackVolume(models.TextChoices):
    MUTE = "0.0", "0"
    TWENTY_FIVE = "0.25", "25%"
    FIFTY = "0.5", "50%"
    SEVENTY_FIVE = "0.75", "75%"
    FULL = "1.0", "100%"
