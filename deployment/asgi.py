"""ASGI entry point for the hardened university deployment.

The semaphore keeps Django request concurrency below PostgreSQL's connection
budget.  Excess HTTP requests wait here instead of all reaching the database
at once and being rejected with "too many clients already".
"""

import asyncio
import os

from django.core.asgi import get_asgi_application


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'deployment.settings')


def _http_concurrency_limit():
    raw_value = os.environ.get('MIYP_HTTP_CONCURRENCY_LIMIT', '75')
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError('MIYP_HTTP_CONCURRENCY_LIMIT must be an integer') from error
    if value < 1:
        raise RuntimeError('MIYP_HTTP_CONCURRENCY_LIMIT must be at least 1')
    return value


django_application = get_asgi_application()
http_slots = asyncio.Semaphore(_http_concurrency_limit())


async def application(scope, receive, send):
    if scope['type'] != 'http':
        return await django_application(scope, receive, send)

    async with http_slots:
        return await django_application(scope, receive, send)
