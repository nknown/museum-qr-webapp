from django.contrib import admin
from leaflet.admin import LeafletGeoAdmin


from django.forms import ModelForm
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TabbedTranslationAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django_summernote.admin import SummernoteModelAdmin
from semantic_admin import SemanticModelAdmin, SemanticStackedInline, SemanticTabularInline

from main_app.models import *

admin.site.site_title = _('Main Administration')
admin.site.site_header = _('Main Administration')
admin.site.index_title = _('Main Administration')

class ThingAdmin(SemanticModelAdmin):
    list_display = ['id', 'name', 'user', 'created_at', 'client_country']
    list_filter = ['user']
admin.site.register(Thing, ThingAdmin)


class SpatialThingAdmin(LeafletGeoAdmin):
    list_display = ['id', 'name', 'user', 'created_at', 'points', 'limits']
    list_filter = ['user']

admin.site.register(SpatialThing, SpatialThingAdmin)


class ExecutionAdmin(SemanticModelAdmin):
    list_display = ['user', '__str__', 'created_at',  'start', 'end', 'client_country']
    list_filter = ['user']
admin.site.register(Execution, ExecutionAdmin)






class UserProfileInline(SemanticStackedInline):
    model=UserProfile
    can_delete=False

class UserAdmin(BaseUserAdmin):
    def get_form(self, request, obj=None, **kwargs):
        if obj:
            self.inlines = (UserProfileInline,)
        else:
            self.inlines = ()
        return super().get_form(request, obj, **kwargs)

admin.site.unregister(User)
admin.site.register(User, UserAdmin)


