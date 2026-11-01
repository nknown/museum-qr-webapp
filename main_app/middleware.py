from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.utils import translation
from urllib.parse import urlsplit

from main_app.access import can_curate, is_administrator


def _is_user_device_path(path):
    """Return whether a path belongs to the visitor-facing User Device flow."""
    normalized = (path or '/').split('?', 1)[0]
    if normalized.startswith(('/presentation/exhibition/', '/presentation/piece/')):
        return True
    if normalized.startswith(('/presentation-access/', '/presentation-favorites')):
        return True
    if normalized.rstrip('/') == '/visit/history':
        return True

    parts = [part for part in normalized.strip('/').split('/') if part]
    return (
        len(parts) == 4
        and parts[0] in {'exhibition', 'piece'}
        and parts[1].isdigit()
        and parts[2] == 'presentation'
        and parts[3] == 'user_device'
    )


class UserDeviceEnglishMiddleware:
    """Keep visitor-facing User Device UI in one deterministic language."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_device_request = _is_user_device_path(request.path_info)

        # The login view is shared with the rest of the application. Force it
        # to English only when it was entered from the User Device flow.
        if request.path_info.rstrip('/') == '/login':
            destination = request.GET.get('next') or request.POST.get('next')
            user_device_request = _is_user_device_path(urlsplit(destination or '').path)

        if not user_device_request:
            return self.get_response(request)

        language_code = getattr(settings, 'USER_DEVICE_LANGUAGE_CODE', 'en')
        request.LANGUAGE_CODE = language_code
        with translation.override(language_code):
            response = self.get_response(request)
        response.headers['Content-Language'] = language_code
        return response


class RoleInterfaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/cms/') and request.user.is_authenticated:
            if not can_curate(request.user):
                raise PermissionDenied
            if not is_administrator(request.user) and not request.user.profile.museum_id:
                raise PermissionDenied('Ask an administrator to assign your museum.')
        return self.get_response(request)
