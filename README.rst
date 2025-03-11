=======================
Welcome to django-vidar
=======================

.. |ci| image:: https://github.com/django-vidar/django-vidar/actions/workflows/django.yml/badge.svg
    :target: https://github.com/django-vidar/django-vidar/actions
.. |cov| image:: https://coveralls.io/repos/github/django-vidar/django-vidar/badge.svg?branch=master
    :target: https://coveralls.io/github/django-vidar/django-vidar?branch=master

|ci| |cov|

The purpose? To archive youtube videos from Channels and Playlists based on cron-like scheduling.

Current State? Well, it works with my current django setup.
There is a demo available using the Docker Demo section below.

Requirements
============

You will need to **use django v5.1.0 or greater** as the template files make use of the
`querystring <https://docs.djangoproject.com/en/5.1/ref/templates/builtins/#querystring>`_ templatetag.

Python::

    django>=5.1
    django-bootstrap4
    django-celery-beat
    django-celery-results
    django-environ
    django-mathfilters
    django-positions
    django-mptt
    celery
    redis
    requests
    beautifulsoup4
    yt-dlp
    moviepy
    Pillow>=10.0.0

HTML/JS/CSS::

    htmx
    jquery
    jqueryui
    popper.js

    bootstrap 4
    pickadate.js - https://amsul.ca/pickadate.js/
    font-awesome

Installation
============

Current installation method assumes you already have a django project to add vidar too.

Install django-vidar::

    pip install https://github.com/django-vidar/django-vidar/archive/refs/heads/master.zip

Add the following to your settings INSTALLED_APPS::

    INSTALLED_APPS = [
        ....
        'vidar',
        'django.contrib.humanize',
        'bootstrap4',
        'celery',
        'django_celery_results',
        'django_celery_beat',
        'mathfilters',
        'mptt',
        ...
    ]

Demo
====

In the repo you will find a docker-compose.yml you can test Vidar with.

I primarily work on Windows based machines and the current compose file has worked on Windows 10 and 11
using Docker Desktop.

To run the demo:

1. ``git clone https://github.com/django-vidar/django-vidar.git``
2. The first time you ever run this, you need to run ``docker compose up db redis web`` and wait for the console to show ``web-1 | [2025-03-09 23:59:10 +0000] [1] [INFO] Listening at: http://0.0.0.0:8000 (1)``
3. ``CTRL+C`` to stop the current containers.
4. On the web service change INIT_VIDAR_DATA=True to False.
5. From here on out you can just use ``docker compose up``

You can login at ``http://127.0.0.1:8000`` using username ``vidar`` and password ``vidar``.

Any media downloaded in the demo will be stored within ``./cache/media/`` of the repo directory.

If for some reason you don't want to use the celery images, remove them from docker-compose.yml
and change ``CELERY_TASK_ALWAYS_EAGER=False`` to True. The celery based tasks will run within the
confines of the web request, your page view will stall while things happen.

Celery
======

If you do not already have celery setup, you will also need to follow the
`Celery with Django <https://docs.celeryq.dev/en/latest/django/first-steps-with-django.html>`_  instructions.

django-vidar assigns its tasks to 2 different queues, one named ``queue-vidar`` and ``queue-vidar-processor``

- ``queue-vidar`` is the primary queue. Checking channels, playlists, downloading videos..etc happens here.
- ``queue-vidar-processor`` is the secondary queue where video and audio conversion happens.

I would recommend running ``queue-vidar-processor`` on its own worker and with concurrency of 1 as the
video conversion uses all cores and hammering the CPU can make things take longer.
This is also why the separation of queues exists.
I do not want video conversion interfering with checking of channels for new videos.
See `docker`_ below for example commands.

For simplicity sake I will include the bare minimum changes necessary to make celery work with a django project.
You will need to replace **myproj** with whatever your project is called.

