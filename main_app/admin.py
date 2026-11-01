from django.contrib import admin
from leaflet.admin import LeafletGeoAdmin


from django.forms import ModelForm
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TabbedTranslationAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
#from django_summernote.admin import SummernoteModelAdmin  # not used any more
from semantic_admin import SemanticModelAdmin, SemanticStackedInline, SemanticTabularInline

from main_app.models import *

# unregister models that should not appear in the main_app admin
for m in (Execution, Thing, SpatialThing):
    try:
        admin.site.unregister(m)
    except admin.sites.NotRegistered:
        pass

# unregister summernote attachment to keep admin minimal
try:
    from django_summernote.models import Attachment
    admin.site.unregister(Attachment)
except Exception:
    pass

admin.site.site_title = _('Main Administration')
admin.site.site_header = _('Main Administration')
admin.site.index_title = _('Main Administration')

# things, spatialthings and executions have been unregistered above
# (they are intentionally omitted per the teacher's request)






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


from django.contrib import admin
from .models import Exposition, Piece, Slide

class SlideInline(admin.TabularInline):
    model = Slide
    extra = 1

@admin.register(Piece)
class PieceAdmin(admin.ModelAdmin):
    list_display = ("title", "qr_slug", "created_at")
    search_fields = ("title", "qr_slug")
    inlines = [SlideInline]

@admin.register(Exposition)
class ExpositionAdmin(admin.ModelAdmin):
    list_display = ("title", "created_at")
    search_fields = ("title",)
    filter_horizontal = ("admins", "pieces")