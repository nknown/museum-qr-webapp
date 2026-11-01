from main_app import views
from django.urls import path, re_path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic.base import RedirectView

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

    path('visit/history', views.VisitorHistoryView.as_view(), name='visitor-history'),

    path('exhibition/<int:pk>/publication', views.PublicationView.as_view(), {'kind': 'exhibition'}, name='exhibition-publication'),
    path('piece/<int:pk>/publication', views.PublicationView.as_view(), {'kind': 'piece'}, name='piece-publication'),

    # PAGES
    path('executions/configured', views.ExecutionsConfiguredListView.as_view(), name='executions-configured'),
    path('executions/finished', views.ExecutionsFinishedListView.as_view(), name='executions-finished'),

    path('execution/create/<int:apparatus_id>/<int:protocol_id>', views.CreateExecutionView.as_view(), name='execution-create'),
    path('execution/<int:pk>', views.ExecutionView.as_view(), name='execution'),
    path('execution/<int:pk>/bare', views.ExecutionStrippedView.as_view(), name='stripped-execution'),
    path('execution/create/<int:apparatus_id>/<int:protocol_id>/bare', views.CreateExecutionStrippedView.as_view(), name='stripped-execution-create'),

   # exhibition / piece hierarchy
   path('museums', views.MuseumsListView.as_view(), name='museums-list'),
   path('museum/create', views.MuseumCreateView.as_view(), name='museum-create'),
   path('museum/<int:pk>/update', views.MuseumChangeView.as_view(), name='museum-update'),
   path('museum/<int:pk>/change', RedirectView.as_view(pattern_name='main_app:museum-update', permanent=False), name='museum-change'),
   path('museum/<int:pk>/delete', views.MuseumDeleteView.as_view(), name='museum-delete'),
   path('exhibitions', views.ExhibitionsListView.as_view(), name='exhibitions-list'),
    path('exhibition/create', views.ExhibitionCreateView.as_view(), name='exhibition-create'),
    path('exhibition/<int:pk>/update', views.ExhibitionUpdateView.as_view(), name='exhibition-update'),
    path('exhibition/<int:pk>/user-device-qrs', views.ExhibitionUserDeviceQRCodesView.as_view(), name='exhibition-user-device-qrs'),
    path('exhibition/<int:pk>/delete', views.ExhibitionDeleteView.as_view(), name='exhibition-delete'),
   path('exhibition/<int:pk>/presentation/<slug:presentation_type>', views.ExhibitionPresentationView.as_view(), name='exhibition-presentation'),
   path('presentation/exhibition/<uuid:public_id>', views.ExhibitionPresentationView.as_view(), name='exhibition-public-presentation'),
   path('exhibition/<int:pk>/attributes/create', views.ExhibitionAttributesCreateView.as_view(), name='exhibition-attributes-create'),
    path('exhibition/<int:pk>/add-pieces', views.ExhibitionAddPiecesView.as_view(), name='exhibition-add-pieces'),
   path('pieces', views.PiecesOverviewView.as_view(), name='pieces-overview'),
   path('piece/create/', views.PieceCreateView.as_view(), name='piece-create'),
   path('piece/create/<int:exhibition_id>', views.PieceCreateView.as_view(), name='piece-create-for-exhibition'),
   path('piece/<int:pk>', views.PieceView.as_view(), name='piece'),
   path('piece/<int:pk>/update', views.PieceUpdateView.as_view(), name='piece-update'),
   path('piece/<int:pk>/delete', views.PieceDeleteView.as_view(), name='piece-delete'),
    path('piece/<int:pk>/presentation/<slug:presentation_type>', views.PiecePresentationView.as_view(), name='piece-presentation'),
    path('presentation/piece/<uuid:public_id>', views.PiecePresentationView.as_view(), name='piece-public-presentation'),
         path('presentation-access/<int:pk>/slide', views.PresentationAccessSlideUpdateView.as_view(), name='presentation-access-slide'),
         path('presentation-favorites', views.PresentationFavoritesView.as_view(), name='presentation-favorites'),
      path('statistics', views.StatisticsView.as_view(), name='statistics'),
         path('statistics/history/<str:history_type>/<int:pk>', views.StatisticsHistoryView.as_view(), name='statistics-history'),
         path('statistics/presentation/<str:presentation_type>/<int:pk>', views.StatisticsPresentationView.as_view(), name='statistics-presentation'),
    

   # path('things', views.ThingsListView.as_view(), name='things-list'),
   # path('thing/<int:pk>', views.ThingView.as_view(), name='thing'),
   # path('thing/create', views.ThingCreateView.as_view(), name='thing-create'), 
   # path('thing/<int:pk>/update', views.ThingUpdateView.as_view(), name='thing-update'), 

#    path('spatialthings', views.SpatialThingsListView.as_view(), name='spatial-things-list'),
#    path('spatialthing/<int:pk>', views.SpatialThingView.as_view(), name='spatial-thing'),
#    path('spatialthing/create', views.SpatialThingCreateView.as_view(), name='spatial-thing-create'), 
#    path('spatialthing/<int:pk>/update', views.SpatialThingUpdateView.as_view(), name='spatial-thing-update'), 



]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
