from django.utils.translation import gettext_lazy as _
from django.urls import reverse_lazy, reverse
from django.views.generic import TemplateView, DetailView
from django.forms import ModelForm
from django import forms

from main_app.views.api import ExecutionSerializer
from main_app.models import *

from django_tables2 import DateTimeColumn, Table, TemplateColumn, Column, RequestConfig
from django_tables2.views import SingleTableView
from django.views.generic.base import RedirectView
from django.views.generic.edit import FormView
from django.views.generic.edit import CreateView, UpdateView, DeleteView

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.http import Http404
from django.urls.exceptions import NoReverseMatch
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from python_ipware import IpWare
from leaflet.forms.widgets import LeafletWidget
from root_files import settings
from django.utils.text import slugify
import requests
from django.contrib.gis.db import models as geo_models
from wagtail.models import Page




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


def _can_manage_on_site_presentation(user, exhibition):
    if not user.is_authenticated or exhibition is None:
        return False
    if user.is_superuser or user.is_staff:
        return True

    profile = getattr(user, 'profile', None)
    if getattr(profile, 'type', None) not in {'t', 'a'}:
        return False

    return exhibition.admins.filter(pk=user.pk).exists()


def _can_view_statistics(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True

    profile = getattr(user, 'profile', None)
    return getattr(profile, 'type', None) in {'t', 'a'}


def _ensure_presentation_session(request):
    if not request.session.session_key:
        request.session.create()

    # Create a new PresentationSession for this visit (one row per visit)
    presentation_session = PresentationSession.objects.create(
        session_key=request.session.session_key,
        user=request.user if request.user.is_authenticated else None,
    )
    return presentation_session


def _log_presentation_access(request, presentation_type, title, exhibition=None, piece=None):
    presentation_session = _ensure_presentation_session(request)
    PresentationAccess.objects.create(
        presentation_session=presentation_session,
        presentation_type=presentation_type,
        presentation_title=title,
        presentation_path=request.path,
        exhibition=exhibition,
        piece=piece,
    )


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


def _presentation_context(slideshow_page, presentation_type):
    presentation_pages = _presentation_pages(
        _ensure_presentation_folders(slideshow_page).get(presentation_type)
    )

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

    def cleaned_attribute_values(self):
        values = []
        for index, attribute_name in enumerate(self.attribute_definitions):
            field_name = f'attribute_{index}'
            values.append((attribute_name, self.cleaned_data.get(field_name, '').strip()))
        return values


class ExhibitionsListView(LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/pieces_overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        exhibitions = Exhibition.objects.filter(admins=self.request.user).annotate(
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


class ExhibitionView(LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        expo = get_object_or_404(Exhibition, pk=kwargs['pk'])
        context['exhibition'] = expo
        context['pieces'] = expo.pieces.all()
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/exhibition.html']


class ExhibitionForm(ModelForm):
    class Meta:
        model = Exhibition
        fields = ['title', 'description']



  #  def get_self.object success_url(self):
   #     new_exh_page = ExhibitionPage()
    ##   new_exh_page.description = self.object.description
     #   new_exh_page.save()        
      #  self.object.wag_slides = new_exh_page
#        self.object.save()
       # return reverse('main_app:exhibitions-list')


class ExhibitionCreateView(LoginRequiredMixin, CreateView):
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
        self._get_or_create_child(
            exhibition_page,
            ExhibitionUserDevicePage,
            title="User Device",
            slug="user_device",
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
            resp = super().form_valid(form)
            self.object.admins.add(self.request.user)
            self._ensure_exhibition_slideshow_tree()
            return resp


class ExhibitionUpdateView(LoginRequiredMixin, UpdateView):
    model = Exhibition
    form_class = ExhibitionForm
    template_name = 'main_app/models/exhibition_edit.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        _ensure_default_name_attribute(self.object)
        
        attributes = _ordered_attributes(self.object)
        has_custom_attributes = len(attributes) > 0

        # Helper that wraps cell values and provides rich comparison for sorting
        import re

        class _SortableValue:
            def __init__(self, raw):
                self.raw = '' if raw is None else str(raw)
                # attempt to parse numeric value, supporting scientific notation
                text = self.raw.replace(',', '').strip()
                # match a numeric pattern with optional decimal and exponent
                m = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', text)
                if m:
                    s = m.group(0)
                    try:
                        # parse as float (covers scientific notation)
                        self.num = float(s)
                        # if it's an integer-like value, keep it as int for cleaner comparisons
                        if self.num.is_integer():
                            self.num = int(self.num)
                    except Exception:
                        self.num = None
                else:
                    self.num = None

            def __lt__(self, other):
                if not isinstance(other, _SortableValue):
                    other = _SortableValue(other)
                if self.num is not None and other.num is not None:
                    return self.num < other.num
                if self.num is not None and other.num is None:
                    return True
                if self.num is None and other.num is not None:
                    return False
                return self.raw.lower() < other.raw.lower()

            def __eq__(self, other):
                if not isinstance(other, _SortableValue):
                    other = _SortableValue(other)
                return (self.num == other.num) and (self.raw == other.raw)

            def __str__(self):
                return self.raw

        attrs = {
            'date_created': DateTimeColumn(verbose_name=_('Date created'), format="Y-m-d H:i")
        }

        # create a Column for each attribute (accessor will use the dict key)
        for attribute in attributes:
            key = attribute.lower()
            attrs[key] = Column(verbose_name=attribute)

        attrs['action'] = TemplateColumn(
            template_name='main_app/models/pieces_table_link.html',
            orderable=False,
            verbose_name=_('Actions')
        )

        DynamicPiecesTable = type('DynamicPiecesTable', (Table,), attrs)

        pieces = self.object.pieces.all().order_by('-date_created')
        table_data = []
        for piece in pieces:
            value_map = _piece_value_map(piece)
            row = {'pk': piece.pk, 'date_created': piece.date_created}
            for attribute in attributes:
                raw_val = value_map.get(attribute.lower()) or ''
                row[attribute.lower()] = _SortableValue(raw_val)
            table_data.append(row)

        table = DynamicPiecesTable(table_data)
        RequestConfig(self.request).configure(table)

        context['table'] = table
        context['has_piece_attributes'] = has_custom_attributes
        context['exhibition_presentations'] = _presentation_links(self.object.slideshow_page)
        return context

    def get_success_url(self):
        return reverse('main_app:exhibition', kwargs={'pk': self.object.pk})


class ExhibitionDeleteView(LoginRequiredMixin, DeleteView):
    model = Exhibition
    template_name = 'main_app/models/exhibition_confirm_delete.html'
    
    def get_object(self):
        obj = super().get_object()
        # Ensure user is an admin of this exhibition
        if not obj.admins.filter(pk=self.request.user.pk).exists():
            raise Http404
        return obj
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        
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

    def dispatch(self, request, *args, **kwargs):
        self.presentation_type = kwargs['presentation_type']
        self.exhibition = get_object_or_404(
            Exhibition.objects.select_related('slideshow_page'),
            pk=kwargs['pk'],
        )
        if self.presentation_type not in {'on_site', 'user_device'}:
            raise Http404

        if self.presentation_type == 'on_site':
            if not _can_manage_on_site_presentation(request.user, self.exhibition):
                raise Http404
        _log_presentation_access(
            request,
            f'exhibition_{self.presentation_type}',
            self.exhibition.title,
            exhibition=self.exhibition,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exhibition'] = self.exhibition
        context.update(_presentation_context(self.exhibition.slideshow_page, self.presentation_type))
        context['is_user_device_presentation'] = self.presentation_type == 'user_device'
        return context
    
class ExhibitionAddPiecesView(LoginRequiredMixin, RedirectView):
    def get_redirect_url(self, *args, **kwargs):
        return f"{reverse('main_app:piece-create')}?exhibition_id={kwargs['pk']}"


class ExhibitionAttributesCreateView(LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/exhibition_attributes_edit.html'

    def dispatch(self, request, *args, **kwargs):
        self.exhibition = get_object_or_404(Exhibition, pk=kwargs['pk'], admins=request.user)
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


class PieceView(LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        piece = get_object_or_404(Piece, pk=kwargs['pk'], exhibition__admins=self.request.user)
        ordered_attributes = _ordered_attributes(piece.exhibition)
        value_map = _piece_value_map(piece)
        context['piece'] = piece
        context['piece_name'] = str(piece)
        context['attribute_rows'] = [
            (attribute, value_map.get(attribute.lower(), ''))
            for attribute in ordered_attributes
        ]
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/piece.html']


class PieceCreateView(LoginRequiredMixin, FormView):
    form_class = PieceForm
    template_name = 'main_app/models/piece_edit.html'

    def dispatch(self, request, *args, **kwargs):
        exhibition_id = kwargs.get('exhibition_id') or request.GET.get('exhibition_id')
        if not exhibition_id:
            raise Http404
        self.exhibition = get_object_or_404(Exhibition, pk=exhibition_id, admins=request.user)
        self.attribute_definitions = _ordered_attributes(self.exhibition)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['attribute_definitions'] = self.attribute_definitions
        kwargs['include_default_name'] = len(self.attribute_definitions) == 0
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
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
        ExhibitionCreateView._get_or_create_child(
            piece_page,
            PieceUserDevicePage,
            title="User Device",
            slug="user_device",
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


class PieceUpdateView(LoginRequiredMixin, FormView):
    form_class = PieceForm
    template_name = 'main_app/models/piece_edit.html'

    def get_queryset(self):
        return Piece.objects.filter(exhibition__admins=self.request.user)

    def dispatch(self, request, *args, **kwargs):
        self.object = get_object_or_404(self.get_queryset(), pk=kwargs['pk'])
        self.exhibition = self.object.exhibition
        self.attribute_definitions = _ordered_attributes(self.exhibition)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial_values = _piece_value_map(self.object)
        kwargs['attribute_definitions'] = self.attribute_definitions
        kwargs['initial_values'] = initial_values
        return kwargs

    def form_valid(self, form):
        self.object.attributes = [
            {'name': attribute_name, 'value': value}
            for attribute_name, value in form.cleaned_attribute_values()
        ]
        self.object.save(update_fields=['attributes'])
        _ensure_piece_name_value(self.object)
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['exhibition'] = self.object.exhibition
        context['has_piece_attributes'] = len(self.attribute_definitions) > 0
        context['piece_presentations'] = _presentation_links(self.object.slideshow_page)
        context['piece'] = self.object
        return context

    def get_success_url(self):
        return reverse('main_app:exhibition-update', kwargs={'pk': self.object.exhibition.pk})


class PiecePresentationView(TemplateView):
    template_name = 'main_app/models/piece_presentation.html'

    def dispatch(self, request, *args, **kwargs):
        self.presentation_type = kwargs['presentation_type']
        self.piece = get_object_or_404(
            Piece.objects.select_related('slideshow_page', 'exhibition'),
            pk=kwargs['pk'],
        )
        if self.presentation_type not in {'on_site', 'user_device'}:
            raise Http404

        if self.presentation_type == 'on_site':
            if not _can_manage_on_site_presentation(request.user, self.piece.exhibition):
                raise Http404
        _log_presentation_access(
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
        context.update(_presentation_context(self.piece.slideshow_page, self.presentation_type))
        context['is_user_device_presentation'] = self.presentation_type == 'user_device'
        return context


class PiecesOverviewView(LoginRequiredMixin, TemplateView):
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
        sessions = PresentationSession.objects.select_related('user').annotate(
            access_count=Count('accesses')
        ).order_by('-created_at')
        context['sessions'] = sessions
        context['base'] = 'main_app/layout/base.html'
        return context


class StatisticsSessionView(LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/statistics_session.html'

    def dispatch(self, request, *args, **kwargs):
        if not _can_view_statistics(request.user):
            raise Http404

        self.presentation_session = get_object_or_404(
            PresentationSession.objects.select_related('user'),
            pk=kwargs['pk'],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accesses = self.presentation_session.accesses.select_related('exhibition', 'piece')
        context['presentation_session'] = self.presentation_session
        context['accesses'] = accesses
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