``myproj/__init__.py``::

    from __future__ import absolute_import, unicode_literals

    # This will make sure the app is always imported when
    # Django starts so that shared_task will use this app.
    from .celery import app as celery_app


    __all__ = ["celery_app"]

``myproj/celery.py``::

    from __future__ import absolute_import, unicode_literals

    import os

    from celery import Celery

    # set the default Django settings module for the 'celery' program.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproj.settings")

    app = Celery("myproj")

    # Using a string here means the worker doesn't have to serialize
    # the configuration object to child processes.
    # - namespace='CELERY' means all celery-related configuration keys
    #   should have a `CELERY_` prefix.
    app.config_from_object("django.conf:settings", namespace="CELERY")

    # Load task modules from all registered Django app configs.
    app.autodiscover_tasks()


Docker
======

You will need to run beat and 1 or 2 other workers.

Some helpful commands::

    # Run beat
    celery -A myproj beat --loglevel=INFO
    celery -A myproj worker -Q queue-vidar --loglevel INFO --prefetch-multiplier 1
    celery -A myproj worker -Q queue-vidar-processor --concurrency 1 --loglevel INFO --prefetch-multiplier 1

    # If you want to run both queues on a single worker, just combine -Q like such
    celery -A myproj worker -Q queue-vidar,queue-vidar-processor --loglevel INFO --prefetch-multiplier 1


Jellyfin
========

I use Jellyfin with a `plugin called YouTubeMetadata <https://github.com/ankenyr/jellyfin-youtube-metadata-plugin>`_

The following configurations and their default values are required for the plugin to work.

- VIDAR_CHANNEL_DIRECTORY_SCHEMA
- VIDAR_SAVE_INFO_JSON_FILE
- VIDAR_VIDEO_DIRECTORY_SCHEMA
- VIDAR_VIDEO_FILENAME_SCHEMA

redis messaging
===============

As Vidar tasks are processing various things they can send messages to the frontend indicating what is happening.

Things like a channel or a playlist being indexed, video downloading and conversion statuses.

Vidar makes use of redis for this functionality, you can enable this on your project by adding the following to
your project settings::

    TEMPLATES = [
        {
            ...
            "OPTIONS": {
                "context_processors": [
                    ...
                    'vidar.template_contexts.add_redis_messages',
                    ...
                ],
            },
        },
    ]

and within one of your template files add the following::

    {% include 'vidar/messages-redis.html' %}

Configurable Settings
=====================


``VIDAR_AUTOMATED_DOWNLOADS_DAILY_LIMIT`` (default: ``400``)

``VIDAR_AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT`` (default: ``90 * 60``)
    If a video duration (in seconds) is longer than this value,
    the ``VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT`` will be halved.

``VIDAR_AUTOMATED_DOWNLOADS_PER_TASK_LIMIT`` (default: ``4``)
    Maximum number of videos permitted to download per run of automated_archiver.

``VIDAR_AUTOMATED_QUALITY_UPGRADES_PER_TASK_LIMIT`` (default: ``4``)

``VIDAR_AUTOMATED_CRONTAB_CATCHUP`` (default: ``True``)
    When ``trigger_crontab_scans`` runs should it try to automatically find channels and
    playlists that failed to run earlier?

``VIDAR_CHANNEL_BANNER_RATE_LIMIT`` (default: ``30``)
    How many seconds between channel thumbnail updates?

    Once a month a task will run to update channel banners, thumbnails, ...etc

``VIDAR_CHANNEL_DIRECTORY_SCHEMA`` (default: ``"{{ channel.system_safe_name }}"``)
    When saving files, use this to name the directory for this channel.

``VIDAR_CHANNEL_BLOCK_RESCAN_WINDOW_HOURS`` (default: ``2``)
    If a channel is scanned and then the automated system tries to scan again within this window,
    the channel is skipped.

``VIDAR_COMMENTS_MAX_PARENTS`` (default: ``"all"``)

``VIDAR_COMMENTS_MAX_REPLIES`` (default: ``100``)

