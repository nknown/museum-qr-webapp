from django.conf import settings

def site_info(request):
    return {
        'project_name': settings.PROJECT_NAME,
        'project_acronymum': settings.PROJECT_ACRONYMUM,
        'site_name': settings.SITE_NAME
    }

