from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.http import HttpResponseRedirect


class GoogleOAuthLoopbackRedirectMiddleware:
    """Use localhost for Google OAuth without moving the normal site host."""

    begin_path = '/login/google-oauth2/'
    complete_path = '/complete/google-oauth2/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.GOOGLE_OAUTH_USE_LOOPBACK_REDIRECT:
            return self.get_response(request)

        if request.path not in {self.begin_path, self.complete_path}:
            return self.get_response(request)

        incoming_host = (
            request.META.get('HTTP_X_FORWARDED_HOST')
            or request.META.get('HTTP_HOST', '')
        )
        incoming_hostname = urlsplit(f'//{incoming_host}').hostname
        loopback_hostname = urlsplit(
            f'//{settings.GOOGLE_OAUTH_LOOPBACK_HOST}'
        ).hostname

        # The browser cannot send its i7h8 session cookie to localhost. Send
        # Google's response back to the public host before Django consumes it.
        if request.path == self.complete_path and incoming_hostname == loopback_hostname:
            public_base = urlsplit(settings.SERVER_NAME)
            return HttpResponseRedirect(urlunsplit((
                public_base.scheme,
                public_base.netloc,
                request.path,
                request.META.get('QUERY_STRING', ''),
                '',
            )))

        # Python Social Auth builds redirect_uri from the request host during
        # both authorization and token exchange, so keep both stages identical.
        request.META['HTTP_HOST'] = settings.GOOGLE_OAUTH_LOOPBACK_HOST
        request.META['HTTP_X_FORWARDED_HOST'] = settings.GOOGLE_OAUTH_LOOPBACK_HOST
        request.META['HTTP_X_FORWARDED_PROTO'] = 'https'
        request.META['HTTP_X_FORWARDED_PORT'] = '8000'
        return self.get_response(request)
