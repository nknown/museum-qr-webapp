from django.apps import AppConfig


class FreeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'main_app'

    def ready(self):
        # unregister models that may have been added later (e.g. by third-party apps)
        from django.contrib import admin
        from django_summernote.models import Attachment
        try:
            admin.site.unregister(Attachment)
        except admin.sites.NotRegistered:
            pass