``VIDAR_COMMENTS_MAX_REPLIES_PER_THREAD`` (default: ``10``)

``VIDAR_COMMENTS_SORTING`` (default: ``"top"``)

``VIDAR_COMMENTS_TOTAL_MAX_COMMENTS`` (default: ``100``)

``VIDAR_CRON_DEFAULT_SELECTION`` (default: ``"6-22/4 * * *|7-21/4 * * *"``)
    **Hourly based scans are not advised**, use daily, weekly, monthly, bi-yearly, or year.

    If you want to use hourly, these are the base selection to choose from WITHOUT the minutes.
    Minutes are calculated on the fly and should not be supplied here.

    So instead of ``m h dom mon dow` you need to supply ``h dom mon dow`.

    You can supply multiple values by pipe ``|`` separation.

    The default supplied above would alternate even and odd hours. Some would be assigned to run at
    ``6,8,10,12,14,16,18,20,22`` and the others at ``7,9,11,13,15,17,19,21``

``VIDAR_CRONTAB_CHECK_INTERVAL`` (default: ``10``)
    vidar's version of cron is based on the cron set for vidar.tasks.trigger_crontab_scans.

    If ``trigger_crontab_scans`` is set to check every 10 minutes, set this value to 10.

    If ``trigger_crontab_scans`` is set to check every 5 minute, set this value to 5.

``VIDAR_CRONTAB_CHECK_INTERVAL_MAX_IN_DAYS`` (default: ``3``)
    If the system went down for a day, there is a utility named catchup. If you use catchup, how many days
    prior to right now do you want to check for channels and playlists that should have been scanned.

    So for instance channel Y is set to scan once a month on the 14th but my server went down on the 13th and
    today is the 15th. When everything starts up, channel Y will still have been missed.
    You can then run a manual catchup from the 13th to now and every channel and playlist that should've been
    scanned, will be scanned.

``VIDAR_DELETE_DOWNLOAD_CACHE`` (default: ``True``)
    When finished downloading, delete cached files?

    Files are downloaded to MEDIA_CACHE and then copied or hardlinked to MEDIA_ROOT, delete the cache copy?

``VIDAR_DEFAULT_QUALITY`` (default: ``1080``)
    Used during the creation of channels and playlists as a default option.
    Also becomes the default on the manual video download form.

``VIDAR_DOWNLOAD_SPEED_RATE_LIMIT`` (default: ``5000``)
    See `yt-dlp Download Option <https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#download-options>`_ ``--limit-rate``

``VIDAR_GOTIFY_PRIORITY`` (default: ``5``)
    Gotify message with priority >= 5

        Android push notification
        For information I need to know instantly

    Gotify message with priority < 5

        I see notification on PC, if I happen to be on computer
        I see notification, if I manually open gotify on Android
        For "nice to know" information

``VIDAR_GOTIFY_TITLE_PREFIX`` (default: ``""``)
    If you want the notification titles to be prepended with something like "Vidar: Video downloaded ..."
    You would then supply ``VIDAR_GOTIFY_TITLE_PREFIX = "Vidar: "``

``VIDAR_GOTIFY_TOKEN`` (default: ``None``)

``VIDAR_GOTIFY_URL`` (default: ``None``)

``VIDAR_GOTIFY_URL_VERIFY`` (default: ``True``)

``VIDAR_LOAD_SPONSORBLOCK_DATA_ON_DOWNLOAD`` (default: ``True``)

``VIDAR_LOAD_SPONSORBLOCK_DATA_ON_UPDATE_VIDEO_DETAILS`` (default: ``True``)
    When checking video status, should it also check sponsorblock for updates?

``VIDAR_MEDIA_CACHE`` (default: ``""``)
    Temporary directory to use when downloading videos before conversion and saving to MEDIA_ROOT.

``VIDAR_MEDIA_HARDLINK`` (default: ``False``)

