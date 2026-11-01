from main_app.presentation_style import assigned_template as _assigned_presentation_template, presentation_appearance
from django.utils.translation import gettext_lazy as _
from django.urls import reverse_lazy, reverse, resolve
from django.views.generic import TemplateView, DetailView
from django.forms import ModelForm
from django import forms

from main_app.views.api import ExecutionSerializer
from main_app.models import *
from main_app.utils.qr import qr_svg
from main_app.access import *
from django.core.exceptions import PermissionDenied

from django_tables2 import DateTimeColumn, Table, TemplateColumn, Column, RequestConfig
from django_tables2.views import SingleTableView
from django.views.generic.base import RedirectView
from django.views.generic.edit import FormView
from django.views.generic.edit import CreateView, UpdateView, DeleteView

from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.http import Http404, JsonResponse
from django.urls.exceptions import NoReverseMatch
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from python_ipware import IpWare
from leaflet.forms.widgets import LeafletWidget
from django.utils.text import slugify
from types import SimpleNamespace
import json
import requests
from urllib.parse import urlsplit, urlunsplit
from django.contrib.gis.db import models as geo_models
from wagtail.models import Page
from wagtail.images import get_image_model
from datetime import timedelta


TRACKED_PRESENTATION_TYPES = ('exhibition_user_device', 'piece_user_device')
SESSION_FAVORITES_KEY = 'presentation_favorites'
MAX_SLIDE_TRACKING_BATCH = 20
MAX_SLIDE_EVENT_CLOCK_DRIFT = timedelta(hours=1)


def _build_public_absolute_uri(request, path):
    """Build a public URL using the configured host instead of a loopback IP."""
    public_base = urlsplit(settings.SERVER_NAME)
    if not public_base.scheme or not public_base.netloc:
        return request.build_absolute_uri(path)

    path_parts = urlsplit(path)
    public_netloc = settings.PUBLIC_HOSTNAME
    if public_base.port:
        public_netloc = f'{public_netloc}:{public_base.port}'
    return urlunsplit((
        public_base.scheme,
        public_netloc,
        path_parts.path,
        path_parts.query,
        path_parts.fragment,
    ))



class PiecesTable(Table):
    action = TemplateColumn(template_name='main_app/models/pieces_table_link.html')
    date_created = DateTimeColumn(format="Y-m-d H:i")
    class Meta:
        model = Piece

        fields = ['date_created', 'action']

class ExhibitionsTable(Table):
    action = TemplateColumn(template_name='main_app/models/exhibitions_table_link.html')

    class Meta:
        model = Exhibition
        fields = ['title', 'description']


class MuseumForm(ModelForm):
    curators = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(profile__type='c'), required=False,
        help_text=_('Selected curators will be assigned to this museum.'),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['curators'].initial = User.objects.filter(profile__museum=self.instance, profile__type='c')

    def save(self, commit=True):
        museum = super().save(commit=commit)
        if commit:
            selected = self.cleaned_data['curators']
            for profile in UserProfile.objects.filter(museum=museum).exclude(user__in=selected):
                profile.museum = None
                profile.save()
            for user in selected:
                user.profile.museum = museum
                user.profile.save()
            museum.admins.set(selected)
        return museum

    class Meta:
        model = Museum
        fields = ['title', 'description']


def _can_manage_on_site_presentation(user, exhibition):
    return can_manage(user, exhibition)


def _can_view_statistics(user):
    return can_curate(user)


def _ensure_presentation_session(request):
    if not request.session.session_key:
        request.session.create()

    # Ensure there's a single PresentationSession row per Django session_key
    session_key = request.session.session_key
    presentation_session = PresentationSession.objects.filter(session_key=session_key).order_by('-created_at', '-pk').first()
    if presentation_session is None:
        presentation_session = PresentationSession.objects.create(
            session_key=session_key, user=request.user if request.user.is_authenticated else None,
        )
    # If user is authenticated and the session row has no user yet, attach it
    if request.user.is_authenticated and presentation_session.user is None:
        presentation_session.user = request.user
        presentation_session.save(update_fields=['user'])

    return presentation_session


def _log_presentation_access(request, presentation_type, title, exhibition=None, piece=None):
    presentation_session = _ensure_presentation_session(request)

    # Keep logs event-like: every new presentation visit is its own row.
    # Summary views still aggregate these rows when displaying totals.
    access = PresentationAccess.objects.create(
        presentation_session=presentation_session,
        presentation_type=presentation_type,
        presentation_title=title,
        presentation_path=request.path,
        exhibition=exhibition,
        piece=piece,
        last_accessed_at=timezone.now(),
        last_wagtail_page_index=0,
        last_wagtail_page_title="Slide 1",
        accesses=1,
    )
    return access


def _presentation_type_suffix(presentation_type):
    return 'user_device' if presentation_type.endswith('user_device') else 'on_site'


def _presentation_pages_for_access(access):
    slideshow_page = None
    if access.piece_id and access.piece and access.piece.slideshow_page:
        slideshow_page = access.piece.slideshow_page
    elif access.exhibition_id and access.exhibition and access.exhibition.slideshow_page:
        slideshow_page = access.exhibition.slideshow_page

    if not slideshow_page:
        return []

    presentation_type = _presentation_type_suffix(access.presentation_type)
    target_page = slideshow_page.get_children().filter(slug=presentation_type).specific().first()
    return _presentation_pages(target_page)


def _update_access_last_wagtail_page(access, slide_index):
    pages = _presentation_pages_for_access(access)
    if not pages:
        return

    clamped_index = max(0, min(int(slide_index), len(pages) - 1))
    target_page = pages[clamped_index]
    access.last_wagtail_page_index = clamped_index
    access.last_wagtail_page_title = target_page.title or ''
    access.save(update_fields=['last_wagtail_page_index', 'last_wagtail_page_title'])


def _access_date(access):
    return access.last_accessed_at or access.presentation_session.created_at


def _summarize_presentation_accesses(accesses, group_by_type=False, group_by_presentation=True, group_by_visitor=True):#this function is used to aggregate presentation accesses for the statistics view, grouping by user/session and presentation, and summing accesses
    grouped = {}

    for access in accesses:
        key = []
        if group_by_visitor:
            key.extend([
                access.session_or_user_history_kind,
                access.session_or_user_history_pk,
            ])
        if group_by_presentation:
            key.extend([
                access.presentation_history_kind,
                access.presentation_history_pk,
            ])
        if group_by_type:
            key.append(access.presentation_type)
        key = tuple(key)

        access_date = _access_date(access)
        if not access_date:
            access_date = timezone.now()

        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                'access': access,
                'accesses': access.accesses or 0,
                'last_accessed_at': access_date,
            }
            continue

        entry['accesses'] += access.accesses or 0
        if access_date > entry['last_accessed_at'] or (
            access_date == entry['last_accessed_at'] and access.id > entry['access'].id
        ):
            entry['access'] = access
            entry['last_accessed_at'] = access_date

    summary_rows = []
    for entry in grouped.values():
        access = entry['access']
        summary_rows.append(SimpleNamespace(
            display_session_or_user=access.display_session_or_user,
            session_or_user_history_kind=access.session_or_user_history_kind,
            session_or_user_history_pk=access.session_or_user_history_pk,
            presentation_title=access.presentation_title,
            presentation_history_kind=access.presentation_history_kind,
            presentation_history_pk=access.presentation_history_pk,
            exhibition_title=access.exhibition.title if access.exhibition_id and access.exhibition else '',
            museum_title=access.exhibition.museum.title if access.exhibition_id and access.exhibition and access.exhibition.museum_id else '',
            accesses=entry['accesses'],
            last_accessed_at=entry['last_accessed_at'],
            last_wagtail_page_title=access.last_wagtail_page_title,
            last_wagtail_page_index=access.last_wagtail_page_index,
            presentation_type=access.presentation_type,
            get_presentation_type_display=access.get_presentation_type_display(),
            display_presentation_mode=access.display_presentation_mode,
        ))

    summary_rows.sort(key=lambda item: item.last_accessed_at, reverse=True)
    return summary_rows


