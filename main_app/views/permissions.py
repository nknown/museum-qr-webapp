from rest_framework import permissions
from main_app.models import Execution
from django.utils import timezone

import environ
env = environ.Env()
environ.Env.read_env()
from django.core.cache import cache

class ApparatusOnlyAccess(permissions.BasePermission):
    message = 'Please provide a valid secret in the Authentication HTTP header.'

    def has_object_permission(self, request, view, obj):
        if 'Authentication' in request.headers:
            if isinstance(obj, Execution):
                if request.headers['Authentication'] == obj.apparatus.secret:
                    if env.bool('CACHE'):
                        cache.set('apparatus_status_'+str(obj.apparatus.id), 'hello, world!', obj.apparatus.timeout)
                    else:
                        obj.apparatus.last_online = timezone.now()
                        obj.apparatus.save()
                    return True
            if isinstance(obj, Result):
                if request.headers['Authentication'] == obj.execution.apparatus.secret:
                    if env.bool('CACHE'):
                        cache.set('apparatus_status_'+str(obj.execution.apparatus.id), 'hello, world!', obj.execution.apparatus.timeout)
                    else:
                        obj.execution.apparatus.last_online = timezone.now()
                        obj.execution.apparatus.save()
                    return True
            if isinstance(obj, Apparatus):
                if request.headers['Authentication'] == obj.secret:
                    if env.bool('CACHE'):
                        cache.set('apparatus_status_'+str(obj.id), 'hello, world!', obj.timeout)
                    else:
                        obj.last_online = timezone.now()
                        obj.save()
                    return True
                    
        return False
        