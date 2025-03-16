from django.contrib.auth.models import AbstractUser
from django.db import models

from vidar.helpers.model_helpers import PlaybackVolume, PlaybackSpeed, PlaybackCompletionPercentage


class User(AbstractUser):

    vidar_playback_completion_percentage = models.CharField(
        max_length=10,
        default=PlaybackCompletionPercentage.SEVENTY_FIVE,
        choices=PlaybackCompletionPercentage.choices,
        verbose_name="Vidar - Default Completion Percentage",
        help_text="How far into a video do you consider it fully watched?"
    )

    vidar_playback_speed = models.CharField(
        max_length=10,
        blank=True,
        choices=PlaybackSpeed.choices,
        verbose_name="Vidar - Default Playback Speed",
    )
    vidar_playback_speed_audio = models.CharField(
        max_length=10,
        blank=True,
        choices=PlaybackSpeed.choices,
        verbose_name="Vidar - Default Playback Speed for Audio view",
    )

    vidar_playback_volume = models.CharField(
        max_length=10,
        blank=True,
        choices=PlaybackVolume.choices,
        verbose_name="Vidar - Default Volume",
    )


class TestModel(models.Model):
    __test__ = False  # pytest
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    search_field = models.TextField(blank=True)

    boolean_field = models.BooleanField(null=True, blank=True)

    def get_absolute_url(self):
        return "TestModelURL"