def _summarize_exhibition_accesses(accesses):
    grouped = {}

    for access in accesses:
        if not access.exhibition_id or not access.exhibition:
            continue

        access_date = _access_date(access) or timezone.now()
        entry = grouped.get(access.exhibition_id)
        if entry is None:
            grouped[access.exhibition_id] = {
                'access': access,
                'accesses': access.accesses or 0,
                'last_accessed_at': access_date,
            }
            continue

        entry['accesses'] += access.accesses or 0
        if access_date > entry['last_accessed_at'] or (
            access_date == entry['last_accessed_at'] and access.id > entry['access'].id
        ):
            entry['access'] = access
            entry['last_accessed_at'] = access_date

    summary_rows = []
    for entry in grouped.values():
        access = entry['access']
        exhibition = access.exhibition
        summary_rows.append(SimpleNamespace(
            presentation_title=exhibition.title,
            presentation_history_kind='exhibition',
            presentation_history_pk=exhibition.pk,
            museum_title=exhibition.museum.title if exhibition.museum_id else '',
            accesses=entry['accesses'],
            last_accessed_at=entry['last_accessed_at'],
        ))

    summary_rows.sort(key=lambda item: item.last_accessed_at, reverse=True)
    return summary_rows


def _featured_exhibition_pieces(exhibition, limit=3, user=None):
    pieces_with_accesses = list(
        visible_pieces(user).filter(exhibition=exhibition).annotate(
            access_total=Sum(
                'presentation_accesses__accesses',
                filter=Q(
                    presentation_accesses__presentation_type='piece_user_device',
                ),
            )
        )
        .filter(access_total__gt=0)
        .order_by('-access_total', 'id')[:limit]
    )

    selected_ids = [piece.pk for piece in pieces_with_accesses]
    selected_pieces = list(pieces_with_accesses)
    remaining_slots = limit - len(selected_pieces)
    if remaining_slots > 0:
        selected_pieces.extend(
            visible_pieces(user).filter(exhibition=exhibition).exclude(pk__in=selected_ids).order_by('?')[:remaining_slots]
        )

    return selected_pieces


def _normalize_attribute_names(raw_attributes):
    if not isinstance(raw_attributes, list):
        return []

    names = []
    seen = set()
    for item in raw_attributes:
        if isinstance(item, dict):
            name = str(item.get('name', '')).strip()
        else:
            name = str(item).strip()

        if not name:
            continue

        key = name.lower()
        if key in seen:
            continue

        seen.add(key)
        names.append(name)

    return names


def _piece_attribute_entries(piece):
    raw_entries = piece.attributes if isinstance(piece.attributes, list) else []
    entries = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue

        name = str(item.get('name', '')).strip()
        if not name:
            continue

        value = str(item.get('value', '')).strip()
        entries.append({'name': name, 'value': value})

    return entries


def _piece_value_map(piece):
    value_map = {}
    for item in _piece_attribute_entries(piece):
        key = item['name'].lower()
        if key not in value_map:
            value_map[key] = item['value']
    return value_map


def _ordered_attributes(exhibition):
    if exhibition is None:
        return []
    return _normalize_attribute_names(exhibition.pieces_attributes)


def _piece_fallback_name(piece, value_map=None):
    if piece.slideshow_page_id and piece.slideshow_page and piece.slideshow_page.title:
        return piece.slideshow_page.title.strip()

    value_map = value_map or _piece_value_map(piece)
    for key, value in value_map.items():
        if key != 'name' and value:
            return value.strip()

    return f"Piece {piece.pk}"


def _ensure_piece_name_value(piece):
    entries = _piece_attribute_entries(piece)
    value_map = _piece_value_map(piece)
    fallback = _piece_fallback_name(piece, value_map)
    changed = False
    has_name = False

    for item in entries:
        if item['name'].lower() == 'name':
            has_name = True
            if not item['value']:
                item['value'] = fallback
                changed = True
            break

    if not has_name:
        entries.insert(0, {'name': 'Name', 'value': fallback})
        changed = True

    if changed:
        piece.attributes = entries
        piece.save(update_fields=['attributes'])


def _ensure_default_name_attribute(exhibition):
    names = _ordered_attributes(exhibition)
    if not any(name.lower() == 'name' for name in names):
        names.insert(0, 'Name')
        exhibition.pieces_attributes = names
        exhibition.save(update_fields=['pieces_attributes'])

    pieces = exhibition.pieces.all().select_related('slideshow_page')
    for piece in pieces:
        _ensure_piece_name_value(piece)

    return names

def _unique_child_slug(parent_page, base_slug):
    """Generate a non-colliding slug for a child page under parent."""
    base = slugify(base_slug) or "page"
    slug = base
    index = 2
    while parent_page.get_children().filter(slug=slug).exists():
        slug = f"{base}-{index}"
        index += 1
    return slug

######This is to make sure pages start unpublished
def _save_as_draft(page):
    page.save_revision()
    if page.live:
        page.unpublish()


def _get_or_create_child_page(parent_page, model_class, title, slug, **kwargs):
    existing = parent_page.get_children().filter(slug=slug).first()
    if existing:
        return existing.specific

    child = model_class(title=title, slug=slug, **kwargs)
    parent_page.add_child(instance=child)
    _save_as_draft(child)
    return child
#THIS ensures folders so that curators don't have to worry about the Wagtail 
# page tree structure when creating exhibitions and pieces

def _ensure_presentation_folders(slideshow_page):
    folders = {
        'on_site': None,
        'user_device': None,
    }
    if slideshow_page is None:
        return folders

    parent_page = slideshow_page.specific

    if isinstance(parent_page, ExhibitionPage):
        folders['on_site'] = _get_or_create_child_page(
            parent_page,
            ExhibitionOnSitePage,
            title="On Site",
            slug="on_site",
        )
        folders['user_device'] = _get_or_create_child_page(
            parent_page,
            ExhibitionUserDevicePage,
            title="User Device",
            slug="user_device",
        )
        return folders

    if isinstance(parent_page, PiecePage):
        folders['on_site'] = _get_or_create_child_page(
            parent_page,
            PieceOnSitePage,
            title="On Site",
            slug="on_site",
        )
        folders['user_device'] = _get_or_create_child_page(
            parent_page,
            PieceUserDevicePage,
            title="User Device",
            slug="user_device",
        )
        return folders

    folders['on_site'] = parent_page.get_children().filter(slug='on_site').first()
    folders['user_device'] = parent_page.get_children().filter(slug='user_device').first()
    return {
        'on_site': folders['on_site'].specific if folders['on_site'] else None,
        'user_device': folders['user_device'].specific if folders['user_device'] else None,
    }


def _presentation_links(slideshow_page):
    links = {
        'on_site': None,
        'user_device': None,
    }
    folders = _ensure_presentation_folders(slideshow_page)
    on_site_page = folders['on_site']
    user_device_page = folders['user_device']

    try:
        if on_site_page:
            links['on_site'] = reverse('wagtailadmin_explore', args=[on_site_page.id])
        if user_device_page:
            links['user_device'] = reverse('wagtailadmin_explore', args=[user_device_page.id])
    except NoReverseMatch:
        pass

    return links


def _presentation_pages(slideshow_page):
    if slideshow_page is None:
        return []

    root_page = slideshow_page.specific
    pages = list(root_page.get_children().specific().order_by('path'))
    return pages or [root_page]


def _presentation_context(slideshow_page, presentation_type, user=None, obj=None):
    folder = presentation_folder(obj, presentation_type)
    preview = can_preview(user, obj)
    presentation_pages = []
    if folder and (preview or folder.live):
        children = folder.get_children().specific().order_by('path')
        if not preview:
            children = children.live()
        presentation_pages = list(children) or [folder]
        if preview:
            presentation_pages = [page.get_latest_revision_as_object() for page in presentation_pages]

    return {
        'presentation_type': presentation_type,
        'presentation_pages': presentation_pages,
    }




