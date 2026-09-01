from django.urls import path

from . import views


app_name = "learning_events"

urlpatterns = [
    path("learning/<slug:event_slug>/programme/", views.public_programme, name="public_programme"),
    path("staff/learning/<slug:event_slug>/", views.dashboard, name="dashboard"),
    path(
        "staff/learning/<slug:event_slug>/enrollments/<int:enrollment_id>/approve-certificate/",
        views.approve_certificate,
        name="approve_certificate",
    ),
]
