"""
Django settings for example project.

Generated by 'django-admin startproject' using Django 4.2.6.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""
import pathlib
import sys

from django.utils import timezone
from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    # set casting, default value
    DEBUG=(bool, True)
)
environ.Env.read_env(BASE_DIR / ".env")

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

SECRET_KEY = env.str(
    "DJANGO_SECRET_KEY", "super-secret-value-pst-dont-use-in-prod"
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env.str(
    "DJANGO_ALLOWED_HOSTS", ""
).split(" ")

LOGIN_URL = '/admin/login/?next=/'


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "django.contrib.humanize",
    'celery',
    'django_celery_results',
    'django_celery_beat',
    'bootstrap4',
    'mathfilters',
    'mptt',
    'vidar',
    'exampleapp',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'example.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'example.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    "default": env.db(default=f"sqlite:///{BASE_DIR}/db.sqlite3"),
}

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "example.auth_backends.AnonymousPermissions",
)

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = env.str('DJANGO_TIME_ZONE', 'UTC')

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = "exampleapp.User"

from django.contrib.auth.hashers import PBKDF2PasswordHasher

class MyPBKDF2PasswordHasher(PBKDF2PasswordHasher):
    """
    A subclass of PBKDF2PasswordHasher that uses 1 iteration.

    This is for test purposes only. Never use anywhere else.
    """

    iterations = 1


PASSWORD_HASHERS = [
    "example.settings.MyPBKDF2PasswordHasher",
]

CELERY_BEAT_MAX_LOOP_INTERVAL = env.int('CELERY_BEAT_MAX_LOOP_INTERVAL', 10)
CELERY_BEAT_SCHEDULER = env.str('CELERY_BEAT_SCHEDULER', "django_celery_beat.schedulers:DatabaseScheduler")

CELERY_BROKER_URL = env.str('CELERY_BROKER_URL', "")
if not CELERY_BROKER_URL:
    CELERY_BROKER_TYPE = env.str('CELERY_BROKER_TYPE', 'redis')
    CELERY_BROKER_HOSTNAME = env.str("CELERY_BROKER_HOSTNAME", '')
    CELERY_BROKER_PORT = env.int("CELERY_BROKER_PORT", 6379)
    CELERY_BROKER_DB = env.int("CELERY_BROKER_DB", 0)
    CELERY_BROKER_URL = f"{CELERY_BROKER_TYPE}://{CELERY_BROKER_HOSTNAME}:{CELERY_BROKER_PORT}/{CELERY_BROKER_DB}"

if CELERY_VISIBILITY_TIMEOUT := env.int('CELERY_VISIBILITY_TIMEOUT', 2 * 60 * 60):
    CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": CELERY_VISIBILITY_TIMEOUT}
CELERY_ENABLE_UTC = env.bool('CELERY_ENABLE_UTC', True)
CELERY_RESULT_BACKEND = env.str('CELERY_RESULT_BACKEND', "django-db")
CELERY_RESULT_EXTENDED = env.bool('CELERY_RESULT_EXTENDED', True)
CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', False)
CELERY_TASK_DEFAULT_QUEUE = env.str('CELERY_TASK_DEFAULT_QUEUE', "queue-vidar")
CELERY_TIMEZONE = env.str('CELERY_TIMEZONE', TIME_ZONE)
CELERY_TRACK_STARTED = env.bool('CELERY_TRACK_STARTED', True)
CELERY_TASK_TRACK_STARTED = env.bool('CELERY_TASK_TRACK_STARTED', True)
CELERY_WORKER_PREFETCH_MULTIPLIER = env.int('CELERY_WORKER_PREFETCH_MULTIPLIER', 1)

MEDIA_ROOT = env.str('DJANGO_MEDIA_ROOT', '/media/')
MEDIA_URL = env.str('DJANGO_MEDIA_URL', '/media/')

VIDAR_REDIS_URL = env.str('VIDAR_REDIS_URL', CELERY_BROKER_URL)
VIDAR_MEDIA_ROOT = env.str('VIDAR_MEDIA_ROOT', MEDIA_ROOT)
VIDAR_MEDIA_URL = env.str('VIDAR_MEDIA_URL', MEDIA_URL)
VIDAR_MEDIA_CACHE = pathlib.Path(env.str('VIDAR_MEDIA_CACHE', "cache/"))

GITHUB_WORKFLOW = env.str("GITHUB_WORKFLOW", default=None)
if GITHUB_WORKFLOW:  # pragma: no cover
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "github_actions",
            "USER": "postgres",
            "PASSWORD": "postgres",
            "HOST": "127.0.0.1",
            "PORT": "5432",
        }
    }

    CELERY_BROKER_URL = "redis://127.0.0.1:6379/0"
    VIDAR_REDIS_URL = CELERY_BROKER_URL

    VIDAR_MEDIA_STORAGE_CLASS = "vidar.storages.TestFileSystemStorage"


def my_ytdlp_initializer(action, instance=None, **kwargs):
    if action == "testing":
        return "Successfully called example.settings.my_ytdlp_initializer"
    import yt_dlp
    return yt_dlp.YoutubeDL(kwargs)

VIDAR_YTDLP_INITIALIZER = my_ytdlp_initializer

IS_TESTING = env.bool("IS_TESTING", "test" in sys.argv)
