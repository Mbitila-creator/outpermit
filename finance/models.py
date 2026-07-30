from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models, transaction

User = settings.AUTH_USER_MODEL


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def get_user_profile(user):
    """Return the permit UserProfile linked to a user, when available."""
    if not user:
        return None

    for attribute in ("profile", "userprofile"):
        try:
            profile = getattr(user, attribute)
        except (AttributeError, ObjectDoesNotExist):
            profile = None

        if profile:
            return profile

    return None


class MinuteSheet(TimeStampedModel):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SUBMITTED", "Submitted"),
        ("HOU_REVIEW", "HOU Review"),
        ("DIRECTOR_REVIEW", "Director Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CLOSED", "Closed"),
    ]

    reference_no = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255, blank=True, default="")
    subject = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    activity_series = models.TextField(blank=True, default="")

    requested_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="minute_sheets_requested",
        null=True,
        blank=True,
    )

    # Stage 1: Store the department and unit at the time the minute sheet is
    # created. They remain nullable so existing records can migrate safely.
    department = models.ForeignKey(
        "permits.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_minute_sheets",
    )
    department_unit = models.ForeignKey(
        "permits.DepartmentUnit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_minute_sheets",
    )

    # Kept temporarily for compatibility with existing templates and data.
    unit_name = models.CharField(max_length=255, blank=True, default="")

    budget_line = models.ForeignKey(
        "finance.BudgetLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="minute_sheets",
    )

    related_task = models.ForeignKey(
        "tasks.Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="minute_sheets",
    )

    related_permit = models.ForeignKey(
        "permits.ExternalWorkRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="minute_sheets",
    )

    activity_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    justification = models.TextField(null=True, blank=True)

    requested_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    hou_recommended_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    director_approved_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    estimated_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="DRAFT",
    )

    attachment = models.FileField(
        upload_to="finance/minute_sheets/",
        null=True,
        blank=True,
    )

    is_approved = models.BooleanField(default=False)
    director_remarks = models.TextField(blank=True, default="")

    def __str__(self):
        if self.reference_no:
            return self.reference_no
        if self.subject:
            return self.subject
        if self.title:
            return self.title
        return f"Minute Sheet #{self.pk}"

    def _assign_organization_from_requester(self):
        profile = get_user_profile(self.requested_by)
        if not profile:
            return

        if not self.department_id:
            self.department = getattr(profile, "department", None)

        if not self.department_unit_id:
            self.department_unit = getattr(profile, "department_unit", None)

        if not self.unit_name and self.department_unit:
            self.unit_name = self.department_unit.name

    def clean(self):
        super().clean()
        self._assign_organization_from_requester()

        if (
            self.department_unit_id
            and self.department_id
            and self.department_unit.department_id != self.department_id
        ):
            raise ValidationError(
                {
                    "department_unit": (
                        "The selected unit does not belong to the "
                        "selected department."
                    )
                }
            )

        if (
            self.budget_line_id
            and self.department_id
            and self.budget_line.department_id != self.department_id
        ):
            raise ValidationError(
                {
                    "budget_line": (
                        "The selected Budget Line does not belong "
                        "to the Minute Sheet department."
                    )
                }
            )

        if not self.budget_line and not self.related_task and not self.related_permit:
            raise ValidationError(
                (
                    "A Minute Sheet must be linked to a Budget Line, "
                    "Task, Permit, or at least one of them."
                )
            )

    def save(self, *args, **kwargs):
        self._assign_organization_from_requester()
        super().save(*args, **kwargs)


