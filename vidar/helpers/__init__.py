import io
import logging

from django.http import HttpResponseRedirect
from django.shortcuts import redirect


log = logging.getLogger(__name__)


def convert_to_next_day_of_week(day_of_week):
    return (day_of_week + 1) % 7


def unauthenticated_allow_view_video(request, video_id):
    if "vidar_video_view_permitted" not in request.session:
        request.session["vidar_video_view_permitted"] = []
    request.session["vidar_video_view_permitted"].append(video_id)
    request.session.modified = True


def unauthenticated_check_if_can_view_video(request, video_id):
    pids = unauthenticated_permitted_videos(request=request)
    return video_id in pids


def unauthenticated_permitted_videos(request):
    if "vidar_video_view_permitted" in request.session:
        return request.session["vidar_video_view_permitted"]
    return []


def redirect_next_or_obj(request, other, *args, **kwargs):
    next_param = getattr(request, "GET", {}).get("next")
    if next_param:
        return HttpResponseRedirect(next_param)
    return redirect(other, *args, **kwargs)


def json_safe_kwargs(kwargs):
    # auto convert datetime into isoformat
    output = {}
    for k, v in kwargs.items():
        if hasattr(v, "isoformat"):
            output[k] = v.isoformat()
        elif isinstance(v, io.IOBase):
            v.seek(0)
            output[k] = v.read()
        elif k != "progress_hooks":
            output[k] = v

    return output
