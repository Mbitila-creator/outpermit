from django.urls import path
from . import views

app_name = 'system_admin'

urlpatterns = [
    path('settings/', views.system_settings, name='settings'),
    path('security-stages/', views.security_stages, name='security_stages'),
    path('backups/', views.backup_list, name='backup_list'),
    path('backups/create/', views.create_backup, name='create_backup'),
]