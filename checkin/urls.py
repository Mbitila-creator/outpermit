from django.urls import path

from . import views


app_name = "checkin"

urlpatterns = [
    path(
        "reports/attendance/",
        views.attendance_reports,
        name="reports",
    ),
    path(
        "reports/attendance/export/",
        views.attendance_report_csv,
        name="reports_csv",
    ),
    path(
        "check-in/",
        views.check_in_lookup,
        name="lookup",
    ),
    path(
        "check-in/<uuid:participant_token>/",
        views.participant_check_in,
        name="participant",
    ),
]

