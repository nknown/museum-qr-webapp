import json
from django.views.generic import TemplateView
from django.core import serializers
from main_app.models import *
from django.db import connection

class ExecutionsView(TemplateView):
    template_name='free/executions.html'   

class ExecutionView(TemplateView):
    template_name='free/new_execution.html' 