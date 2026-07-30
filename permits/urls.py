from django.urls import path

from . import views


urlpatterns = [

    # -------------------------------------------------
    # AUTHENTICATION
    # -------------------------------------------------
    path(
        "",
        views.login_view,
        name="login",
    ),
    path(
        "login/",
        views.login_view,
        name="login",
    ),
    path(
        "logout/",
        views.logout_view,
        name="logout",
    ),
    path(
        "change-password/",
        views.change_my_password,
        name="change_my_password",
    ),
    path(
        "redirect/",
        views.role_redirect,
        name="role_redirect",
    ),
    path(
        "home/",
        views.system_home,
        name="system_home",
    ),

    # -------------------------------------------------
    # PERMIT VERIFICATION
    # -------------------------------------------------
    path(
        "verify/<path:reference_no>/",
        views.verify_permit,
        name="verify_permit",
    ),

    # -------------------------------------------------
    # ACTING OFFICER / STAFF LOOKUP
    # -------------------------------------------------
    path(
        "acting-officer/<int:user_id>/details/",
        views.acting_officer_details,
        name="acting_officer_details",
    ),

    # -------------------------------------------------
    # USER MANAGEMENT AND REPORTS
    # -------------------------------------------------
    path(
        "users/",
        views.user_management,
        name="user_management",
    ),
    path(
        "users/create/",
        views.create_user_account,
        name="create_user_account",
    ),
    path(
        "users/<int:user_id>/edit/",
        views.edit_user_account,
        name="edit_user_account",
    ),
    path(
        "users/<int:user_id>/reset-password/",
        views.reset_user_password,
        name="reset_user_password",
    ),
    path(
        "permit-reports/",
        views.permit_reports,
        name="permit_reports",
    ),
    path(
        "permit-reports/export/excel/",
        views.export_permit_reports_excel,
        name="export_permit_reports_excel",
    ),
    path(
        "permit-reports/export/pdf/",
        views.export_permit_reports_pdf,
        name="export_permit_reports_pdf",
    ),

    # -------------------------------------------------
    # DASHBOARDS
    # -------------------------------------------------
    path(
        "dashboard/requester/",
        views.requester_dashboard,
        name="requester_dashboard",
    ),
    path(
        "dashboard/admin/",
        views.admin_dashboard,
        name="admin_dashboard",
    ),
    path(
        "dashboard/director/",
        views.director_dashboard,
        name="director_dashboard",
    ),
    path(
        "dashboard/assistant-director/",
        views.assistant_director_dashboard,
        name="assistant_director_dashboard",
    ),
    path(
        "dashboard/head-of-unit/",
        views.head_of_unit_requests,
        name="head_of_unit_requests",
    ),

    # -------------------------------------------------
    # REQUEST MANAGEMENT
    # -------------------------------------------------
    path(
        "request/new/",
        views.create_request,
        name="request_new",
    ),
    path(
        "request/<int:pk>/submitted/",
        views.submission_status,
        name="submission_status",
    ),
    path(
        "request/<int:pk>/",
        views.request_detail,
        name="request_detail",
    ),
    path(
        "request/<int:pk>/edit/",
        views.edit_request,
        name="edit_request",
    ),
    path(
        "request/<int:pk>/resubmit/",
        views.resubmit_request,
        name="resubmit_request",
    ),
    path(
        "request/<int:pk>/delete/",
        views.delete_request,
        name="delete_request",
    ),
    path(
        "request/<int:pk>/upload-report/",
        views.upload_summary_report,
        name="upload_summary_report",
    ),
    path(
        "request/<int:pk>/export-pdf/",
        views.export_permit_pdf,
        name="export_permit_pdf",
    ),

    # -------------------------------------------------
    # HEAD OF UNIT REVIEW
    # -------------------------------------------------
    path(
        "head-of-unit/request/<int:pk>/",
        views.head_of_unit_request_detail,
        name="head_of_unit_request_detail",
    ),

    # -------------------------------------------------
    # DIRECTOR AND ASSISTANT DIRECTOR REVIEW
    # -------------------------------------------------
    path(
        "director/requests/",
        views.director_requests,
        name="director_requests",
    ),
    path(
        "director/request/<int:pk>/",
        views.director_request_detail,
        name="director_request_detail",
    ),
]