def _build_piece_rows(exhibition):
    attributes = _ordered_attributes(exhibition)
    has_custom_attributes = len(attributes) > 0
    display_attributes = [{'name': attribute} for attribute in attributes] if has_custom_attributes else [{'name': _('Name')}]
    pieces = exhibition.pieces.all().order_by('-date_created')
    rows = []
    for piece in pieces:
        value_map = _piece_value_map(piece)
        rows.append({
            'piece': piece,
            'values': [value_map.get(attribute.lower()) or '???' for attribute in attributes] if has_custom_attributes else [str(piece)],
            'presentations': _presentation_links(piece.slideshow_page),
        })
    return display_attributes, rows, has_custom_attributes


def _piece_shared_hero_image(piece):
    if not piece or not piece.slideshow_page_id or not piece.slideshow_page:
        return None

    children_by_slug = {
        child.slug: child.specific
        for child in piece.slideshow_page.get_children().specific()
        if child.slug in {'on_site', 'user_device'}
    }
    for slug in ('on_site', 'user_device'):
        page = children_by_slug.get(slug)
        hero_image = getattr(page, 'hero_image', None)
        if hero_image:
            return hero_image

    return None


def _save_piece_shared_hero_image(piece, uploaded_file):
    if not uploaded_file:
        return None

    if not piece.slideshow_page_id:
        return None

    image_model = get_image_model()
    wagtail_image = image_model.objects.create(
        title=str(piece),
        file=uploaded_file,
    )

    folders = _ensure_presentation_folders(piece.slideshow_page)
    for presentation_type in ('on_site', 'user_device'):
        page = folders.get(presentation_type)
        if page:
            page.hero_image = wagtail_image
            page.save(update_fields=['hero_image'])

    return wagtail_image


