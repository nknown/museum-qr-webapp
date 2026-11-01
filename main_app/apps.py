from django.apps import AppConfig
from django.db.models.signals import post_migrate


def provision_roles(sender, **kwargs):
    from main_app.models import UserProfile
    from main_app.role_permissions import sync_user_access
    for profile in UserProfile.objects.select_related('user'):
        sync_user_access(profile)


class FreeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'main_app'

    def ready(self):
        post_migrate.connect(provision_roles, sender=self, dispatch_uid='main_app.provision_roles')
