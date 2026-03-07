from django.utils.translation import gettext_lazy as _
from django.urls import reverse_lazy, reverse
from django.views.generic import TemplateView, TemplateView, DetailView
from django.forms import ModelForm
from django import forms

from main_app.views.api import ExecutionSerializer
from main_app.models import *

from django_tables2 import Table, TemplateColumn, Column
from django_tables2.views import SingleTableView
from django.views.generic.base import RedirectView
from django.views.generic.edit import FormView
from django.views.generic.edit import CreateView, UpdateView

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.http import Http404
from python_ipware import IpWare
from leaflet.forms.widgets import LeafletWidget
from root_files import settings
import requests
from django.contrib.gis.db import models as geo_models

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
class ThingsListView(LoginRequiredMixin,SingleTableView):
    template_name = 'main_app/models/things_table.html'
    table_class = ThingsTable

    def get_queryset(self):
        return Thing.objects.filter(user=self.request.user)

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




class SpatialThingsTable(Table):
    action = TemplateColumn(template_name='main_app/models/spatial_things_table_link.html')

    class Meta:
        model = SpatialThing
        fields = ['user', 'id', 'name', 'created_at', 'points', 'limits']

class SpatialThingsListView(LoginRequiredMixin,SingleTableView):
    template_name = 'main_app/models/spatial_things_table.html'
    table_class = SpatialThingsTable

    def get_queryset(self):
        return SpatialThing.objects.filter(user=self.request.user)

class SpatialThingView(LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['spatialthing'] = SpatialThing.objects.get(pk=kwargs['pk'])
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/spatial_thing.html']


LEAFLET_WIDGET_ATTRS = {
    'map_height': '500px',
    'map_width': '100%',
    'display_raw': 'true',
    'map_srid': 4326,
}
class SpatialThingEditForm(forms.ModelForm):
    class Meta:
        model = SpatialThing
        fields = ['name', 'points', 'limits']
        widgets = {'points': LeafletWidget(attrs=LEAFLET_WIDGET_ATTRS), 
            'limits': LeafletWidget(attrs=LEAFLET_WIDGET_ATTRS), 
        }

class SpatialThingUpdateView(LoginRequiredMixin, UpdateView):
    form_class = SpatialThingEditForm
    model = SpatialThing
    template_name = 'main_app/models/spatial_thing_edit.html'
    success_url = reverse_lazy('main_app:spatial-things-list')


class SpatialThingCreateView(LoginRequiredMixin, CreateView):
    form_class = SpatialThingEditForm
    model = SpatialThing
    template_name = 'main_app/models/spatial_thing_edit.html'
    success_url = reverse_lazy('main_app:spatial-things-list')

    def form_valid(self, form):
        ipw = IpWare()
        meta = self.request.META
        ip, trusted_route = ipw.get_client_ip(meta)
        remote_addr = str(ip)
        form.fields['client_ip_address']= remote_addr
        form.fields['user_id']=self.request.user.id

        form.instance.user = self.request.user
        return super().form_valid(form)


class SpatialThingUpdateView(LoginRequiredMixin, UpdateView):
    form_class = SpatialThingEditForm
    model = SpatialThing
    template_name = 'main_app/models/spatial_thing_edit.html'
    success_url = reverse_lazy('main_app:spatial-things-list')


# ----------------------- exposition / piece / slide code -----------------------

from django.shortcuts import get_object_or_404

class ExpositionsTable(Table):
    action = TemplateColumn(template_name='main_app/models/expositions_table_link.html')

    class Meta:
        model = Exposition
        fields = ['title', 'created_at']


class ExpositionsListView(LoginRequiredMixin, SingleTableView):
    template_name = 'main_app/models/expositions_table.html'
    table_class = ExpositionsTable

    def get_queryset(self):
        return Exposition.objects.filter(admins=self.request.user)


class ExpositionView(LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        expo = get_object_or_404(Exposition, pk=kwargs['pk'])
        context['exposition'] = expo
        context['pieces'] = expo.pieces.all()
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/exposition.html']


class ExpositionForm(ModelForm):
    class Meta:
        model = Exposition
        fields = ['title', 'description', 'admins']


class ExpositionCreateView(LoginRequiredMixin, CreateView):
    model = Exposition
    form_class = ExpositionForm
    template_name = 'main_app/models/exposition_edit.html'

    def get_success_url(self):
        return reverse('main_app:expositions-list')

    def form_valid(self, form):
        resp = super().form_valid(form)
        self.object.admins.add(self.request.user)
        return resp


class ExpositionUpdateView(LoginRequiredMixin, UpdateView):
    model = Exposition
    form_class = ExpositionForm
    template_name = 'main_app/models/exposition_edit.html'

    def get_success_url(self):
        return reverse('main_app:exposition', kwargs={'pk': self.object.pk})


# pieces
class PiecesTable(Table):
    action = TemplateColumn(template_name='main_app/models/pieces_table_link.html')

    class Meta:
        model = Piece
        fields = ['title', 'qr_slug', 'created_at']


class PiecesListView(LoginRequiredMixin, SingleTableView):
    template_name = 'main_app/models/pieces_table.html'
    table_class = PiecesTable

    def get_queryset(self):
        expo_pk = self.kwargs.get('expo_pk')
        if expo_pk:
            expo = get_object_or_404(Exposition, pk=expo_pk)
            return expo.pieces.all()
        return Piece.objects.all()


class PieceView(LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        piece = get_object_or_404(Piece, pk=kwargs['pk'])
        context['piece'] = piece
        context['pages'] = piece.wagtail_pages.all() if hasattr(piece, 'wagtail_pages') else []
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/piece.html']


class PieceForm(ModelForm):
    class Meta:
        model = Piece
        fields = ['title', 'description', 'qr_slug']


class PieceCreateView(LoginRequiredMixin, CreateView):
    model = Piece
    form_class = PieceForm
    template_name = 'main_app/models/piece_edit.html'

    def form_valid(self, form):
        resp = super().form_valid(form)
        expo_pk = self.kwargs.get('expo_pk')
        if expo_pk:
            expo = get_object_or_404(Exposition, pk=expo_pk)
            expo.pieces.add(self.object)
        return resp

    def get_success_url(self):
        expo_pk = self.kwargs.get('expo_pk')
        if expo_pk:
            return reverse('main_app:exposition', kwargs={'pk': expo_pk})
        return reverse('main_app:pieces-list')


class PieceUpdateView(LoginRequiredMixin, UpdateView):
    model = Piece
    form_class = PieceForm
    template_name = 'main_app/models/piece_edit.html'

    def get_success_url(self):
        return reverse('main_app:piece', kwargs={'pk': self.object.pk})


# slides
class SlidesTable(Table):
    action = TemplateColumn(template_name='main_app/models/slides_table_link.html')

    class Meta:
        model = Slide
        fields = ['piece', 'order', 'title']


class SlidesListView(LoginRequiredMixin, SingleTableView):
    template_name = 'main_app/models/slides_table.html'
    table_class = SlidesTable

    def get_queryset(self):
        return Slide.objects.all()


# utility pages
class VisitsView(LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/visits.html'


class StatisticsView(LoginRequiredMixin, TemplateView):
    template_name = 'main_app/models/statistics.html'


class AdminRedirectView(RedirectView):
    pattern_name = 'admin:index'

