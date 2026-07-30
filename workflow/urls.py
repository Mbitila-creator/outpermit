from django.urls import path
from . import views

urlpatterns = [
    path("", views.workflow_list, name="workflow_list"),
    path("details/<int:department_id>/<str:module_code>/", views.workflow_details, name="workflow_details"),
    path("add/<int:department_id>/<str:module_code>/", views.workflow_add_step, name="workflow_add_step"),
    path("edit/<int:workflow_id>/", views.workflow_edit, name="workflow_edit"),
    path("delete/<int:workflow_id>/", views.workflow_delete, name="workflow_delete"),
]