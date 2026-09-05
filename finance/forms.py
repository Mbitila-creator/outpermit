from datetime import date

from django import forms
from django.db.models import Q

from .models import (
    MinuteSheet,
    FinanceRequest,
    BudgetLine,
    Disbursement,
    Retirement,
    RetirementLine,
    FinanceDocument,
)


MONTH_MAP = {
    1: "JANUARY",
    2: "FEBRUARY",
    3: "MARCH",
    4: "APRIL",
    5: "MAY",
    6: "JUNE",
    7: "JULY",
    8: "AUGUST",
    9: "SEPTEMBER",
    10: "OCTOBER",
    11: "NOVEMBER",
    12: "DECEMBER",
}


def get_current_budget_month(today=None):
    today = today or date.today()
    return MONTH_MAP[today.month]


def get_current_financial_year(today=None):
    today = today or date.today()

    if today.month >= 7:
        return f"{today.year}/{today.year + 1}"

    return f"{today.year - 1}/{today.year}"


def get_user_profile(user):
    """
    Safely return the logged-in user's profile.

    The project has previously used both `profile` and `userprofile`
    as reverse relationship names, so both are checked.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None

    profile = getattr(user, "profile", None)

    if profile is None:
        profile = getattr(user, "userprofile", None)

    return profile


def get_user_department(user):
    profile = get_user_profile(user)
    return getattr(profile, "department", None) if profile else None


def get_user_department_unit(user):
    profile = get_user_profile(user)
    return getattr(profile, "department_unit", None) if profile else None


class BaseStyledForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"

            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} {css_class}".strip()



class MinuteSheetForm(BaseStyledForm):
    class Meta:
        model = MinuteSheet

        fields = [
            "subject",
            "activity_series",
            "budget_line",
            "start_date",
            "end_date",
            "requested_amount",
            "attachment",
        ]

        labels = {
            "subject": "Subject",
            "activity_series": "Activities / Justification",
            "budget_line": "Related Task from Budget Line",
            "start_date": "Start Date",
            "end_date": "End Date",
            "requested_amount": "Requested Amount",
            "attachment": "Attachment",
        }

        widgets = {
            "activity_series": forms.Textarea(
                attrs={"rows": 5}
            ),
            "start_date": forms.DateInput(
                attrs={"type": "date", "onchange": "this.blur()"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "onchange": "this.blur()"}
            ),
            "requested_amount": forms.NumberInput(
                attrs={
                    "min": "0",
                    "step": "0.01",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)

        super().__init__(*args, **kwargs)

        current_month = get_current_budget_month()
        current_financial_year = get_current_financial_year()

        budget_lines = BudgetLine.objects.filter(
            monthly_approved_amount__gt=0,
        )

        department = get_user_department(self.user)

        if (
            self.user
            and self.user.is_authenticated
            and not self.user.is_superuser
        ):
            if department:
                budget_lines = budget_lines.filter(
                    department=department
                )
            else:
                budget_lines = BudgetLine.objects.none()

        current_period_lines = budget_lines.filter(
            financial_year=current_financial_year,
            month=current_month,
        )

        if current_period_lines.exists():
            budget_lines = current_period_lines

            self.fields["budget_line"].help_text = (
                f"Showing approved Budget Lines for "
                f"{current_month} ({current_financial_year}) "
                f"from your department."
            )
        else:
            self.fields["budget_line"].help_text = (
                f"No approved Budget Lines were found for "
                f"{current_month} ({current_financial_year}). "
                "Showing all approved Budget Lines available "
                "for your department."
            )

        self.fields["budget_line"].queryset = (
            budget_lines.order_by(
                "-financial_year",
                "task_code",
                "month",
                "monthly_activity_description",
            ).distinct()
        )

        self.fields["budget_line"].empty_label = (
            "-- Select Related Task from Budget Line --"
        )

    def clean(self):
        cleaned_data = super().clean()

        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        requested_amount = cleaned_data.get("requested_amount")
        budget_line = cleaned_data.get("budget_line")

        if start_date and end_date and end_date < start_date:
            self.add_error(
                "end_date",
                "End date cannot be earlier than start date.",
            )

        if (
            requested_amount is not None
            and requested_amount <= 0
        ):
            self.add_error(
                "requested_amount",
                "Requested amount must be greater than zero.",
            )

        if budget_line:
            allowed_budget_lines = (
                self.fields["budget_line"].queryset
            )

            if not allowed_budget_lines.filter(
                pk=budget_line.pk
            ).exists():
                self.add_error(
                    "budget_line",
                    (
                        "You are not allowed to use the selected "
                        "Budget Line."
                    ),
                )

            department = get_user_department(self.user)

            if (
                department
                and budget_line.department_id
                != department.id
            ):
                self.add_error(
                    "budget_line",
                    (
                        "The selected Budget Line does not belong "
                        "to your department."
                    ),
                )

        return cleaned_data


class FinanceRequestForm(BaseStyledForm):
    class Meta:
        model = FinanceRequest

        # request_no is deliberately excluded. It is generated automatically
        # by FinanceRequest.save() using the user's department.
        #
        # approved_amount is also excluded from the requester form because it
        # must only be set during the approval process.
        fields = [
            "minute_sheet",
            "request_type",
            "requested_amount",
            "currency",
            "funding_source",
            "financial_year",
            "vote_code",
            "sub_vote",
            "cost_centre",
            "remarks",
        ]

        labels = {
            "minute_sheet": "Approved Minute Sheet",
            "request_type": "Request Type",
            "requested_amount": "Requested Amount",
            "currency": "Currency",
            "funding_source": "Funding Source",
            "financial_year": "Financial Year",
            "vote_code": "Vote Code",
            "sub_vote": "Sub-vote",
            "cost_centre": "Cost Centre",
            "remarks": "Remarks",
        }

        widgets = {
            "requested_amount": forms.NumberInput(
                attrs={"min": "0", "step": "0.01"}
            ),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        current_financial_year = get_current_financial_year()
        self.fields["financial_year"].initial = current_financial_year

        minute_sheets = MinuteSheet.objects.all()

        if self.user and self.user.is_authenticated and not self.user.is_superuser:
            department = get_user_department(self.user)

            minute_sheets = minute_sheets.filter(
                Q(requested_by=self.user)
                | Q(department=department)
            )

            if department:
                minute_sheets = minute_sheets.filter(department=department)
            else:
                minute_sheets = minute_sheets.filter(requested_by=self.user)

        # Do not offer a Minute Sheet that already has a Finance Request.
        # The relationship currently permits several requests technically,
        # but the creation form treats each Minute Sheet as one request.
        if not self.instance.pk:
            minute_sheets = minute_sheets.filter(
                finance_requests__isnull=True
            )

        self.fields["minute_sheet"].queryset = minute_sheets.order_by(
            "-created_at"
        ).distinct()

        self.fields["minute_sheet"].help_text = (
            "Only eligible minute sheets belonging to your department are shown."
        )

    def clean(self):
        cleaned_data = super().clean()

        minute_sheet = cleaned_data.get("minute_sheet")
        requested_amount = cleaned_data.get("requested_amount")

        if requested_amount is not None and requested_amount <= 0:
            self.add_error(
                "requested_amount",
                "Requested amount must be greater than zero.",
            )

        if minute_sheet:
            allowed_minute_sheets = self.fields["minute_sheet"].queryset

            if not allowed_minute_sheets.filter(pk=minute_sheet.pk).exists():
                self.add_error(
                    "minute_sheet",
                    "You are not allowed to use the selected minute sheet.",
                )

            minute_amount = minute_sheet.requested_amount or 0

            if (
                requested_amount is not None
                and minute_amount
                and requested_amount > minute_amount
            ):
                self.add_error(
                    "requested_amount",
                    "Requested amount cannot exceed the Minute Sheet amount.",
                )

        return cleaned_data


class BudgetLineForm(BaseStyledForm):
    class Meta:
        model = BudgetLine

        # PART A: PLANNING AND BUDGETING SECTION
        # DBO manually enters items 1, 2, 3, 5, 6, 7 and 8.
        # Item 4: Amount Disbursed is accumulated automatically from
        # Disbursement records.
        fields = [
            "task_code",
            "task_in_mtef",
            "financial_year",
            "budgeted_amount",
            "month",
            "monthly_activity_description",
            "monthly_proposed_amount",
            "monthly_approved_amount",
            "remarks",
        ]

        labels = {
            "task_code": "1. Task Code",
            "task_in_mtef": "2. Task in MTEF",
            "financial_year": "Financial Year",
            "budgeted_amount": "3. Budgeted Amount",
            "month": "Month",
            "monthly_activity_description": "5. Monthly Activity Description",
            "monthly_proposed_amount": "6. Monthly Proposed Amount",
            "monthly_approved_amount": "7. Approved Amount",
            "remarks": "8. Remarks",
        }

        widgets = {
            "task_in_mtef": forms.Textarea(attrs={"rows": 3}),
            "budgeted_amount": forms.NumberInput(
                attrs={"min": "0", "step": "0.01"}
            ),
            "monthly_activity_description": forms.Textarea(attrs={"rows": 3}),
            "monthly_proposed_amount": forms.NumberInput(
                attrs={"min": "0", "step": "0.01"}
            ),
            "monthly_approved_amount": forms.NumberInput(
                attrs={"min": "0", "step": "0.01"}
            ),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

        help_texts = {
            "budgeted_amount": (
                "Enter the total amount budgeted for this task in the "
                "selected financial year."
            ),
            "monthly_proposed_amount": (
                "Enter the amount requested by the division for the "
                "selected month."
            ),
            "monthly_approved_amount": (
                "Enter the amount approved for use in the selected month."
            ),
            "remarks": (
                "Enter any explanation, justification, or budget note."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.fields["financial_year"].initial = (
                get_current_financial_year()
            )
            self.fields["month"].initial = get_current_budget_month()


class DisbursementForm(BaseStyledForm):
    class Meta:
        model = Disbursement
        fields = [
            "finance_request",
            "disbursement_no",
            "amount",
            "payment_method",
            "payment_reference",
            "recipient_name",
            "recipient_account",
            "status",
            "notes",
        ]

        widgets = {
            "amount": forms.NumberInput(
                attrs={"min": "0.01", "step": "0.01"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        finance_requests = FinanceRequest.objects.filter(
            status__in=[
                "DIRECTOR_APPROVED",
                "PARTIALLY_APPROVED",
                "DISBURSED",
            ],
            approved_amount__gt=0,
        )

        if self.user and self.user.is_authenticated and not self.user.is_superuser:
            department = get_user_department(self.user)

            if department:
                finance_requests = finance_requests.filter(
                    department=department
                )

        self.fields["finance_request"].queryset = (
            finance_requests.order_by("-created_at")
        )


class RetirementForm(BaseStyledForm):
    class Meta:
        model = Retirement
        fields = [
            "finance_request",
            "amount_accounted",
            "summary",
        ]

        widgets = {
            "amount_accounted": forms.NumberInput(
                attrs={"min": "0", "step": "0.01"}
            ),
            "summary": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        qs = FinanceRequest.objects.filter(
            status__in=["DIRECTOR_APPROVED", "DISBURSED"],
            approved_amount__gt=0,
        ).exclude(
            retirement__isnull=False
        ).order_by("-created_at")

        if self.user and not self.user.is_superuser:
            department = get_user_department(self.user)

            qs = qs.filter(
                Q(submitted_by=self.user)
                | Q(minute_sheet__requested_by=self.user)
            )

            if department:
                qs = qs.filter(department=department)

            qs = qs.distinct()

        self.fields["finance_request"].queryset = qs


class RetirementLineForm(BaseStyledForm):
    class Meta:
        model = RetirementLine
        fields = [
            "retirement",
            "description",
            "receipt_no",
            "amount",
            "attachment",
        ]

        widgets = {
            "amount": forms.NumberInput(
                attrs={"min": "0.01", "step": "0.01"}
            ),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        retirements = Retirement.objects.all()

        if self.user and self.user.is_authenticated and not self.user.is_superuser:
            department = get_user_department(self.user)

            retirements = retirements.filter(
                Q(submitted_by=self.user)
                | Q(finance_request__submitted_by=self.user)
            )

            if department:
                retirements = retirements.filter(
                    finance_request__department=department
                )

        self.fields["retirement"].queryset = retirements.order_by(
            "-created_at"
        ).distinct()


class FinanceDocumentForm(BaseStyledForm):
    class Meta:
        model = FinanceDocument
        fields = [
            "finance_request",
            "minute_sheet",
            "retirement",
            "document_type",
            "file",
        ]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if not self.user or not self.user.is_authenticated:
            return

        if self.user.is_superuser:
            return

        department = get_user_department(self.user)

        finance_requests = FinanceRequest.objects.filter(
            Q(submitted_by=self.user)
            | Q(minute_sheet__requested_by=self.user)
        )
        minute_sheets = MinuteSheet.objects.filter(requested_by=self.user)
        retirements = Retirement.objects.filter(
            Q(submitted_by=self.user)
            | Q(finance_request__submitted_by=self.user)
        )

        if department:
            finance_requests = FinanceRequest.objects.filter(
                department=department
            )
            minute_sheets = MinuteSheet.objects.filter(
                department=department
            )
            retirements = Retirement.objects.filter(
                finance_request__department=department
            )

        self.fields["finance_request"].queryset = (
            finance_requests.order_by("-created_at").distinct()
        )
        self.fields["minute_sheet"].queryset = (
            minute_sheets.order_by("-created_at").distinct()
        )
        self.fields["retirement"].queryset = (
            retirements.order_by("-created_at").distinct()
        )

    def clean(self):
        cleaned_data = super().clean()

        linked_records = [
            cleaned_data.get("finance_request"),
            cleaned_data.get("minute_sheet"),
            cleaned_data.get("retirement"),
        ]

        if sum(record is not None for record in linked_records) != 1:
            raise forms.ValidationError(
                "Select exactly one Finance Request, Minute Sheet, "
                "or Retirement for this document."
            )

        return cleaned_data
