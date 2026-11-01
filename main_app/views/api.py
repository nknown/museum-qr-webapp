from rest_framework import generics, serializers, views
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from main_app.models import *
import json
import decimal
from jsonschema import validate, ValidationError as JSONValidationError
from MIYP import settings
from django.shortcuts import get_object_or_404

from main_app.views.permissions import ApparatusOnlyAccess

import requests
from countries_plus.models import Country
from python_ipware import IpWare






class ExecutionSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Execution
        fields = ['id','name', 'apparatus', 'protocol', 'config', 'status', 'queue_time', 'order', 'start', 'end']
        read_only_fields = ('id', 'apparatus', 'protocol', 'status', 'queue_time',  'order', 'start', 'end')

class ExecutionCreateSerializer(serializers.ModelSerializer):
    def validate(self, data):
        data = super().validate(data)
        adjusted_schema = json.loads(json.dumps(data['protocol'].config), parse_float=decimal.Decimal)
        instance = data['config'] if 'config' in data else {}
        adjusted_instance = json.loads(json.dumps(instance), parse_float=decimal.Decimal)
        
        try:
            validate(instance = adjusted_instance, schema = adjusted_schema)
        except JSONValidationError as e:
            raise serializers.ValidationError(e.message)


        ### GEt country from address
        ipw = IpWare()
        meta = self.context['request'].META

        ip, trusted_route = ipw.get_client_ip(meta)
        try:
            #remote_addr = "192.124.249.9"
            remote_addr = str(ip)
            data['client_ip_address']= remote_addr
            url = "https://api.ipgeolocation.io/ipgeo?apiKey=%s&ip=%s"%(settings.IPGEOLOCATION_API_KEY, remote_addr)
            response = requests.request("GET", url)
            country = Country.objects.get(iso=response.json()['country_code2'])
            data['client_country']=country
            data['client_city']=response.json()['city']
            data['client_organization']=response.json()['organization']
            data['client_lat']= response.json()['latitude']
            data['client_long']= response.json()['longitude']
        except:
            pass
        return data  

    class Meta:
        model = Execution
        fields = ['id', 'name','apparatus', 'protocol', 'config']

class ExecutionUpdateSerializer(serializers.ModelSerializer):

    def validate(self, data):
        data = super().validate(data)
            
        if not self.instance.status in ['C','N']:
            raise serializers.ValidationError("Can only update configuration of not enqueued executions.")
        
        try:
            validate(instance = data['config'] if 'config' in data else {}, schema = self.instance.protocol.config)
        except JSONValidationError as e:
            raise serializers.ValidationError(e.message)
            
        return data  

    class Meta:
        model = Execution
        fields = ['config']
        


class ExecutionConfigure(generics.CreateAPIView):
    """
    Configures an execution of experiment. 
    
    You must supply valid apparatus and protocol ids. The config is validated against JSON schema of the protocol.
    """
    serializer_class = ExecutionCreateSerializer
    queryset = Execution.objects.all()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, status = 'C')

class ExecutionRetrieveUpdateDestroy(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieves, updates or deletes a given execution. 
    
    The config is validated against JSON schema of the protocol.
    Update and delete are only possible for executions, that have not been enqueued (are in configured state - C).
    It is only possble to update config of the execution.
    """
    queryset = Execution.objects.all()
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return ExecutionSerializer
        return ExecutionUpdateSerializer

    def perform_update(self, serializer):
        serializer.save(status = 'C')
        
class ExecutionUpdateNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields = ['name']        
        
class ExecutionUpdateName(generics.UpdateAPIView):
    """
    Changes the name of the execution.

    It's possible to change the name of the execution in any state.
    """
    queryset = Execution.objects.all()
    lookup_field = 'id'
    serializer_class = ExecutionUpdateNameSerializer

class ExecutionStart(views.APIView):
    """
    Starts a configured execution. 
    
    Status is changed to Q - "Queued".
    """
    def put(self, *args, **kwargs):
        try:
            execution = Execution.objects.get(pk=kwargs['id'])
        except Execution.DoesNotExist:
            return Response({'error': 'Execution with given ID does not exist!'}, status = 404)

        if execution.status != 'C':
            return Response({'error': 'You can only start executions with Configured (C) state.'}, status = 400)

        execution.status = 'Q'
        execution.save()

        return Response(status = 200)
    



class Version(views.APIView):
    """
    Returns the current version of the FREE server

    """
    def get(self, *args, **kwargs):
        return Response({'version': settings.FREE_VERSION})


class ExecutionStatusSerializer(serializers.ModelSerializer):
    def validate(self, data):
        valid_transitions = {
            'Q': ['R'],
            'R': ['F', 'E']
        }

        if self.instance: # if updating
            if self.instance.status in valid_transitions:
                if data['status'] not in valid_transitions[self.instance.status]:
                    raise ValidationError('Execution in state ' + self.instance.status + ' can only change state to ' + ','.join(valid_transitions[self.instance.status]))
            else:
                raise ValidationError('Cannot change an execution with status ' + self.instance.status)

        return data
                
    class Meta:
        model = Execution
        fields = ['status']
