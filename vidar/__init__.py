default_app_config = "vidar.apps.VidarConfig"

VERSION = (2025, 3, 15, "alpha", 0)

__title__ = "django-vidar"
__version_info__ = VERSION
__version__ = ".".join(map(str, VERSION[:3])) + (
    "-{}{}".format(VERSION[3], VERSION[4] or "") if VERSION[3] != "final" else ""
)
