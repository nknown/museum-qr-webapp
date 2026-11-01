from  main_app.userAdmin.views import *
from django.urls import re_path, path
urlpatterns = []

urlpatterns += [
    path('free-admin/usersCleanUp/', UsersCleanUpListView.as_view(), name='users-cleanup-admin'),
    path('free-admin/delete_user/<int:id>', UserDelete.as_view(), name='user-delete-admin'),
    path('free-admin/experimentsCleanup/', ExperimentCleanUpView.as_view(), name='experiments-cleanup-admin'),
    path('free-admin/executions/delete/<int:days>/<str:opt>', ExecutionsDeleteOlder.as_view(), name='api-delet-executions-older'),
]
