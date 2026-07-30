from django.urls import path
from . import views

app_name = "finance"

urlpatterns = [
    path("", views.finance_dashboard, name="dashboard"),

    path("budget-lines/", views.budget_line_list, name="budget_line_list"),
    path("budget-lines/<int:pk>/edit/", views.budget_line_edit, name="budget_line_edit"),

    path("minute-sheets/create/", views.minute_sheet_create, name="minute_sheet_create"),
    path("minute-sheets/<int:pk>/", views.minute_sheet_detail, name="minute_sheet_detail"),

    path("requests/create/", views.finance_request_create, name="finance_request_create"),
    path("requests/<int:pk>/", views.finance_request_detail, name="finance_request_detail"),

    path("budget-lines/create/", views.budget_line_create, name="budget_line_create"),

    path("disbursements/create/", views.disbursement_create, name="disbursement_create"),

    path("retirements/create/", views.retirement_create, name="retirement_create"),

    path("reports/", views.finance_reports, name="finance_reports"),

    path("ajax/search-mtef-task/", views.search_mtef_task, name="search_mtef_task"),

    path("analytics/", views.finance_analytics, name="finance_analytics"),

    path("minute-sheets/", views.minute_sheet_list, name="minute_sheet_list"),

    path("analytics/export/excel/", views.export_finance_analytics_excel, name="export_finance_analytics_excel"),
    
    path("analytics/export/pdf/", views.export_finance_analytics_pdf, name="export_finance_analytics_pdf"),

    path("start-new-financial-year/", views.start_new_financial_year, name="start_new_financial_year"),

    path("retirements/", views.retirement_list, name="retirement_list"),
    path("retirements/<int:pk>/", views.retirement_detail, name="retirement_detail"),

    path("retirements/<int:pk>/edit/", views.edit_retirement, name="edit_retirement"),

    path(
    "budget-lines/clone-month/",
    views.clone_month_to_next,
    name="clone_month_to_next",
    ),

    path(
    "ajax/finance-request-amount/",
    views.get_finance_request_amount,
    name="get_finance_request_amount"
    ),
]  