``VIDAR_MEDIA_ROOT`` (default: ``settings.MEDIA_ROOT``)

``VIDAR_MEDIA_URL`` (default: ``settings.MEDIA_URL``)

``VIDAR_MONTHLY_CHANNEL_UPDATE_BANNERS`` (default: ``True``)

``VIDAR_MONTHLY_CHANNEL_CRONTAB_BALANCING`` (default: ``False``)

``VIDAR_MONTHLY_VIDEO_CONFIRM_FILENAMES_ARE_CORRECT`` (default: ``True``)

``VIDAR_NOTIFICATIONS_CHANNEL_STATUS_CHANGED`` (default: ``True``)

``VIDAR_NOTIFICATIONS_CONVERT_TO_MP4_COMPLETED`` (default: ``True``)

``VIDAR_NOTIFICATIONS_SEND`` (default: ``True``)

``VIDAR_NOTIFICATIONS_VIDEO_DOWNLOADED`` (default: ``True``)

``VIDAR_NOTIFICATIONS_FULL_ARCHIVING_COMPLETED`` (default: ``True``)

``VIDAR_NOTIFICATIONS_FULL_ARCHIVING_STARTED`` (default: ``True``)

``VIDAR_NOTIFICATIONS_FULL_INDEXING_COMPLETE`` (default: ``True``)

``VIDAR_NOTIFICATIONS_NO_VIDEOS_ARCHIVED_TODAY`` (default: ``True``)

``VIDAR_NOTIFICATIONS_PLAYLIST_ADDED_BY_MIRROR`` (default: ``True``)

``VIDAR_NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_ERRORS`` (default: ``True``)

``VIDAR_NOTIFICATIONS_PLAYLIST_DISABLED_DUE_TO_STRING`` (default: ``True``)

``VIDAR_NOTIFICATIONS_VIDEO_ADDED_TO_PLAYLIST`` (default: ``True``)

``VIDAR_NOTIFICATIONS_VIDEO_READDED_TO_PLAYLIST`` (default: ``True``)

``VIDAR_NOTIFICATIONS_VIDEO_REMOVED_FROM_PLAYLIST`` (default: ``True``)

``VIDAR_PLAYLIST_BLOCK_RESCAN_WINDOW_HOURS`` (default: ``2``)
    If a playlist is scanned and then the automated system tries to scan again within this window,
    the playlist is skipped.

``VIDAR_PRIVACY_STATUS_CHECK_HOURS_PER_DAY`` (default: ``16``)
    How many hours per day does the update_video_statuses_and_details task run for?

``VIDAR_PRIVACY_STATUS_CHECK_MAX_CHECK_PER_VIDEO`` (default: ``3``)
    How many times should an update_video_details be used on a video, automatically.

``VIDAR_PRIVACY_STATUS_CHECK_MIN_AGE`` (default: ``30``)
    How many days before a video status should be checked.

``VIDAR_PRIVACY_STATUS_CHECK_FORCE_CHECK_PER_CALL`` (default: ``0``)
    How many videos to check per-call of the ``update_video_details`` task. The task by default calculates
    the number of videos to scan that day based on the number of pending videos divided by the range of check

``VIDAR_PROXIES`` (default: ``[]``)
    A list of proxies to select from.

    Supply a callable function and it will be called with the previous proxies,
    the current video being attempted, and the number of attempt the system is on.
    The callable must return a string containing the connection string for a ``proxy`` to use,
    or return None to not use a proxy.::

        def my_custom_vidar_get_proxy(previous_proxies=None, instance=None, attempt=None):
            ...

        VIDAR_PROXIES = my_custom_vidar_get_proxy

``VIDAR_PROXIES_DEFAULT`` (default: ``""``)
    If you use a proxy for yt-dlp, this is the base proxy value to supply in the event all other VIDAR_PROXIES fail

``VIDAR_REDIS_ENABLED`` (default: ``True``)
    If False vidar will not send any messages to redis.