class FinanceRequest(TimeStampedModel):
    REQUEST_TYPE_CHOICES = [
        ("ADVANCE", "Advance"),
        ("REIMBURSEMENT", "Reimbursement"),
        ("DIRECT_PAYMENT", "Direct Payment"),
        ("IMPRESS", "Imprest"),
        ("SPECIAL_ACTIVITY", "Special Activity"),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SUBMITTED", "Submitted"),
        ("HOU_REVIEWED", "HOU Reviewed"),
        ("DIRECTOR_APPROVED", "Director Approved"),
        ("PARTIALLY_APPROVED", "Partially Approved"),
        ("DISBURSED", "Disbursed"),
        ("RETIRED", "Retired"),
        ("REJECTED", "Rejected"),
    ]

    # Generated automatically as DEPARTMENT-FIN-YEAR-SEQUENCE.
    request_no = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
    )

    minute_sheet = models.ForeignKey(
        MinuteSheet,
        on_delete=models.CASCADE,
        related_name="finance_requests",
    )

    # Stage 1: organizational ownership of each finance request.
    department = models.ForeignKey(
        "permits.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_requests",
    )
    department_unit = models.ForeignKey(
        "permits.DepartmentUnit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_requests",
    )

    request_type = models.CharField(max_length=30, choices=REQUEST_TYPE_CHOICES)
    requested_amount = models.DecimalField(max_digits=14, decimal_places=2)
    approved_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    currency = models.CharField(max_length=10, default="TZS")
    funding_source = models.CharField(max_length=255, blank=True)
    financial_year = models.CharField(max_length=20, default="2025/2026")
    vote_code = models.CharField(max_length=50, blank=True)
    sub_vote = models.CharField(max_length=50, blank=True)
    cost_centre = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="DRAFT",
    )

    submitted_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="finance_requests_submitted",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["department", "status"]),
            models.Index(fields=["submitted_by", "status"]),
            models.Index(fields=["financial_year"]),
        ]

    def __str__(self):
        return self.request_no or f"Finance Request #{self.pk}"

    def _assign_organization(self):
        profile = get_user_profile(self.submitted_by)

        if not self.department_id and profile:
            self.department = getattr(profile, "department", None)

        if not self.department_unit_id and profile:
            self.department_unit = getattr(profile, "department_unit", None)

        # Fall back to the linked minute sheet for old or incomplete profiles.
        if self.minute_sheet_id:
            if not self.department_id:
                self.department = self.minute_sheet.department
            if not self.department_unit_id:
                self.department_unit = self.minute_sheet.department_unit

    def _financial_year_start(self):
        """Return the first year in values such as 2025/2026."""
        value = (self.financial_year or "").strip()
        first_part = value.split("/")[0]
        return first_part if first_part.isdigit() else "GEN"

    def _generate_request_no(self):
        department_code = "GEN"
        if self.department and self.department.code:
            department_code = self.department.code.strip().upper()

        year_code = self._financial_year_start()
        prefix = f"{department_code}-FIN-{year_code}-"

        latest = (
            FinanceRequest.objects.select_for_update()
            .filter(request_no__startswith=prefix)
            .order_by("-request_no")
            .first()
        )

        sequence = 1
        if latest and latest.request_no:
            try:
                sequence = int(latest.request_no.rsplit("-", 1)[1]) + 1
            except (IndexError, TypeError, ValueError):
                sequence = (
                    FinanceRequest.objects.filter(request_no__startswith=prefix).count()
                    + 1
                )

        request_no = f"{prefix}{sequence:04d}"
        while FinanceRequest.objects.filter(request_no=request_no).exists():
            sequence += 1
            request_no = f"{prefix}{sequence:04d}"

        return request_no

    def clean(self):
        self._assign_organization()

        if self.approved_amount and self.approved_amount > self.requested_amount:
            raise ValidationError(
                {"approved_amount": "Approved amount cannot exceed requested amount."}
            )

        if self.requested_amount is not None and self.requested_amount <= 0:
            raise ValidationError(
                {"requested_amount": "Requested amount must be greater than zero."}
            )

        if (
            self.department_unit_id
            and self.department_id
            and self.department_unit.department_id != self.department_id
        ):
            raise ValidationError(
                {"department_unit": "The selected unit does not belong to the selected department."}
            )

    def save(self, *args, **kwargs):
        self._assign_organization()

        if self.minute_sheet_id:
            minute_sheet_changed = False

            if not self.minute_sheet.department_id and self.department_id:
                self.minute_sheet.department = self.department
                minute_sheet_changed = True

            if not self.minute_sheet.department_unit_id and self.department_unit_id:
                self.minute_sheet.department_unit = self.department_unit
                minute_sheet_changed = True

            if minute_sheet_changed:
                self.minute_sheet.save(
                    update_fields=["department", "department_unit", "updated_at"]
                )

        if self.request_no:
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            self.request_no = self._generate_request_no()
            super().save(*args, **kwargs)

    @property
    def total_budget_lines(self):
        return sum(
            (line.total_cost for line in self.budget_lines.all()),
            Decimal("0.00"),
        )

    @property
    def total_disbursed(self):
        return sum(
            (
                item.amount
                for item in self.disbursements.filter(status="PAID")
            ),
            Decimal("0.00"),
        )

    @property
    def remaining_approved_balance(self):
        approved = self.approved_amount or Decimal("0.00")
        return approved - self.total_disbursed

    @property
    def requires_retirement(self):
        return self.request_type in ["ADVANCE", "IMPRESS"]


