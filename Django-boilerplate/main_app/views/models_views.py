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


#return 404 if object does not exist or user does not have permissions to see it
from django.shortcuts import get_object_or_404

class ExhibitionsTable(Table):
    action = TemplateColumn(template_name='main_app/models/exhibitions_table_link.html')

    class Meta:
        model = Exhibition
        fields = ['name', 'description']


class ExhibitionsListView(LoginRequiredMixin, SingleTableView):
    template_name = 'main_app/models/exhibitions_table.html'
    table_class = ExhibitionsTable

    def get_queryset(self):
        return Exhibition.objects.filter(admins=self.request.user)


class ExhibitionView(LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        expo = get_object_or_404(Exhibition, pk=kwargs['pk'])
        context['exhibition'] = expo
        #context['pieces'] = expo.pieces.all()
        context['base'] = "main_app/layout/base.html"
        return context

    def get_template_names(self):
        return ['main_app/models/exhibition.html']


class ExhibitionForm(ModelForm):
    class Meta:
        model = Exhibition
        fields = ['name', 'description']


class ExhibitionCreateView(LoginRequiredMixin, CreateView):
    model = Exhibition
    form_class = ExhibitionForm
    template_name = 'main_app/models/exhibition_edit.html'

    def get_success_url(self):
        return reverse('main_app:exhibitions-list')

    def form_valid(self, form):
        resp = super().form_valid(form)
        self.object.admins.add(self.request.user)
        return resp


class ExhibitionUpdateView(LoginRequiredMixin, UpdateView):
    model = Exhibition
    form_class = ExhibitionForm
    template_name = 'main_app/models/exhibition_edit.html'

    def get_success_url(self):
        return reverse('main_app:exhibition', kwargs={'pk': self.object.pk})



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

