from django.conf import settings

from main_app.access import is_administrator, can_curate, all_visitor_content

def site_info(request):
    return {
        'is_platform_admin': is_administrator(request.user),
        'can_curate': can_curate(request.user),
        'all_visitor_content': all_visitor_content(request.user),
        'project_name': settings.PROJECT_NAME,
        'project_acronymum': settings.PROJECT_ACRONYMUM,
        'site_name': settings.SITE_NAME,
        'auth_notyf': request.session.pop('auth_notyf', None),
    }