class BudgetLine(models.Model):
    CATEGORY_CHOICES = [
        ("TRANSPORT", "Transport"),
        ("ACCOMMODATION", "Accommodation"),
        ("FUEL", "Fuel"),
        ("MEALS", "Meals"),
        ("PRINTING", "Printing"),
        ("ALLOWANCE", "Allowance"),
        ("PROCUREMENT", "Procurement"),
        ("OTHER", "Other"),
    ]

    MONTH_CHOICES = [
        ("JULY", "July"),
        ("AUGUST", "August"),
        ("SEPTEMBER", "September"),
        ("OCTOBER", "October"),
        ("NOVEMBER", "November"),
        ("DECEMBER", "December"),
        ("JANUARY", "January"),
        ("FEBRUARY", "February"),
        ("MARCH", "March"),
        ("APRIL", "April"),
        ("MAY", "May"),
        ("JUNE", "June"),
    ]

    department = models.ForeignKey(
        "permits.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_budget_lines",
    )

    department_unit = models.ForeignKey(
        "permits.DepartmentUnit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_budget_lines",
    )

    finance_request = models.ForeignKey(
        FinanceRequest,
        on_delete=models.CASCADE,
        related_name="budget_lines",
        null=True,
        blank=True,
    )

    task_code = models.CharField(max_length=50, default="TASK-001")
    task_in_mtef = models.TextField(default="Default Task")
    financial_year = models.CharField(max_length=20, default="2025/2026")

    budgeted_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    amount_disbursed = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    month = models.CharField(
        max_length=20,
        choices=MONTH_CHOICES,
        default="JULY",
    )
    monthly_activity_description = models.TextField(blank=True)

    monthly_proposed_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=Decimal("0.00"),
    )

    monthly_approved_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=Decimal("0.00"),
    )

    item_name = models.CharField(
        max_length=255,
        default="General Activity",
    )
    description = models.TextField(blank=True)

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1,
    )
    unit_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    total_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        editable=False,
        default=0,
    )

    budget_code = models.CharField(max_length=50, blank=True)
    expense_category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default="OTHER",
    )

    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["financial_year", "month", "task_code"]
        indexes = [
            models.Index(fields=["department", "financial_year"]),
            models.Index(fields=["department", "month"]),
        ]

    def __str__(self):
        owner_code = "UNASSIGNED"

        if self.department_unit and self.department_unit.code:
            owner_code = self.department_unit.code
        elif self.department and self.department.code:
            owner_code = self.department.code

        return f"{owner_code} - {self.task_code} - {self.task_in_mtef}"

    def clean(self):
        super().clean()

        budgeted_amount = self.budgeted_amount or Decimal("0.00")
        amount_disbursed = self.amount_disbursed or Decimal("0.00")
        monthly_proposed_amount = (
            self.monthly_proposed_amount or Decimal("0.00")
        )
        monthly_approved_amount = (
            self.monthly_approved_amount or Decimal("0.00")
        )

        if (
            self.department_unit_id
            and self.department_id
            and self.department_unit.department_id != self.department_id
        ):
            raise ValidationError(
                {
                    "department_unit": (
                        "The selected department unit does not belong "
                        "to the selected department."
                    )
                }
            )

        if self.finance_request_id:
            if (
                self.department_id
                and self.finance_request.department_id
                and self.department_id != self.finance_request.department_id
            ):
                raise ValidationError(
                    {
                        "finance_request": (
                            "The selected Finance Request belongs to a "
                            "different department."
                        )
                    }
                )

            if not self.department_id:
                self.department = self.finance_request.department

            if not self.department_unit_id:
                self.department_unit = self.finance_request.department_unit

        if budgeted_amount < 0:
            raise ValidationError(
                {"budgeted_amount": "Budgeted amount cannot be negative."}
            )

        if amount_disbursed < 0:
            raise ValidationError(
                {
                    "amount_disbursed": (
                        "Amount disbursed cannot be negative."
                    )
                }
            )

        if monthly_proposed_amount < 0:
            raise ValidationError(
                {
                    "monthly_proposed_amount": (
                        "Monthly proposed amount cannot be negative."
                    )
                }
            )

        if monthly_approved_amount < 0:
            raise ValidationError(
                {
                    "monthly_approved_amount": (
                        "Monthly approved amount cannot be negative."
                    )
                }
            )

        if monthly_approved_amount > monthly_proposed_amount:
            raise ValidationError(
                {
                    "monthly_approved_amount": (
                        "Monthly approved amount cannot exceed monthly "
                        "proposed amount."
                    )
                }
            )

        if monthly_proposed_amount > budgeted_amount:
            raise ValidationError(
                {
                    "monthly_proposed_amount": (
                        "Monthly proposed amount cannot exceed annual "
                        "budgeted amount."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.budgeted_amount = (
            self.budgeted_amount or Decimal("0.00")
        )
        self.amount_disbursed = (
            self.amount_disbursed or Decimal("0.00")
        )
        self.monthly_proposed_amount = (
            self.monthly_proposed_amount or Decimal("0.00")
        )
        self.monthly_approved_amount = (
            self.monthly_approved_amount or Decimal("0.00")
        )
        self.quantity = self.quantity or Decimal("0.00")
        self.unit_cost = self.unit_cost or Decimal("0.00")

        if self.finance_request_id:
            if not self.department_id:
                self.department = self.finance_request.department

            if not self.department_unit_id:
                self.department_unit = self.finance_request.department_unit

        self.total_cost = (
            self.quantity * self.unit_cost
            ).quantize(Decimal("0.01"))
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def monthly_balance(self):
        approved = (
            self.monthly_approved_amount or Decimal("0.00")
        )
        disbursed = self.amount_disbursed or Decimal("0.00")
        return approved - disbursed

    @property
    def monthly_variance(self):
        proposed = (
            self.monthly_proposed_amount
            or Decimal("0.00")
        )

        approved = (
            self.monthly_approved_amount
            or Decimal("0.00")
        )

        return proposed - approved


class ApprovalStep(models.Model):
    ACTION_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("RETURNED", "Returned"),
        ("COMMENTED", "Commented"),
    ]

    STEP_CHOICES = [
        ("HEAD_OF_UNIT", "Head of Unit"),
        ("ASSISTANT_DIRECTOR", "Assistant Director"),
        ("DIRECTOR", "Director"),
        ("DIVISION_BUDGET_OFFICER", "Division Budget Officer"),
        ("ACCOUNTANT", "Accountant"),
        ("FINAL_APPROVER", "Final Approver"),
    ]

    finance_request = models.ForeignKey(
        FinanceRequest,
        on_delete=models.CASCADE,
        related_name="approval_steps",
    )

    step_name = models.CharField(max_length=40, choices=STEP_CHOICES)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        default="PENDING",
    )
    comment = models.TextField(blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)
    sequence_no = models.PositiveIntegerField()

    class Meta:
        ordering = ["sequence_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["finance_request", "sequence_no"],
                name="unique_finance_request_approval_sequence",
            )
        ]

    def __str__(self):
        return f"{self.finance_request.request_no} - {self.step_name}"