``VIDAR_REDIS_URL`` (default: ``None``)
    URL to connect to redis, will use settings.CELERY_BROKER_URL if it exists

``VIDAR_REDIS_CHANNEL_INDEXING`` (default: ``True``)
    Update redis messaging when a Channel is being indexed

``VIDAR_REDIS_PLAYLIST_INDEXING`` (default: ``True``)
    Update redis messaging when a Playlist is being indexed

``VIDAR_REDIS_VIDEO_DOWNLOADING`` (default: ``True``)
    Vidar uses yt-dlp progress hook to send update messages to redis that can be used in django templates
    for messages to the user about the download state.

``VIDAR_REDIS_VIDEO_CONVERSION_FINISHED`` (default: ``True``)

``VIDAR_REDIS_VIDEO_CONVERSION_STARTED`` (default: ``True``)

``VIDAR_SAVE_INFO_JSON_FILE`` (default: ``True``)
    Write info.json file alongside video file?

``VIDAR_SHORTS_FORCE_MAX_QUALITY`` (default: ``True``)
    When downloading shorts, grab max quality available?

``VIDAR_SLOW_FULL_ARCHIVE_TASK_DOWNLOAD_LIMIT`` (default: ``1``)
    How many videos to download per task run.

``VIDAR_VIDEO_AUTO_DOWNLOAD_LIVE_AMQ_WHEN_DETECTED`` (default: ``False``)
    When ``update_video_details`` task is called, a video's live quality may have been
    updated since it was last downloaded. Maybe the download task grabbed 480p while youtube
    was still processing 1080p. If a channel is set to download the best quality available,
    this will track if a videos quality has been upgraded since the video was last downloaded.
    If so, redownload it at max quality.

``VIDAR_VIDEO_DOWNLOAD_ERROR_ATTEMPTS`` (default: ``70``)
    How many times to try downloading a video, divide this by VIDAR_VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS
    to see how many days it takes to fully error and stop trying. Default is 14 days worth.

``VIDAR_VIDEO_DOWNLOAD_ERROR_DAILY_ATTEMPTS`` (default: ``5``)

``VIDAR_VIDEO_DOWNLOAD_ERROR_WAIT_PERIOD`` (default: ``60``)
    How many minutes to wait between error attempts

``VIDAR_VIDEO_DOWNLOAD_FORMAT``
    default: ``"best[height<={quality}]"``

``VIDAR_VIDEO_DOWNLOAD_FORMAT_BEST``
    default: ``"bestvideo[ext=mp4]+bestaudio[ext=mp4]"``

``VIDAR_VIDEO_DIRECTORY_SCHEMA``
    default: ``"{{ video.upload_date|date:"Y-m-d" }} - {{ video.system_safe_title }} [{{ video.provider_object_id }}]"``

``VIDAR_VIDEO_FILENAME_SCHEMA``
    default: ``"{{ video.upload_date|date:"Y-m-d" }} - {{ video.system_safe_title }} [{{ video.provider_object_id }}]"``

``VIDAR_VIDEO_LIVE_DOWNLOAD_RETRY_HOURS`` (default: ``6``)
    How many hours to wait before checking if a Live (premiering) video can be downloaded.

``VIDAR_YTDLP_INITIALIZER`` (default: ``None``)
    Lets you handle the creation of the yt_dlp.YoutubeDL instance.

    If you plan to use a proxy, you will need to assign it yourself.
    ::

        def my_ytdlp_instance(kwargs):
            kwargs["proxy"] = "..."
            kwargs["cookiefile"] = "/home/user/cookies.txt"
            return yt_dlp.YoutubeDL(kwargs)

        VIDAR_YOUTUBEDL_INITIALIZER = my_ytdlp_instance

        # or put it in a file such as myproj/ytdlp.py and then

        VIDAR_YOUTUBEDL_INITIALIZER = 'myproj.ytdlp.my_ytdlp_instance'
