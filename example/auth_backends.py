from django.contrib.auth.models import Group



class AnonymousPermissions(object):
    def authenticate(self, **kwargs):
        return

    @staticmethod
    def get_anonymous_permissions():
        group, group_created = Group.objects.get_or_create(name="Anonymous Users")
        perms = group.permissions.all()
        perms = perms.values_list("content_type__app_label", "codename").order_by()
        perms = set("%s.%s" % (ct, name) for ct, name in perms)
        return perms

    def get_group_permissions(self, user_obj, obj=None):
        if user_obj.is_anonymous:
            perm_cache_name = "_anonymous_perm_cache"
            if not hasattr(user_obj, perm_cache_name):
                setattr(user_obj, perm_cache_name, self.get_anonymous_permissions())
            return getattr(user_obj, perm_cache_name)
        return set()

    def get_all_permissions(self, user_obj, obj=None):
        return self.get_group_permissions(user_obj, obj)

    def has_perm(self, user_obj, perm, obj=None):
        return perm in self.get_group_permissions(user_obj, obj)
