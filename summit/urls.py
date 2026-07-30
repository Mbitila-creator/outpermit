from django.urls import path
from . import views

urlpatterns = [
    path('register/<str:event_code>/', views.register_participant, name='summit_register'),
    path('success/<int:participant_id>/', views.summit_success, name='summit_success'),
    path('badge/<int:participant_id>/', views.participant_badge, name='participant_badge'),
    path('admin-dashboard/', views.summit_admin_dashboard, name='summit_admin_dashboard'),
    path('participants/', views.participant_list, name='participant_list'),
    path('participants/export-excel/', views.export_participants_excel, name='export_participants_excel'),

    path('events/', views.event_list, name='event_list'),
    path('events/create/', views.create_event, name='create_event'),
    path('events/<int:event_id>/activate/', views.activate_event, name='activate_event'),
    path('events/<int:event_id>/', views.event_details, name='event_details'),

    path('events/<int:event_id>/edit/', views.edit_event, name='edit_event'),

    path('events/<int:event_id>/open/', views.open_event, name='open_event'),
    path('events/<int:event_id>/close/', views.close_event, name='close_event'),
    path('events/<int:event_id>/archive/', views.archive_event, name='archive_event'),
    path('events/<int:event_id>/duplicate/', views.duplicate_event, name='duplicate_event'),
]