class MuseumsListView(CuratorRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/museums.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        museums = (Museum.objects.all() if is_administrator(self.request.user) else Museum.objects.filter(pk=self.request.user.profile.museum_id)).annotate(
            exhibition_count=Count('exhibitions')
        ).order_by('title')
        context['museum_cards'] = [
            {
                'museum': museum,
                'exhibition_count': museum.exhibition_count,
            }
            for museum in museums
        ]
        context['base'] = "main_app/layout/base.html"
        return context


class MuseumCreateView(AdministratorRequiredMixin, LoginRequiredMixin, CreateView):
    model = Museum
    form_class = MuseumForm
    template_name = 'main_app/models/museum_edit.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        return response

    def get_success_url(self):
        return reverse('main_app:museums-list')


class MuseumDeleteView(AdministratorRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Museum
    template_name = 'main_app/models/museum_confirm_delete.html'

    def get_object(self):
        return get_object_or_404(Museum, pk=self.kwargs['pk'])

    def get_success_url(self):
        return reverse('main_app:museums-list')


class MuseumChangeView(AdministratorRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/museum_change.html'

    def dispatch(self, request, *args, **kwargs):
        self.museum = get_object_or_404(Museum, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        form = MuseumForm(request.POST, instance=self.museum)
        selected_ids = set()
        for raw_id in request.POST.getlist('exhibitions'):
            try:
                selected_ids.add(int(raw_id))
            except (TypeError, ValueError):
                continue

        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        manageable_exhibitions = managed_exhibitions(request.user)
        with transaction.atomic():
            form.save()
            manageable_exhibitions.filter(pk__in=selected_ids).update(museum=self.museum)
            manageable_exhibitions.filter(museum=self.museum).exclude(pk__in=selected_ids).update(museum=None)
            from main_app.role_permissions import sync_museum_access
            sync_museum_access()

        return redirect('main_app:museums-list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        exhibitions = managed_exhibitions(self.request.user).select_related('museum').order_by('title')
        context['museum'] = self.museum
        context['form'] = kwargs.get('form') or MuseumForm(instance=self.museum)
        context['exhibition_rows'] = [
            {
                'exhibition': exhibition,
                'checked': exhibition.museum_id == self.museum.pk,
                'current_museum': exhibition.museum,
            }
            for exhibition in exhibitions
        ]
        context['base'] = "main_app/layout/base.html"
        return context


class PieceDynamicForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.attribute_definitions = kwargs.pop('attribute_definitions', [])
        include_default_name = kwargs.pop('include_default_name', False)
        initial_values = kwargs.pop('initial_values', {})
        super().__init__(*args, **kwargs)

        if include_default_name and not self.attribute_definitions:
            self.fields['default_piece_name'] = forms.CharField(
                label=_('Name'),
                required=True,
                initial=initial_values.get('default_piece_name', ''),
            )

        for index, attribute_name in enumerate(self.attribute_definitions):
            field_name = f'attribute_{index}'
            self.fields[field_name] = forms.CharField(
                label=attribute_name,
                required=False,
                initial=initial_values.get(attribute_name.lower(), ''),
            )

        self.fields['piece_image'] = forms.ImageField(
            label=_('Piece image'),
            required=False,
            help_text=_('Used for both On Site and User Device presentations.'),
        )

    def cleaned_attribute_values(self):
        values = []
        for index, attribute_name in enumerate(self.attribute_definitions):
            field_name = f'attribute_{index}'
            values.append((attribute_name, self.cleaned_data.get(field_name, '').strip()))
        return values


class ExhibitionsListView(CuratorRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/pieces_overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        exhibitions = managed_exhibitions(self.request.user).annotate(
            piece_count=Count('pieces')
        ).order_by('title')

        exhibition_cards = []
        for exhibition in exhibitions:
            exhibition_cards.append({
                'exhibition': exhibition,
                'piece_count': exhibition.piece_count,
            })

        context['exhibition_cards'] = exhibition_cards
        context['base'] = "main_app/layout/base.html"
        return context


class ExhibitionView(CuratorRequiredMixin, LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        expo = get_object_or_404(managed_exhibitions(self.request.user), pk=kwargs['pk'])
        context['exhibition'] = expo
        context['pieces'] = expo.pieces.all()
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/exhibition.html']


class ExhibitionForm(ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not is_administrator(user):
            self.fields.pop('museum', None)

    class Meta:
        model = Exhibition
        fields = ['title', 'description', 'museum']


class ExhibitionBulkPiecesForm(forms.Form):
    spreadsheet = forms.FileField(
        label=_('ODS or Excel file'),
        help_text=_('The filename must match this exhibition title. Existing pieces are updated by Name.'),
    )



  #  def get_self.object success_url(self):
   #     new_exh_page = ExhibitionPage()
    ##   new_exh_page.description = self.object.description
     #   new_exh_page.save()        
      #  self.object.wag_slides = new_exh_page
#        self.object.save()
       # return reverse('main_app:exhibitions-list')


class ExhibitionCreateView(CuratorRequiredMixin, LoginRequiredMixin, CreateView):
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    model = Exhibition
    form_class = ExhibitionForm
    template_name = 'main_app/models/exhibition_edit.html'

    def get_success_url(self):
        return reverse('main_app:exhibitions-list')

    @staticmethod
    def _save_as_draft(page):
        _save_as_draft(page)

    @staticmethod
    def _unique_child_slug(parent_page, base_slug):
        return _unique_child_slug(parent_page, base_slug)

    @staticmethod
    def _get_or_create_child(parent_page, model_class, title, slug, **kwargs):
        return _get_or_create_child_page(parent_page, model_class, title, slug, **kwargs)

    def _ensure_exhibition_slideshow_tree(self):
        if self.object.slideshow_page_id:
            return self.object.slideshow_page

        root_page = Page.get_first_root_node()
        exhibition_slug = self._unique_child_slug(root_page, self.object.title)
        exhibition_page = ExhibitionPage(
            title=self.object.title,
            slug=exhibition_slug,
            description=self.object.description,
        )
        root_page.add_child(instance=exhibition_page)
        self._save_as_draft(exhibition_page)

        self._get_or_create_child(
            exhibition_page,
            ExhibitionOnSitePage,
            title="On Site",
            slug="on_site",
        )
        exhibition_user_device_page = self._get_or_create_child(
            exhibition_page,
            ExhibitionUserDevicePage,
            title="User Device",
            slug="user_device",
        )
        # Add default slide page to User Device folder
        self._get_or_create_child(
            exhibition_user_device_page,
            SlideshowSlidePage,
            title="Slide 1",
            slug="slide_1",
        )
        self._get_or_create_child(
            exhibition_page,
            ExhibitionPiecesListPage,
            title="Pieces",
            slug="pieces",
        )

        self.object.slideshow_page = exhibition_page
        self.object.save(update_fields=['slideshow_page'])
        return exhibition_page

    def form_valid(self, form):
        with transaction.atomic():
            if is_curator(self.request.user):
                form.instance.museum = curator_museum(self.request.user)
            resp = super().form_valid(form)
            self.object.admins.add(self.request.user)
            self._ensure_exhibition_slideshow_tree()
            return resp


class ExhibitionUpdateView(CuratorRequiredMixin, LoginRequiredMixin, UpdateView):
    def get_queryset(self):
        return managed_exhibitions(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    model = Exhibition
    form_class = ExhibitionForm
    template_name = 'main_app/models/exhibition_edit.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        _ensure_default_name_attribute(self.object)
        
        attributes = _ordered_attributes(self.object)
        has_custom_attributes = len(attributes) > 0

        attrs = {
            'date_created': DateTimeColumn(verbose_name=_('Date created'), format="Y-m-d H:i"),
            'name': TemplateColumn(
                template_code='''
                    <span class="piece-preview-link">
                        <a href="{% url "main_app:piece-update" record.pk %}" class="piece-preview-anchor" data-preview-url="{{ record.preview_image_url }}" data-preview-name="{{ record.name }}">{{ record.name }}</a>
                    </span>
                ''',
                verbose_name=_('Name'),
            ),
        }

        DynamicPiecesTable = type('DynamicPiecesTable', (Table,), attrs)

        pieces = self.object.pieces.all().order_by('-date_created')
        table_data = []
        for piece in pieces:
            preview_image_url = ''
            hero_image = _piece_shared_hero_image(piece)
            if hero_image:
                try:
                    preview_image_url = hero_image.get_rendition('fill-240x240').url
                except Exception:
                    preview_image_url = hero_image.file.url

            table_data.append({
                'pk': piece.pk,
                'date_created': piece.date_created,
                'name': str(piece),
                'preview_image_url': preview_image_url,
            })

        table = DynamicPiecesTable(table_data)
        RequestConfig(self.request).configure(table)

        context['table'] = table
        context['has_piece_attributes'] = has_custom_attributes
        context['exhibition_presentations'] = _presentation_links(self.object.slideshow_page)
        return context

    def form_valid(self, form):
        form.instance.show_on_site_qr = 'show_on_site_qr' in self.request.POST
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('main_app:exhibition-update', kwargs={'pk': self.object.pk})


class ExhibitionUserDeviceQRCodesView(CuratorRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/exhibition_user_device_qrs.html'

    def dispatch(self, request, *args, **kwargs):
        self.exhibition = get_object_or_404(
            Exhibition.objects.prefetch_related('pieces'),
            pk=kwargs['pk'],
        )
        if not _can_manage_on_site_presentation(request.user, self.exhibition):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        exhibition_url = _build_public_absolute_uri(
            self.request,
            reverse('main_app:exhibition-public-presentation', kwargs={'public_id': self.exhibition.public_id})
        )
        qr_items = [{
            'title': self.exhibition.title,
            'kind': _('Exhibition'),
            'url': exhibition_url,
            'qr_svg': qr_svg(exhibition_url),
        }]

        for piece in self.exhibition.pieces.all().order_by('id'):
            piece_url = _build_public_absolute_uri(
                self.request,
                reverse('main_app:piece-public-presentation', kwargs={'public_id': piece.public_id})
            )
            qr_items.append({
                'title': str(piece),
                'kind': _('Piece'),
                'url': piece_url,
                'qr_svg': qr_svg(piece_url),
            })

        context['exhibition'] = self.exhibition
        context['qr_items'] = qr_items
        return context


class ExhibitionDeleteView(CuratorRequiredMixin, LoginRequiredMixin, DeleteView):
    model = Exhibition
    template_name = 'main_app/models/exhibition_confirm_delete.html'
    
    def get_object(self):
        obj = super().get_object()
        # Ensure user is an admin of this exhibition
        if not can_manage(self.request.user, obj):
            raise Http404
        return obj
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        delete_exhibition_presentation_favorites(self.object)
        
        # Delete the associated wagtail page if it exists
        if self.object.slideshow_page:
            slideshow_page = self.object.slideshow_page
            slideshow_page.delete()
        
        # Delete all pieces and their wagtail pages
        for piece in self.object.pieces.all():
            if piece.slideshow_page:
                piece.slideshow_page.delete()
            piece.delete()
        
        # Delete the exhibition itself
        return super().delete(request, *args, **kwargs)
    
    def get_success_url(self):
        return reverse('main_app:exhibitions-list')


class ExhibitionPresentationView(TemplateView):
    template_name = 'main_app/models/exhibition_presentation.html'

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, request, *args, **kwargs):
        self.presentation_type = kwargs.get('presentation_type', 'user_device')
        lookup = {'public_id': kwargs['public_id']} if 'public_id' in kwargs else {'pk': kwargs['pk']}
        self.exhibition = get_object_or_404(
            Exhibition.objects.select_related('slideshow_page', 'museum'),
            **lookup,
        )
        if self.presentation_type not in {'on_site', 'user_device'}:
            raise Http404

        if 'public_id' not in kwargs and self.presentation_type == 'user_device':
            raise Http404

        if not can_view_presentation(request.user, self.exhibition, self.presentation_type):
            raise Http404
        self.presentation_access = None
        if self.presentation_type == 'user_device':
            self.presentation_access = _log_presentation_access(
                request,
                f'exhibition_{self.presentation_type}',
                self.exhibition.title,
                exhibition=self.exhibition,
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exhibition'] = self.exhibition
        context['presentation_appearance'] = presentation_appearance(self.exhibition)
        context.update(_presentation_context(self.exhibition.slideshow_page, self.presentation_type, self.request.user, self.exhibition))
        context['active_presentation_template'] = _assigned_presentation_template(
            self.exhibition,
            self.presentation_type,
        )
        context['is_user_device_presentation'] = self.presentation_type == 'user_device'
        context['presentation_page_count'] = len(context['presentation_pages']) + (1 if self.presentation_type == 'user_device' else 0)
        context['pieces'] = visible_pieces(self.request.user).filter(exhibition=self.exhibition).order_by('-date_created')
        context['featured_pieces'] = _featured_exhibition_pieces(self.exhibition, user=self.request.user)
        self.request.presentation_exhibition_id = self.exhibition.pk
        from main_app.visitor import visitor_history
        context['visitor_history'] = visitor_history(self.request)
        context['visited_museum_id'] = f'museum:{self.exhibition.museum_id}' if self.exhibition.museum_id else f'not-on-display:{self.exhibition.pk}'
        context['visited_exhibition_id'] = f'exhibition:{self.exhibition.public_id}'
        context['visited_museum_name'] = self.exhibition.museum.title if self.exhibition.museum_id else ''
        context['visited_exhibition_name'] = self.exhibition.title
        context['visited_exhibition_path'] = reverse(
            'main_app:exhibition-public-presentation',
            kwargs={'public_id': self.exhibition.public_id},
        )
        if self.presentation_access:
            context['slide_tracking_url'] = reverse(
                'main_app:presentation-access-slide',
                kwargs={'pk': self.presentation_access.pk},
            )
        if self.presentation_type == 'on_site' and self.exhibition.show_on_site_qr:
            user_device_url = _build_public_absolute_uri(
                self.request,
                reverse('main_app:exhibition-public-presentation', kwargs={'public_id': self.exhibition.public_id})
            )
            context['user_device_presentation_url'] = user_device_url
            context['user_device_presentation_qr_svg'] = qr_svg(user_device_url)
        return context
    
class ExhibitionAddPiecesView(CuratorRequiredMixin, LoginRequiredMixin, FormView):
    form_class = ExhibitionBulkPiecesForm
    template_name = 'main_app/models/exhibition_bulk_import.html'

    def dispatch(self, request, *args, **kwargs):
        self.exhibition = get_object_or_404(managed_exhibitions(request.user), pk=kwargs['pk'])
        if not _can_manage_on_site_presentation(request.user, self.exhibition):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        from main_app.utils.feeder import FeederImporter, FeederImportError

        importer = FeederImporter()
        try:
            result = importer.import_uploaded_file(
                form.cleaned_data['spreadsheet'],
                exhibition=self.exhibition,
                admin_user=self.request.user,
            )
        except FeederImportError as exc:
            form.add_error('spreadsheet', str(exc))
            return self.form_invalid(form)

        messages.success(
            self.request,
            _(
                'Bulk import finished: %(created)s created, %(updated)s updated, %(ignored)s ignored.'
            ) % {
                'created': result.created,
                'updated': result.updated,
                'ignored': result.ignored,
            },
        )
        return redirect('main_app:exhibition-update', pk=self.exhibition.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exhibition'] = self.exhibition
        context['base'] = "main_app/layout/base.html"
        return context


class ExhibitionAttributesCreateView(CuratorRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/exhibition_attributes_edit.html'

    def dispatch(self, request, *args, **kwargs):
        self.exhibition = get_object_or_404(managed_exhibitions(request.user), pk=kwargs['pk'])
        _ensure_default_name_attribute(self.exhibition)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        names = _normalize_attribute_names(request.POST.getlist('attribute_names'))

        if not names:
            context = self.get_context_data(error=_('At least one attribute is required.'))
            return self.render_to_response(context)

        with transaction.atomic():
            self.exhibition.pieces_attributes = names
            self.exhibition.save(update_fields=['pieces_attributes'])
            _ensure_default_name_attribute(self.exhibition)

        return redirect('main_app:exhibition-update', pk=self.exhibition.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exhibition'] = self.exhibition
        context['existing_attributes'] = _ordered_attributes(self.exhibition)
        context['base'] = "main_app/layout/base.html"
        context.update(kwargs)
        return context


class PieceForm(PieceDynamicForm):
    pass



class PieceView(TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        piece = get_object_or_404(visible_pieces(self.request.user), pk=kwargs['pk'])
        ordered_attributes = _ordered_attributes(piece.exhibition)
        value_map = _piece_value_map(piece)
        context['piece'] = piece
        context['can_edit_piece'] = can_manage(self.request.user, piece.exhibition)
        context['piece_name'] = str(piece)
        context['attribute_rows'] = [
            (attribute, value_map.get(attribute.lower(), ''))
            for attribute in ordered_attributes
        ]
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/piece.html']


class PieceCreateView(CuratorRequiredMixin, LoginRequiredMixin, FormView):
    form_class = PieceForm
    template_name = 'main_app/models/piece_edit.html'

    def dispatch(self, request, *args, **kwargs):
        exhibition_id = kwargs.get('exhibition_id') or request.GET.get('exhibition_id')
        if not exhibition_id:
            raise Http404
        self.exhibition = get_object_or_404(managed_exhibitions(request.user), pk=exhibition_id)
        self.attribute_definitions = _ordered_attributes(self.exhibition)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['attribute_definitions'] = self.attribute_definitions
        kwargs['include_default_name'] = len(self.attribute_definitions) == 0
        return kwargs

    def form_valid(self, form):
        with transaction.atomic(): #attomic transaction to ensure piece and page creation are consistent
            self.object = Piece.objects.create(exhibition=self.exhibition)
            if self.attribute_definitions:
                self.object.attributes = self._build_attributes_payload(form.cleaned_attribute_values())
            else:
                self.default_piece_name = form.cleaned_data.get('default_piece_name', '').strip()
                self.object.attributes = [{'name': 'Name', 'value': self.default_piece_name}]

            self.object.save(update_fields=['attributes'])
            _ensure_piece_name_value(self.object)
            self.default_piece_name = str(self.object)
            self._ensure_piece_slideshow_tree()
            _save_piece_shared_hero_image(self.object, form.cleaned_data.get('piece_image'))
            return super().form_valid(form)

    def _build_attributes_payload(self, cleaned_values):
        return [
            {'name': attribute_name, 'value': value}
            for attribute_name, value in cleaned_values
        ]

    def _get_or_create_piece_parent(self):
        exhibition_page = self.exhibition.slideshow_page
        if exhibition_page is None:
            creator = ExhibitionCreateView()
            creator.object = self.exhibition
            exhibition_page = creator._ensure_exhibition_slideshow_tree()

        pieces_page = exhibition_page.get_children().filter(slug='pieces').first()
        if pieces_page:
            return pieces_page.specific

        pieces_page = ExhibitionCreateView._get_or_create_child(
            exhibition_page,
            ExhibitionPiecesListPage,
            title="Pieces",
            slug="pieces",
        )
        return pieces_page

    def _ensure_piece_slideshow_tree(self):
        if self.object.slideshow_page_id:
            return self.object.slideshow_page

        pieces_page = self._get_or_create_piece_parent()
        page_title = getattr(self, 'default_piece_name', '') or str(self.object)
        piece_slug = ExhibitionCreateView._unique_child_slug(pieces_page, f"piece-{self.object.pk}")
        piece_page = PiecePage(
            title=page_title,
            slug=piece_slug,
        )
        pieces_page.add_child(instance=piece_page)
        ExhibitionCreateView._save_as_draft(piece_page)

        ExhibitionCreateView._get_or_create_child(
            piece_page,
            PieceOnSitePage,
            title="On Site",
            slug="on_site",
        )
        piece_user_device_page = ExhibitionCreateView._get_or_create_child(
            piece_page,
            PieceUserDevicePage,
            title="User Device",
            slug="user_device",
        )
        # Add default slide page to User Device folder
        ExhibitionCreateView._get_or_create_child(
            piece_user_device_page,
            SlideshowSlidePage,
            title="Slide 1",
            slug="slide_1",
        )

        self.object.slideshow_page = piece_page
        self.object.save(update_fields=['slideshow_page'])
        return piece_page

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exhibition'] = self.exhibition
        context['has_piece_attributes'] = len(self.attribute_definitions) > 0
        return context

    def get_success_url(self):
        return reverse('main_app:exhibition-update', kwargs={'pk': self.exhibition.pk})


class PieceUpdateView(CuratorRequiredMixin, LoginRequiredMixin, FormView):
    form_class = PieceForm
    template_name = 'main_app/models/piece_edit.html'

    def get_queryset(self):
        return managed_pieces(self.request.user)

    def dispatch(self, request, *args, **kwargs):
        self.object = get_object_or_404(self.get_queryset(), pk=kwargs['pk'])
        self.exhibition = self.object.exhibition
        self.attribute_definitions = _ordered_attributes(self.exhibition)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial_values = _piece_value_map(self.object)
        initial_values['default_piece_name'] = str(self.object)
        kwargs['include_default_name'] = not self.attribute_definitions
        kwargs['attribute_definitions'] = self.attribute_definitions
        kwargs['initial_values'] = initial_values
        return kwargs# returning the initial values to pre-populate the form fields with existing attribute values

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['exhibition'] = forms.ModelChoiceField(
            queryset=managed_exhibitions(self.request.user), initial=self.object.exhibition_id,
        )
        return form

    @transaction.atomic
    def form_valid(self, form):
        target = form.cleaned_data['exhibition']
        if target.pk != self.object.exhibition_id:
            builder = PieceCreateView()
            builder.exhibition = target
            parent = builder._get_or_create_piece_parent()
            if self.object.slideshow_page_id:
                page = self.object.slideshow_page
                if parent.get_children().filter(slug=page.slug).exclude(pk=page.pk).exists():
                    page.slug = _unique_child_slug(parent, page.slug)
                    page.save(update_fields=['slug'])
                page.move(parent, pos='last-child')
            self.object.exhibition = target
            self.object.save(update_fields=['exhibition'])
        self.object.attributes = [
            {'name': attribute_name, 'value': value}
            for attribute_name, value in form.cleaned_attribute_values()
        ]
        if not self.attribute_definitions:
            self.object.attributes = [{'name': 'Name', 'value': form.cleaned_data['default_piece_name']}]
        self.object.save(update_fields=['attributes'])
        _ensure_piece_name_value(self.object)
        _save_piece_shared_hero_image(self.object, form.cleaned_data.get('piece_image'))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exhibition'] = self.object.exhibition
        context['has_piece_attributes'] = len(self.attribute_definitions) > 0
        context['piece_presentations'] = _presentation_links(self.object.slideshow_page)
        context['piece'] = self.object
        context['object'] = self.object
        current_image = _piece_shared_hero_image(self.object)
        context['current_piece_image_url'] = current_image.file.url if current_image else ''
        return context

    def get_success_url(self):
        return reverse('main_app:exhibition-update', kwargs={'pk': self.object.exhibition.pk})


class PieceDeleteView(CuratorRequiredMixin, LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        piece = get_object_or_404(
            managed_pieces(request.user).select_related('slideshow_page', 'exhibition'),
            pk=kwargs['pk'],
        )
        exhibition_pk = piece.exhibition_id

        with transaction.atomic():
            delete_piece_presentation_favorites(piece)
            if piece.slideshow_page_id:
                piece.slideshow_page.delete()
            piece.delete()

        return redirect('main_app:exhibition-update', pk=exhibition_pk)


class PiecePresentationView(TemplateView):
    template_name = 'main_app/models/piece_presentation.html'

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, request, *args, **kwargs):
        self.presentation_type = kwargs.get('presentation_type', 'user_device')
        lookup = {'public_id': kwargs['public_id']} if 'public_id' in kwargs else {'pk': kwargs['pk']}
        self.piece = get_object_or_404(
            Piece.objects.select_related('slideshow_page', 'exhibition', 'exhibition__museum'),
            **lookup,
        )
        if self.presentation_type not in {'on_site', 'user_device'}:
            raise Http404

        if 'public_id' not in kwargs and self.presentation_type == 'user_device':
            raise Http404

        if not can_view_presentation(request.user, self.piece, self.presentation_type):
            raise Http404
        self.presentation_access = None
        if self.presentation_type == 'user_device':
            self.presentation_access = _log_presentation_access(
                request,
                f'piece_{self.presentation_type}',
                str(self.piece),
                exhibition=self.piece.exhibition,
                piece=self.piece,
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['piece'] = self.piece
        context['piece_name'] = str(self.piece)
        self.request.presentation_exhibition_id = self.piece.exhibition_id
        from main_app.visitor import visitor_history
        context['visitor_history'] = visitor_history(self.request)
        context['visited_museum_id'] = f'museum:{self.piece.exhibition.museum_id}' if self.piece.exhibition_id and self.piece.exhibition.museum_id else f'not-on-display:{self.piece.exhibition_id}'
        context['visited_exhibition_id'] = f'exhibition:{self.piece.exhibition.public_id}' if self.piece.exhibition_id else ''
        context['visited_piece_id'] = f'piece:{self.piece.public_id}'
        context['visited_museum_name'] = self.piece.exhibition.museum.title if self.piece.exhibition_id and self.piece.exhibition.museum_id else ''
        context['visited_exhibition_name'] = self.piece.exhibition.title if self.piece.exhibition_id else ''
        context['visited_exhibition_path'] = reverse(
            'main_app:exhibition-public-presentation',
            kwargs={'public_id': self.piece.exhibition.public_id},
        ) if self.piece.exhibition_id else ''
        context['visited_piece_name'] = str(self.piece)
        context['visited_piece_path'] = reverse(
            'main_app:piece-public-presentation',
            kwargs={'public_id': self.piece.public_id},
        )
        ordered_attributes = _ordered_attributes(self.piece.exhibition)
        value_map = _piece_value_map(self.piece)
        context['attribute_rows'] = [
            (attribute, value_map.get(attribute.lower(), ''))
            for attribute in ordered_attributes
        ]
        context.update(_presentation_context(self.piece.slideshow_page, self.presentation_type, self.request.user, self.piece))
        context['presentation_appearance'] = presentation_appearance(self.piece.exhibition)
        context['active_presentation_template'] = _assigned_presentation_template(
            self.piece.exhibition,
            self.presentation_type,
            piece=self.piece,
        )
        context['is_user_device_presentation'] = self.presentation_type == 'user_device'
        context['presentation_page_count'] = len(context['presentation_pages']) + (1 if self.presentation_type == 'user_device' else 0)
        if self.presentation_access:
            context['slide_tracking_url'] = reverse(
                'main_app:presentation-access-slide',
                kwargs={'pk': self.presentation_access.pk},
            )
        if self.presentation_type == 'on_site' and self.piece.exhibition_id and self.piece.exhibition.show_on_site_qr:
            user_device_url = _build_public_absolute_uri(
                self.request,
                reverse('main_app:piece-public-presentation', kwargs={'public_id': self.piece.public_id})
            )
            context['user_device_presentation_url'] = user_device_url
            context['user_device_presentation_qr_svg'] = qr_svg(user_device_url)
        return context


class PresentationAccessSlideUpdateView(View):
    def _get_access(self, request, pk):
        access = get_object_or_404(
            PresentationAccess.objects.select_related('presentation_session', 'exhibition', 'piece'),
            pk=pk,
        )
        if access.presentation_session.user_id:
            if not request.user.is_authenticated or request.user.pk != access.presentation_session.user_id:
                raise Http404
        else:
            if request.session.session_key != access.presentation_session.session_key:
                raise Http404
        return access

    def post(self, request, *args, **kwargs):
        access = self._get_access(request, kwargs['pk'])
        try:
            payload = json.loads(request.body or '{}')
            events = payload.get('events', [])
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'ok': False, 'error': 'invalid JSON payload'}, status=400)

        if not isinstance(events, list) or not events or len(events) > MAX_SLIDE_TRACKING_BATCH:
            return JsonResponse({'ok': False, 'error': 'invalid event batch'}, status=400)

        now = timezone.now()
        rows = []
        previous_slide_index = None
        for event in events:
            if not isinstance(event, dict):
                return JsonResponse({'ok': False, 'error': 'invalid slide event'}, status=400)
            try:
                slide_index = int(event.get('slide_index'))
            except (TypeError, ValueError):
                return JsonResponse({'ok': False, 'error': 'invalid slide index'}, status=400)
            if slide_index < 0:
                return JsonResponse({'ok': False, 'error': 'invalid slide index'}, status=400)

            # Ignore consecutive duplicates without collapsing legitimate revisits.
            if slide_index == previous_slide_index:
                continue
            previous_slide_index = slide_index

            occurred_at = parse_datetime(str(event.get('occurred_at', '')))
            if occurred_at is None:
                occurred_at = now
            elif timezone.is_naive(occurred_at):
                occurred_at = timezone.make_aware(occurred_at)
            if abs(now - occurred_at) > MAX_SLIDE_EVENT_CLOCK_DRIFT:
                occurred_at = now

            rows.append(PresentationAccess(
                presentation_session=access.presentation_session,
                presentation_type=access.presentation_type,
                presentation_title=access.presentation_title,
                presentation_path=access.presentation_path,
                exhibition=access.exhibition,
                piece=access.piece,
                last_accessed_at=occurred_at,
                last_wagtail_page_index=slide_index,
                last_wagtail_page_title=f"Slide {slide_index + 1}",
                accesses=1,
            ))

        PresentationAccess.objects.bulk_create(rows)
        return JsonResponse({'ok': True, 'created': len(rows)})


class PresentationFavoritesView(View):
    def _favorite_path_exists(self, path, visible=True):
        if not path.startswith('/') or path.startswith('//') or urlsplit(path).netloc:
            return False
        try:
            match = resolve(urlsplit(path).path)
        except Exception:
            return False

        model = {'exhibition-public-presentation': Exhibition, 'piece-public-presentation': Piece}.get(match.url_name)
        if model:
            obj = model.objects.filter(public_id=match.kwargs.get('public_id')).first()
            return obj is not None and (not visible or can_view_presentation(self.request.user, obj))
        return False

    def _valid_favorite(self, path, title, visible=True):
        if not path:
            return False
        title = title.strip()
        if title == 'FREE |':
            return False
        if not (title.startswith('Exhibition | ') or title.startswith('Piece | ')):
            return False
        return self._favorite_path_exists(path, visible=visible)

    def _session_favorites(self):
        favorites = self.request.session.get(SESSION_FAVORITES_KEY, [])
        if not isinstance(favorites, list):
            favorites = []

        cleaned = []
        seen = set()
        for favorite in favorites:
            if not isinstance(favorite, dict):
                continue
            path = str(favorite.get('path', '')).strip()
            title = str(favorite.get('title', '')).strip() or path
            if path in seen or not self._valid_favorite(path, title, visible=False):
                continue
            seen.add(path)
            cleaned.append({'path': path, 'title': title})

        if cleaned != favorites:
            self.request.session[SESSION_FAVORITES_KEY] = cleaned
            self.request.session.modified = True

        return [item for item in cleaned if self._valid_favorite(item['path'], item['title'])]

    def _set_session_favorites(self, favorites):
        self.request.session[SESSION_FAVORITES_KEY] = favorites
        self.request.session.modified = True

    def _favorite_payload(self):
        if not self.request.user.is_authenticated:
            return self._session_favorites()

        payload = []
        stale_ids = []
        for favorite in self.request.user.presentation_favorites.all():
            if not self._valid_favorite(favorite.presentation_path, favorite.presentation_title, visible=False):
                stale_ids.append(favorite.pk)
                continue
            if not self._valid_favorite(favorite.presentation_path, favorite.presentation_title):
                continue
            payload.append({
                'path': favorite.presentation_path,
                'title': favorite.presentation_title,
            })

        if stale_ids:
            PresentationFavorite.objects.filter(user=self.request.user, pk__in=stale_ids).delete()

        return payload

    def get(self, request, *args, **kwargs):
        return JsonResponse({'favorites': self._favorite_payload()})

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

        posted_favorites = payload.get('favorites', [])
        if isinstance(posted_favorites, list):
            session_favorites = []
            session_seen = set()
            for favorite in posted_favorites:
                if not isinstance(favorite, dict):
                    continue
                path = str(favorite.get('path', '')).strip()
                title = str(favorite.get('title', '')).strip() or path
                if not self._valid_favorite(path, title):
                    continue
                if request.user.is_authenticated:
                    PresentationFavorite.objects.update_or_create(
                        user=request.user,
                        presentation_path=path[:255],
                        defaults={'presentation_title': title[:255]},
                    )
                elif path not in session_seen:
                    session_seen.add(path)
                    session_favorites.append({'path': path[:255], 'title': title[:255]})
            if not request.user.is_authenticated:
                self._set_session_favorites(session_favorites)

        current = payload.get('current')
        if isinstance(current, dict):
            path = str(current.get('path', '')).strip()
            title = str(current.get('title', '')).strip() or path
            is_favorite = bool(current.get('favorite'))
            if self._valid_favorite(path, title):
                if is_favorite:
                    if request.user.is_authenticated:
                        PresentationFavorite.objects.update_or_create(
                            user=request.user,
                            presentation_path=path[:255],
                            defaults={'presentation_title': title[:255]},
                        )
                    else:
                        session_favorites = [
                            favorite for favorite in self._session_favorites()
                            if favorite['path'] != path
                        ]
                        session_favorites.append({'path': path[:255], 'title': title[:255]})
                        self._set_session_favorites(session_favorites)
                else:
                    if request.user.is_authenticated:
                        PresentationFavorite.objects.filter(
                            user=request.user,
                            presentation_path=path[:255],
                        ).delete()
                    else:
                        self._set_session_favorites([
                            favorite for favorite in self._session_favorites()
                            if favorite['path'] != path
                        ])

        return JsonResponse({'ok': True, 'favorites': self._favorite_payload()})


class PiecesOverviewView(CuratorRequiredMixin, LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/pieces_overview.html'

    def get_context_data(self, **kwargs):
        return ExhibitionsListView.get_context_data(self, **kwargs)


class StatisticsView(LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/statistics.html'

    def dispatch(self, request, *args, **kwargs):
        if not _can_view_statistics(request.user):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accesses = managed_accesses(self.request.user).select_related(
            'presentation_session__user', 'exhibition__museum', 'piece'
        ).filter(presentation_type__in=TRACKED_PRESENTATION_TYPES).order_by('-id')
        context['accesses'] = _summarize_presentation_accesses(
            accesses,
            group_by_type=False,
            group_by_presentation=False,
        )
        context['exhibition_accesses'] = _summarize_exhibition_accesses(
            accesses.filter(exhibition__isnull=False)
        )
        context['piece_accesses'] = _summarize_presentation_accesses(
            accesses.filter(piece__isnull=False),
            group_by_type=False,
            group_by_presentation=True,
            group_by_visitor=False,
        )
        context['base'] = 'main_app/layout/base.html'
        return context


class StatisticsHistoryView(LoginRequiredMixin, TemplateView):

    template_name = 'main_app/models/statistics_session.html'

    def dispatch(self, request, *args, **kwargs):
        if not _can_view_statistics(request.user):
            raise Http404

        self.history_type = kwargs['history_type']
        if self.history_type == 'user':
            self.user = get_object_or_404(User, pk=kwargs['pk'])
            self.history_label = self.user.username
            self.presentation_sessions = PresentationSession.objects.filter(user=self.user).select_related('user')
            self.presentation_accesses = PresentationAccess.objects.filter(
                presentation_session__in=self.presentation_sessions,
                presentation_type__in=TRACKED_PRESENTATION_TYPES,
            ).select_related('presentation_session__user', 'exhibition', 'piece').order_by('-id')
        elif self.history_type == 'session':
            self.presentation_session = get_object_or_404(
                PresentationSession.objects.select_related('user'),
                pk=kwargs['pk'],
            )
            if self.presentation_session.user_id:
                return redirect(
                    'main_app:statistics-history',
                    history_type='user',
                    pk=self.presentation_session.user_id,
                )
            self.history_label = self.presentation_session.display_session_or_user
            self.presentation_accesses = self.presentation_session.accesses.select_related(
                'presentation_session__user', 'exhibition', 'piece'
            ).filter(presentation_type__in=TRACKED_PRESENTATION_TYPES).order_by('-id')
        else:
            raise Http404

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.presentation_accesses = self.presentation_accesses.filter(pk__in=managed_accesses(self.request.user))
        if not is_administrator(self.request.user) and not self.presentation_accesses.exists():
            raise Http404
        context['history_label'] = self.history_label
        context['history_type'] = self.history_type
        context['accesses'] = _summarize_presentation_accesses(self.presentation_accesses, group_by_type=True)
        context['user_log'] = self.presentation_accesses.order_by('last_accessed_at', 'id')
        context['base'] = 'main_app/layout/base.html'
        return context


class StatisticsPresentationView(LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/statistics_presentation.html'
#to show each session only once we need to group accesses by presentation type and session, so we can show the most recent access for each session in the list, and then link to the session history for more details. This way we avoid showing multiple entries for the same session if a user accessed the same presentation multiple times.

    def dispatch(self, request, *args, **kwargs):
        if not _can_view_statistics(request.user):
            raise Http404

        self.presentation_type = kwargs['presentation_type']
        if self.presentation_type == 'exhibition':
            self.presentation = get_object_or_404(managed_exhibitions(request.user), pk=kwargs['pk'])
            self.exhibition_presentation_accesses = PresentationAccess.objects.filter(
                exhibition=self.presentation,
                piece__isnull=True,
                presentation_type__in=TRACKED_PRESENTATION_TYPES,
            ).select_related('presentation_session__user', 'exhibition', 'piece').order_by('-id')
            self.piece_presentation_accesses = PresentationAccess.objects.filter(
                exhibition=self.presentation,
                piece__isnull=False,
                presentation_type__in=TRACKED_PRESENTATION_TYPES,
            ).select_related('presentation_session__user', 'exhibition', 'piece').order_by('-id')
            self.presentation_accesses = (
                self.exhibition_presentation_accesses | self.piece_presentation_accesses
            ).order_by('-id')
            self.presentation_label = self.presentation.title
        elif self.presentation_type == 'piece':
            self.presentation = get_object_or_404(managed_pieces(request.user), pk=kwargs['pk'])
            self.presentation_accesses = PresentationAccess.objects.filter(
                piece=self.presentation,
                presentation_type__in=TRACKED_PRESENTATION_TYPES,
            ).select_related('presentation_session__user', 'exhibition', 'piece').order_by('-id')
            self.presentation_label = str(self.presentation)
        else:
            raise Http404

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presentation_label'] = self.presentation_label
        context['presentation_type'] = self.presentation_type
        if self.presentation_type == 'exhibition':
            context['piece_accesses'] = _summarize_presentation_accesses(
                self.piece_presentation_accesses,
                group_by_type=False,
                group_by_presentation=True,
                group_by_visitor=False,
            )
            context['exhibition_presentation_accesses'] = _summarize_presentation_accesses(
                self.exhibition_presentation_accesses,
                group_by_type=True,
                group_by_presentation=False,
                group_by_visitor=False,
            )
            context['exhibition_log'] = self.presentation_accesses.order_by('last_accessed_at', 'id')
        else:
            context['accesses'] = _summarize_presentation_accesses(self.presentation_accesses, group_by_type=True)
            context['piece_log'] = self.presentation_accesses.order_by('last_accessed_at', 'id')
        context['base'] = 'main_app/layout/base.html'
        return context

################ VIEWS for the Thing Model
#### create list of things
# List1 - Create a Table
class ThingsTable(Table):
    # List2 - define the template for the button on each line
    action = TemplateColumn(template_name='main_app/models/things_table_link.html')

    class Meta:
        model = Thing
        fields = ['user', 'id', 'name', 'created_at']


# List3 - Create list view
class ThingsListView(SingleTableView):
    template_name = 'main_app/models/things_table.html'
    table_class = ThingsTable




 #   def get_queryset(self):
  #      if self.request.user.is_superuser:
  #          return Thing.objects.all()
   #     if self.request.user.is_authenticated:
     #       return Thing.objects.filter(user=self.request.user)
      #  return Thing.objects.all()

# List4 - Create the corresponding template (things_table)
# List5 - Create the url for this view
# List6 - Create add the link into the correct temaple (e.g. menu)



#### create a thing page
# Thing1 - Define the Thing View
class ThingView(LoginRequiredMixin, TemplateView):
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['thing'] = Thing.objects.get(pk=kwargs['pk'])
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/thing.html']
# Thing2 -  Create the corresponding template (thing)
# Thing3 -  Create the corresponding url ()


class ThingForm(ModelForm):
    class Meta:
        model = Thing
        fields = "__all__"


class ThingCreateView(LoginRequiredMixin, CreateView):
    model = Thing
    fields = ['name', 'config']
    template_name = 'main_app/models/thing_edit.html'
    success_url = reverse_lazy('main_app:things-list')

    def form_valid(self, form):
        ipw = IpWare()
        meta = self.request.META
        ip, trusted_route = ipw.get_client_ip(meta)
        remote_addr = str(ip)
        form.fields['client_ip_address']= remote_addr
        form.fields['user_id']=self.request.user.id
        try:
            url = "https://api.ipgeolocation.io/ipgeo?apiKey=%s&ip=%s"%(settings.IPGEOLOCATION_API_KEY, remote_addr)
            response = requests.request("GET", url)
            country = Country.objects.get(iso=response.json()['country_code2'])
            form.fields['client_country']=country
            form.fields['client_city']=response.json()['city']
            form.fields['client_organization']=response.json()['organization']
            form.fields['client_lat']= response.json()['latitude']
            form.fields['client_long']= response.json()['longitude']
        except:
            pass


        form.instance.user = self.request.user
        return super().form_valid(form)
    

class ThingUpdateView(LoginRequiredMixin, UpdateView):
    model = Thing
    fields = ['name', 'config']
    template_name = 'main_app/models/thing_edit.html'
    success_url = reverse_lazy('main_app:things-list')




#class SpatialThingsTable(Table):
#    action = TemplateColumn(template_name='main_app/models/spatial_things_table_link.html')
#
#    class Meta:
#        model = SpatialThing
#        fields = ['user', 'id', 'name', 'created_at', 'points', 'limits']

#class SpatialThingsListView(LoginRequiredMixin,SingleTableView):
#    template_name = 'main_app/models/spatial_things_table.html'
#    table_class = SpatialThingsTable
#
#    def get_queryset(self):
#        return SpatialThing.objects.filter(user=self.request.user)

#class SpatialThingView(LoginRequiredMixin, TemplateView):
#    def get_context_data(self, **kwargs):
#        context = super().get_context_data(**kwargs)
#        context['spatialthing'] = SpatialThing.objects.get(pk=kwargs['pk'])
#        context['base'] = "main_app/layout/base.html"
#        return context

    def get_template_names(self):
        return ['main_app/models/spatial_thing.html']


LEAFLET_WIDGET_ATTRS = {
    'map_height': '500px',
    'map_width': '100%',
    'display_raw': 'true',
    'map_srid': 4326,
}
#class SpatialThingEditForm(forms.ModelForm):
#    class Meta:
#        model = SpatialThing
#        fields = ['name', 'points', 'limits']
#        widgets = {'points': LeafletWidget(attrs=LEAFLET_WIDGET_ATTRS), 
#            'limits': LeafletWidget(attrs=LEAFLET_WIDGET_ATTRS), 
#        }

#class SpatialThingUpdateView(LoginRequiredMixin, UpdateView):
#    form_class = SpatialThingEditForm
#    model = SpatialThing
#    template_name = 'main_app/models/spatial_thing_edit.html'
#    success_url = reverse_lazy('main_app:spatial-things-list')


#class SpatialThingCreateView(LoginRequiredMixin, CreateView):
#    form_class = SpatialThingEditForm
#    model = SpatialThing
#    template_name = 'main_app/models/spatial_thing_edit.html'
#    success_url = reverse_lazy('main_app:spatial-things-list')

#    def form_valid(self, form):
#        ipw = IpWare()
#        meta = self.request.META
#        ip, trusted_route = ipw.get_client_ip(meta)
#        remote_addr = str(ip)
#        form.fields['client_ip_address']= remote_addr
#        form.fields['user_id']=self.request.user.id

#        form.instance.user = self.request.user
#        return super().form_valid(form)


#class SpatialThingUpdateView(LoginRequiredMixin, UpdateView):
#    form_class = SpatialThingEditForm
#    model = SpatialThing
#    template_name = 'main_app/models/spatial_thing_edit.html'
#    success_url = reverse_lazy('main_app:spatial-things-list')


class VisitorHistoryView(TemplateView):
    template_name = 'main_app/models/visitor_history.html'

    def get_context_data(self, **kwargs):
        from main_app.visitor import visitor_history
        context = super().get_context_data(**kwargs)
        context['visitor_history'] = visitor_history(self.request)
        return context


class PublicationView(CuratorRequiredMixin, View):
    def post(self, request, kind, pk):
        obj = get_object_or_404(managed_exhibitions(request.user) if kind == 'exhibition' else managed_pieces(request.user), pk=pk)
        if not obj.slideshow_page_id:
            raise Http404('No presentation root exists yet.')
        action = request.POST.get('action')
        if action not in {'publish', 'unpublish'}:
            return JsonResponse({'error': 'Invalid publication action'}, status=400)
        with transaction.atomic():
            pages = obj.slideshow_page.get_descendants(inclusive=True).specific().order_by('depth', 'path')
            for page in pages:
                if action == 'publish':
                    revision = page.get_latest_revision() or page.save_revision(user=request.user)
                    revision.publish(user=request.user, skip_permission_checks=True)
                elif page.live:
                    page.unpublish(user=request.user)
        return redirect('main_app:' + kind + '-update', pk=obj.pk)
