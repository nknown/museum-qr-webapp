"""Readiness checks for the hardened deployment profile."""
import logging
from django.db import connection
from django.http import JsonResponse
from django.urls import path
from global_files.urls import urlpatterns as application_urls


def readiness(request):
    try:
        with connection.cursor() as cursor:
            # Query application tables: a bare SELECT 1 would pass before migration.
            cursor.execute('SELECT 1 FROM django_migrations LIMIT 1')
            cursor.execute('SELECT 1 FROM main_app_presentationsession LIMIT 1')
        response = JsonResponse({'status': 'ok'})
    except Exception:
        logging.getLogger(__name__).exception('Readiness database check failed')
        response = JsonResponse({'status': 'unavailable'}, status=503)
    response['Cache-Control'] = 'no-store'
    return response


urlpatterns = [path('health/ready/', readiness), *application_urls]