class Disbursement(TimeStampedModel):
    METHOD_CHOICES = [
        ("BANK", "Bank"),
        ("CASH", "Cash"),
        ("MOBILE", "Mobile"),
        ("CHEQUE", "Cheque"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PAID", "Paid"),
        ("FAILED", "Failed"),
        ("REVERSED", "Reversed"),
    ]

    finance_request = models.ForeignKey(
        FinanceRequest,
        on_delete=models.CASCADE,
        related_name="disbursements",
    )

    disbursement_no = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    payment_reference = models.CharField(max_length=100, blank=True)

    disbursed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disbursements_made",
    )

    disbursed_at = models.DateTimeField(null=True, blank=True)
    recipient_name = models.CharField(max_length=255)
    recipient_account = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
    )
    notes = models.TextField(blank=True)

    def clean(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError(
                {"amount": "Disbursement amount must be greater than zero."}
            )

        existing_paid = sum(
            (
                item.amount
                for item in self.finance_request.disbursements.exclude(
                    pk=self.pk
                ).filter(status="PAID")
            ),
            Decimal("0.00"),
        )

        approved = self.finance_request.approved_amount or Decimal("0.00")
        if self.status == "PAID" and (existing_paid + self.amount) > approved:
            raise ValidationError(
                "Total disbursement cannot exceed approved amount."
            )


class Retirement(TimeStampedModel):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SUBMITTED", "Submitted"),
        ("VERIFIED", "Verified"),
        ("ACCEPTED", "Accepted"),
        ("REJECTED", "Rejected"),
        ("RETURNED", "Returned"),
    ]

    finance_request = models.OneToOneField(
        FinanceRequest,
        on_delete=models.CASCADE,
        related_name="retirement",
    )

    retirement_no = models.CharField(max_length=50, unique=True, blank=True)

    submitted_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="retirements_submitted",
    )

    amount_accounted = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    amount_unaccounted = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    refund_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="DRAFT",
    )
    summary = models.TextField(blank=True)

    supporting_file = models.FileField(
        upload_to="finance/retirements/supporting_docs/",
        null=True,
        blank=True,
    )

    submitted_at = models.DateTimeField(null=True, blank=True)

    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retirements_verified",
    )

    verified_at = models.DateTimeField(null=True, blank=True)

    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retirements_approved",
    )

    approved_at = models.DateTimeField(null=True, blank=True)

    def get_unit_code(self):
        if self.finance_request_id:
            if self.finance_request.department_unit:
                return self.finance_request.department_unit.code.upper()
            if self.finance_request.department:
                return self.finance_request.department.code.upper()

        profile = get_user_profile(self.submitted_by)
        if profile:
            department_unit = getattr(profile, "department_unit", None)
            if department_unit:
                return department_unit.code.upper()

            department = getattr(profile, "department", None)
            if department:
                return department.code.upper()

        return "GEN"

    def save(self, *args, **kwargs):
        if not self.retirement_no:
            unit_code = self.get_unit_code()
            prefix = f"RT-{unit_code}-"

            with transaction.atomic():
                latest = (
                    Retirement.objects.select_for_update()
                    .filter(retirement_no__startswith=prefix)
                    .order_by("-retirement_no")
                    .first()
                )

                sequence = 1
                if latest and latest.retirement_no:
                    try:
                        sequence = int(latest.retirement_no.rsplit("-", 1)[1]) + 1
                    except (IndexError, TypeError, ValueError):
                        sequence = (
                            Retirement.objects.filter(
                                retirement_no__startswith=prefix
                            ).count()
                            + 1
                        )

                self.retirement_no = f"{prefix}{sequence:04d}"
                super().save(*args, **kwargs)
                return

        super().save(*args, **kwargs)

    def __str__(self):
        return self.retirement_no


