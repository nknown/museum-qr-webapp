"""Fail-closed settings for a university-hosted MIYP deployment."""
from global_files.settings import *  # noqa: F403
from django.core.exceptions import ImproperlyConfigured

if DEBUG or not env.bool('MAIN_APP_PRODUCTION'):
    raise ImproperlyConfigured('Deployment requires MAIN_APP_PRODUCTION=on')
if not ALLOWED_HOSTS or any('*' in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured('Deployment requires explicit allowed hosts')
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('Deployment requires a strong, deployment-specific secret')
if DB_TYPE != 'postgres':
    raise ImproperlyConfigured('Deployment requires PostgreSQL')
if not env.bool('MAIN_APP_REVERSE_PROXY'):
    raise ImproperlyConfigured('Deployment requires the trusted HTTPS gateway')
if GOOGLE_OAUTH_USE_LOOPBACK_REDIRECT:
    raise ImproperlyConfigured('The localhost OAuth bridge is development-only')

ASGI_APPLICATION = 'deployment.asgi.application'
ROOT_URLCONF = 'deployment.urls'
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    *[m for m in MIDDLEWARE if m not in {
        'django.middleware.security.SecurityMiddleware',
        'whitenoise.middleware.WhiteNoiseMiddleware',
        'global_files.middleware.GoogleOAuthLoopbackRedirectMiddleware',
    }],
]
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = 'Lax'
# Embedded previews in the CMS require same-origin framing.
X_FRAME_OPTIONS = 'SAMEORIGIN'
SOCIAL_AUTH_REDIRECT_IS_HTTPS = True
STATIC_ROOT = '/app/static'
MEDIA_ROOT = '/app/main_app/media'
# Keep protected document downloads behind Wagtail's permission checks.
WAGTAILDOCS_SERVE_METHOD = 'serve_view'
# Django recommends disabling persistent connections under ASGI.
# This overrides any value retained in an older private environment file.
DATABASES['default']['CONN_MAX_AGE'] = 0
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
DATABASES['default']['OPTIONS'] = {'connect_timeout': 5}
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}
