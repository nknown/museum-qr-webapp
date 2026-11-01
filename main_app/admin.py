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
from main_app.admin_forms import AdminUserCreationForm, UserProfileAdminForm
from main_app.access import is_administrator

from django.contrib.sessions.models import Session



admin.site.site_title = 'MIYP'
admin.site.site_header = 'MIYP'
admin.site.index_title = 'MIYP'
admin.site.has_permission = lambda request: is_administrator(request.user)


class ThingAdmin(SemanticModelAdmin):
    list_display = ['id', 'name', 'user', 'created_at', 'client_country']
    list_filter = ['user']
admin.site.register(Thing, ThingAdmin)


class MuseumAdmin(SemanticModelAdmin):
    model = Museum
    menu_label = 'Museums'
    list_display = ['id', 'title', 'description']
    exclude = ['admins']

admin.site.register(Museum, MuseumAdmin)


class ExhibitionAdmin(SemanticModelAdmin):
    model = Exhibition
    menu_label = 'Exhibitions'  # ditch this to use verbose_name_plural from model
    list_display = ['id', 'title', 'museum', 'description']

admin.site.register(Exhibition, ExhibitionAdmin)



class PieceAdmin(SemanticModelAdmin):
    model = Piece
    list_display = ['id', 'exhibition', 'date_created']
admin.site.register(Piece, PieceAdmin)








class ExecutionAdmin(SemanticModelAdmin):
    list_display = ['user', '__str__', 'created_at',  'start', 'end', 'client_country']
    list_filter = ['user']
admin.site.register(Execution, ExecutionAdmin)






class UserProfileInline(SemanticStackedInline):
    form = UserProfileAdminForm
    model=UserProfile
    can_delete=False

class UserAdmin(BaseUserAdmin):
    readonly_fields = ('is_staff', 'is_superuser', 'groups', 'user_permissions')
    add_form = AdminUserCreationForm
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'account_type',
                'username',
                'google_email',
                'password1',
                'password2',
                'profile_type',
                'museum',
            ),
        }),
    )

    def get_inlines(self, request, obj):
        return (UserProfileInline,) if obj else ()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and isinstance(form, AdminUserCreationForm):
            obj.profile.type = form.cleaned_data['profile_type']
            obj.profile.museum = form.cleaned_data.get('museum') if obj.profile.type == 'c' else None
            obj.profile.save()

admin.site.unregister(User)
admin.site.register(User, UserAdmin)



class SessionAdmin(SemanticModelAdmin):
    def _session_data(self, obj):
        return obj.get_decoded()
    list_display = ['session_key', '_session_data', 'expire_date']
admin.site.register(Session, SessionAdmin)