class RetirementLine(models.Model):
    retirement = models.ForeignKey(
        Retirement,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    description = models.CharField(max_length=255)
    receipt_no = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference_no = models.CharField(max_length=50, unique=True, blank=True)

    attachment = models.FileField(
        upload_to="finance/retirements/",
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.description


class FinanceDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ("MINUTE_SHEET", "Minute Sheet"),
        ("QUOTATION", "Quotation"),
        ("INVOICE", "Invoice"),
        ("RECEIPT", "Receipt"),
        ("PAYMENT_VOUCHER", "Payment Voucher"),
        ("APPROVAL_MEMO", "Approval Memo"),
        ("RETIREMENT_REPORT", "Retirement Report"),
        ("OTHER", "Other"),
    ]

    finance_request = models.ForeignKey(
        FinanceRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents",
    )

    minute_sheet = models.ForeignKey(
        MinuteSheet,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents",
    )

    retirement = models.ForeignKey(
        Retirement,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents",
    )

    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
    )
    file = models.FileField(upload_to="finance/documents/")

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        linked_records = sum(
            bool(value)
            for value in (
                self.finance_request_id,
                self.minute_sheet_id,
                self.retirement_id,
            )
        )
        if linked_records != 1:
            raise ValidationError(
                "A finance document must be linked to exactly one finance record."
            )

    def __str__(self):
        return f"{self.get_document_type_display()} - {self.id}"