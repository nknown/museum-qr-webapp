from main_app.models import *
from main_app.views.permissions import ApparatusOnlyAccess


from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView, TemplateView, DetailView


from rest_framework import generics, serializers, views
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

class ApparatusMapView(LoginRequiredMixin, DetailView):
    template_name = 'apparatus_map.html'
    def get_queryset(self):
        print(self.kwargs['pk'])
        return Apparatus.objects.filter(id=self.kwargs['pk'])
        #.get(pk=self.kwargs['pk'])



class ExecutionLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields = ['id','name', 'apparatus', 'status', 'client_long', 'client_lat', 'order']
        read_only_fields = ('id','name', 'apparatus', 'status', 'client_long', 'client_lat', 'order')

class ApparatusExecutionsQueue(LoginRequiredMixin, generics.ListAPIView):
    permission_classes = [ApparatusOnlyAccess]
    serializer_class = ExecutionLocationSerializer
    def get_queryset(self):
        return Execution.objects.filter(apparatus_id=self.kwargs['pk'], status__in='QR') #status__in='QR',



class ApparatusGetFinishedExecutions(LoginRequiredMixin, generics.ListAPIView):
    permission_classes = [ApparatusOnlyAccess]
    serializer_class = ExecutionLocationSerializer
    def get_queryset(self):
        return Execution.objects.filter(apparatus_id=self.kwargs['pk'], status__in='F') #status__in='QR',
    
