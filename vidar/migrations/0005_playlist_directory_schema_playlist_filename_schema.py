# Generated by Django 5.1.8 on 2025-04-05 12:05

from django.db import migrations, models

import vidar.helpers.model_helpers


class Migration(migrations.Migration):

    dependencies = [
        ('vidar', '0004_playlist_next_playlist'),
    ]

    operations = [
        migrations.AddField(
            model_name='playlist',
            name='directory_schema',
            field=models.CharField(blank=True, help_text=vidar.helpers.model_helpers.DIRECTORY_SCHEMA_HELP_TEXT, max_length=500),
        ),
        migrations.AddField(
            model_name='playlist',
            name='filename_schema',
            field=models.CharField(blank=True, help_text=vidar.helpers.model_helpers.FILENAME_SCHEMA_HELP_TEXT, max_length=500),
        ),
    ]
