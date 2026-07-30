from django.contrib import admin

from .models import (
    MinuteSheet,
    FinanceRequest,
    BudgetLine,
    ApprovalStep,
    Disbursement,
    Retirement,
    RetirementLine,
    FinanceDocument,
)


@admin.register(MinuteSheet)
class MinuteSheetAdmin(admin.ModelAdmin):
    list_display = (
        "reference_no",
        "title",
        "unit_name",
        "requested_amount",
        "director_approved_amount",
        "status",
        "created_at",
    )
    search_fields = ("reference_no", "title", "unit_name")
    list_filter = ("status", "unit_name", "created_at")


@admin.register(FinanceRequest)
class FinanceRequestAdmin(admin.ModelAdmin):
    list_display = (
        "request_no",
        "request_type",
        "requested_amount",
        "approved_amount",
        "status",
        "financial_year",
        "created_at",
    )
    search_fields = ("request_no", "financial_year", "cost_centre")
    list_filter = ("status", "request_type", "financial_year")


@admin.register(BudgetLine)
class BudgetLineAdmin(admin.ModelAdmin):
    list_display = (
        "task_code",
        "financial_year",
        "month",
        "budgeted_amount",
        "monthly_proposed_amount",
        "monthly_approved_amount",
        "amount_disbursed",
        "monthly_balance",
    )
    search_fields = ("task_code", "task_in_mtef", "item_name")
    list_filter = ("financial_year", "month", "expense_category")


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = (
        "finance_request",
        "step_name",
        "actor",
        "action",
        "sequence_no",
        "acted_at",
    )
    list_filter = ("step_name", "action")


@admin.register(Disbursement)
class DisbursementAdmin(admin.ModelAdmin):
    list_display = (
        "disbursement_no",
        "finance_request",
        "amount",
        "payment_method",
        "status",
        "recipient_name",
        "created_at",
    )
    search_fields = ("disbursement_no", "payment_reference", "recipient_name")
    list_filter = ("payment_method", "status")


@admin.register(Retirement)
class RetirementAdmin(admin.ModelAdmin):
    list_display = (
        "retirement_no",
        "finance_request",
        "amount_accounted",
        "amount_unaccounted",
        "refund_amount",
        "status",
        "created_at",
    )
    search_fields = ("retirement_no",)
    list_filter = ("status",)


admin.site.register(RetirementLine)
admin.site.register(FinanceDocument)