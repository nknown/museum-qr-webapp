from main_app import views
from django.urls import path, re_path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from django.conf.urls.static import static
from django.conf import settings

# Helper function to generate API documentation
schema_view = get_schema_view(
   openapi.Info(
      title="MAIN-APP API",
      default_version='v1',
      description="Documentation for MAIN-APP API endpoints",
      contact=openapi.Contact(email="kurispav@fjfi.cvut.cz"),
      license=openapi.License(name="MIT License"),
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)

app_name = 'main_app'
urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('login', views.LoginView.as_view(), name='login'),
    path('logout', views.LogoutView.as_view(), name='logout'),

    # API DOCUMENTATION
    re_path(r'^main_app-api(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    re_path(r'^api/swagger/$', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    re_path(r'^api/redoc/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    # PAGES
    path('executions/configured', views.ExecutionsConfiguredListView.as_view(), name='executions-configured'),
    path('executions/finished', views.ExecutionsFinishedListView.as_view(), name='executions-finished'),

    path('execution/create/<int:apparatus_id>/<int:protocol_id>', views.CreateExecutionView.as_view(), name='execution-create'),
    path('execution/<int:pk>', views.ExecutionView.as_view(), name='execution'),
    path('execution/<int:pk>/bare', views.ExecutionStrippedView.as_view(), name='stripped-execution'),
    path('execution/create/<int:apparatus_id>/<int:protocol_id>/bare', views.CreateExecutionStrippedView.as_view(), name='stripped-execution-create'),

   # exhibition / piece hierarchy
    path('exhibitions', views.ExhibitionsListView.as_view(), name='exhibitions-list'),
    path('exhibition/create', views.ExhibitionCreateView.as_view(), name='exhibition-create'),
    path('exhibition/<int:pk>', views.ExhibitionView.as_view(), name='exhibition'),
    path('exhibition/<int:pk>/update', views.ExhibitionUpdateView.as_view(), name='exhibition-update'),



    # REST API
    path('api/v1/version', views.Version.as_view(), name='api-version'),

    path('api/v1/execution', views.ExecutionConfigure.as_view(), name='api-execution-configure' ),
    path('api/v1/execution/<int:id>', views.ExecutionRetrieveUpdateDestroy().as_view(), name='api-execution'),
    path('api/v1/execution/<int:id>/name', views.ExecutionUpdateName.as_view(), name='api-execution-update-name'),
    path('api/v1/execution/<int:id>/start', views.ExecutionStart.as_view(), name='api-execution-start'),
    

    path('things', views.ThingsListView.as_view(), name='things-list'),
    path('thing/<int:pk>', views.ThingView.as_view(), name='thing'),
    path('thing/create', views.ThingCreateView.as_view(), name='thing-create'), 
    path('thing/<int:pk>/update', views.ThingUpdateView.as_view(), name='thing-update'), 

#    path('spatialthings', views.SpatialThingsListView.as_view(), name='spatial-things-list'),
#    path('spatialthing/<int:pk>', views.SpatialThingView.as_view(), name='spatial-thing'),
#    path('spatialthing/create', views.SpatialThingCreateView.as_view(), name='spatial-thing-create'), 
#    path('spatialthing/<int:pk>/update', views.SpatialThingUpdateView.as_view(), name='spatial-thing-update'), 



]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
