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
        "reports/certificates/pdf/",
        views.certificate_bulk_pdf,
        name="certificate_bulk_pdf",
    ),
    path(
        "reports/participants/print/",
        views.participant_list_print,
        name="participant_list_print",
    ),
    path(
        "reports/participants/excel/",
        views.participant_list_excel,
        name="participant_list_excel",
    ),
    path(
        "reports/participants/<int:submission_id>/",
        views.participant_staff_detail,
        name="participant_staff_detail",
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
