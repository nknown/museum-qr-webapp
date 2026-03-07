try:
    from django.conf.urls import url
except ImportError:
    from django.urls import re_path as url

# from .views import QuizListView, CategoriesListView, \
#     ViewQuizListByCategory, QuizUserProgressView, QuizMarkingList, \
#     QuizMarkingDetail, QuizDetailView, QuizTake
from .views import *
from django.urls import path

app_name = 'FREE_maps'
urlpatterns = [

    path('apparatus/<int:pk>/map', ApparatusMapView.as_view(), name='apparatus-Map'),
    path('apparatus/<int:pk>/finishedExecutions', ApparatusGetFinishedExecutions.as_view(), name='apparatus-Finished-Executions'),
    path('apparatus/<int:pk>/queue', ApparatusExecutionsQueue.as_view(), name='apparatus-Executions-Queue'),

]
