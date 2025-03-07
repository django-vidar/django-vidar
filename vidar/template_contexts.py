from vidar.services.redis_services import RedisMessaging


def add_redis_messages(request=None):
    redis_messages = None
    if request:
        if mapp := request.GET.get("messages_app"):
            app_name = mapp
        else:
            try:
                app_name = request.resolver_match.app_name
            except (ValueError, TypeError, AttributeError):
                app_name = None

        if app_name != "core_data":
            redis_messages = RedisMessaging().get_app_messages(app=app_name)

    if redis_messages is None:
        redis_messages = RedisMessaging().get_all_messages()

    return {
        "vidar_redis_messages": redis_messages,
    }
