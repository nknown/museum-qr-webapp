from django.utils.translation import gettext_lazy as _
from django.urls import reverse_lazy
from django.views.generic import TemplateView, TemplateView, DetailView

from main_app.views.api import ExecutionSerializer
from main_app.models import *

from django_tables2 import Table, TemplateColumn, Column
from django_tables2.views import SingleTableView
from django.views.generic.base import RedirectView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.http import Http404
from python_ipware import IpWare

class IndexView(TemplateView):
    template_name='main_app/layout/index.html'
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["n_executions"] = len(Execution.objects.filter(status='F'))
        context["n_users"] = len(User.objects.all())
        context["n_countries"] = len(Execution.objects.all().values_list('client_country').distinct())
        
        return context
# EXPERIMENT CONTROL & EXECUTIONS





class ExecutionView(LoginRequiredMixin, TemplateView):
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.execution = Execution.objects.get(pk=kwargs['pk'])
        context['execution_json'] = ExecutionSerializer(self.execution).data
        context['base'] = "main_app/layout/base.html"

        return context

    def get_template_names(self):
        return ['main_app/experiments/' + self.execution.apparatus.apparatus_type.slug + '.html']


class ExecutionStrippedView(ExecutionView):
    def get_context_data(self, **kwargs):
        context = ExecutionView.get_context_data(self, **kwargs)
        context['base'] = "main_app/base_stripped.html"
        context['STRIPPED'] = True
        return context

class ApparatusVideoView(LoginRequiredMixin, DetailView):
    template_name = 'main_app/apparatus_video.html'
    def get_queryset(self):
        print(self.kwargs['pk'])
        return Apparatus.objects.filter(id=self.kwargs['pk'])
        #.get(pk=self.kwargs['pk'])

class CreateExecutionView(LoginRequiredMixin, TemplateView):    
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['base'] = "main_app/layout/base.html"
        
        apparatus_id = kwargs['apparatus_id']
        protocol_id = kwargs['protocol_id']
        

        self.apparatus = get_object_or_404(Apparatus, pk=apparatus_id)

        if not self.apparatus.protocols.filter(id=protocol_id).exists():
            raise Http404("Apparatus type does implement such protocol")

        context['execution_json'] = {}
        context['apparatus'] = self.apparatus
        context['protocol'] = Protocol.objects.get(pk=protocol_id)
        context['final_result'] = {}
        return context

    def get_template_names(self):
        return ['main_app/experiments/' + self.apparatus.apparatus_type.slug + '.html']

class CreateExecutionStrippedView(CreateExecutionView):
    def get_context_data(self, **kwargs):
        context = CreateExecutionView.get_context_data(self, **kwargs)
        context['base'] = "main_app/base_stripped.html"
        context['STRIPPED'] = True
        return context


class ExecutionsTable(Table):
    action = TemplateColumn(template_name='main_app/execution_link.html')

    class Meta:
        model = Execution
        fields = ['id', 'apparatus', 'name', 'protocol', 'status', 'order', 'start', 'end']

class ExecutionsListView(LoginRequiredMixin,SingleTableView):
    template_name = 'main_app/executions.html'
    table_class = ExecutionsTable

    def get_queryset(self):
        return Execution.objects.filter(user=self.request.user, status__in =  self.status_filter)

class ExecutionsConfiguredListView(ExecutionsListView):
    status_filter = ['C','N', 'Q', 'R']

class ExecutionsFinishedListView(ExecutionsListView):
    status_filter = ['E',  'F', 'A', 'T']
        

