"""
URL configuration for example project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path("tests/", include("exampleapp.urls")),
    path('', include('vidar.urls')),
]

if settings.DEBUG:
    media_url = getattr(settings, 'MEDIA_URL', '')
    if not media_url:
        media_url = getattr(settings, 'VIDAR_MEDIA_URL', '')

    if media_url.startswith('/'):
        media_url = media_url[1:]

    media_root = getattr(settings, 'MEDIA_ROOT', None)
    if not media_root and media_url:
        media_root = getattr(settings, 'VIDAR_MEDIA_ROOT', None)

    if media_root:
        urlpatterns.extend([
            re_path(r"^{}(?P<path>.*)$".format(media_url), serve, {"document_root": media_root}),
        ])
