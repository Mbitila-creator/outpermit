from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.references import generate_reference


class Department(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    has_units = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"


class DepartmentUnit(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="units"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sections",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["department__code", "code"]
        unique_together = ("department", "code")

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        if self.department:
            self.department.has_units = True
            self.department.save(update_fields=["has_units"])
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.parent_id == self.pk and self.pk is not None:
            raise ValidationError({"parent": "A unit cannot be its own parent."})
        if self.parent and self.parent.department_id != self.department_id:
            raise ValidationError(
                {"parent": "A parent unit must belong to the same department."}
            )

    def __str__(self):
        unit_code = (
            f"{self.parent.code}/{self.code}"
            if self.parent_id
            else self.code
        )
        return f"{self.department.code} - {unit_code} - {self.name}"


class ApprovalRole(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class DepartmentApprovalWorkflow(models.Model):
    MODULE_CHOICES = [
        ("PERMIT", "Permit"),
        ("TASK", "Task"),
        ("FINANCE", "Finance"),
        ("EVENT", "Event Management"),
    ]

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="approval_workflows"
    )
    module = models.CharField(max_length=30, choices=MODULE_CHOICES)
    step_order = models.PositiveIntegerField()
    approval_role = models.ForeignKey(
        ApprovalRole,
        on_delete=models.CASCADE,
        related_name="workflow_steps"
    )
    is_required = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["department__code", "module", "step_order"]
        unique_together = ("department", "module", "step_order")

    def __str__(self):
        return f"{self.department.code} - {self.module} - Step {self.step_order}: {self.approval_role.name}"


class ExternalWorkRequest(models.Model):
    STATUS_CHOICES = [
        ("PENDING_HOU", "Pending Head of Unit"),
        ("PENDING_DIRECTOR", "Pending Director"),
        ("RETURNED_HOU", "Returned by Head of Unit"),
        ("RETURNED_DIRECTOR", "Returned by Director"),
        ("APPROVED", "Approved"),
        ("REJECTED_HOU", "Rejected by Head of Unit"),
        ("REJECTED_DIRECTOR", "Rejected by Director"),
        ("CLOSED", "Closed"),
    ]

    reference_no = models.CharField(max_length=30, unique=True, blank=True)

    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="work_requests"
    )

    requester_name = models.CharField(max_length=150, blank=True)
    requester_employee_id = models.CharField(max_length=50, blank=True)

    purpose = models.CharField(max_length=200)
    destination = models.CharField(max_length=200)

    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField(db_index=True)

    is_group_request = models.BooleanField(default=False)

    group_leader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="group_leader_requests"
    )
    group_leader_name = models.CharField(max_length=150, blank=True)
    group_leader_employee_id = models.CharField(max_length=50, blank=True)

    acting_officer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acting_officer_requests"
    )
    acting_officer_name = models.CharField(max_length=150, blank=True)
    acting_officer_employee_id = models.CharField(max_length=50, blank=True)
    acting_officer_phone = models.CharField(max_length=30, blank=True)

    unit_name = models.CharField(max_length=20, blank=True, null=True, db_index=True)

    head_of_unit = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="head_of_unit_requests"
    )

    director = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="director_requests"
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="PENDING_DIRECTOR",
        db_index=True
    )

    hou_comment = models.TextField(blank=True)
    director_comment = models.TextField(blank=True)

    returned_at = models.DateTimeField(blank=True, null=True)
    resubmitted_at = models.DateTimeField(blank=True, null=True)

    hou_approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hou_approved_requests"
    )
    hou_approved_at = models.DateTimeField(null=True, blank=True)

    director_approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="director_approved_requests"
    )
    director_approved_at = models.DateTimeField(null=True, blank=True)

    rejected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_requests"
    )
    rejected_by_role = models.CharField(max_length=50, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    task_approval_file = models.FileField(
        upload_to="task_approvals/",
        blank=True,
        null=True
    )

    report_file = models.FileField(
        upload_to="reports/",
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def _generate_reference_no(self):
        department = None
        profile = getattr(self.requester, "profile", None)
        if profile:
            department = profile.department

        return generate_reference(
            model_class=ExternalWorkRequest,
            field_name="reference_no",
            module_code="PERMIT",
            department=department,
        )

    def save(self, *args, **kwargs):
        if self.group_leader:
            profile = getattr(self.group_leader, "profile", None)
            self.group_leader_name = (
                self.group_leader.get_full_name().strip()
                or self.group_leader.username
            )
            self.group_leader_employee_id = getattr(profile, "employee_id", "") or ""
        elif not self.group_leader:
            self.group_leader_name = self.group_leader_name or ""
            self.group_leader_employee_id = self.group_leader_employee_id or ""

        if self.acting_officer:
            profile = getattr(self.acting_officer, "profile", None)
            self.acting_officer_name = (
                self.acting_officer.get_full_name().strip()
                or self.acting_officer.username
            )
            self.acting_officer_employee_id = getattr(profile, "employee_id", "") or ""
            self.acting_officer_phone = getattr(profile, "phone_number", "") or ""
        elif not self.acting_officer:
            self.acting_officer_name = self.acting_officer_name or ""
            self.acting_officer_employee_id = self.acting_officer_employee_id or ""
            self.acting_officer_phone = self.acting_officer_phone or ""

        if not self.reference_no:
            self.reference_no = self._generate_reference_no()

        super().save(*args, **kwargs)

    @property
    def request_type_display(self):
        return "Group" if self.is_group_request else "Individual"

    @property
    def is_returned(self):
        return self.status in ["RETURNED_HOU", "RETURNED_DIRECTOR"]

    @property
    def is_rejected(self):
        return self.status in ["REJECTED_HOU", "REJECTED_DIRECTOR"]

    def __str__(self):
        return f"{self.reference_no} - {self.purpose}"


class GroupMember(models.Model):
    request = models.ForeignKey(
        ExternalWorkRequest,
        on_delete=models.CASCADE,
        related_name="members"
    )
    member_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_work_group_memberships"
    )
    full_name = models.CharField(max_length=150)
    employee_id = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if self.member_user:
            profile = getattr(self.member_user, "profile", None)
            self.full_name = (
                self.member_user.get_full_name().strip()
                or self.member_user.username
            )
            self.employee_id = getattr(profile, "employee_id", "") or ""
        else:
            self.full_name = self.full_name or ""
            self.employee_id = self.employee_id or ""

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.employee_id})"


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ("REQUESTER", "Requester"),
        ("ADMIN", "Admin"),
        ("DIRECTOR", "Director"),
        ("HEAD_OF_UNIT", "Head of Unit"),
        ("ASSISTANT_DIRECTOR",
        "Assistant Director",
        ),
        ("DIVISION_BUDGET_OFFICER",
        "Division Budget Officer",
        ),
        ("ACCOUNTANT",
        "Accountant",
        ),
        ("EVENT_ADMIN", "Event Administrator"),
        ("REGISTRATION_OFFICER", "Event Registration Officer"),
        ("ATTENDANCE_OFFICER", "Event Attendance Officer"),
        ("REPORT_OFFICER", "Event Reports Officer"),
    ]

    UNIT_CHOICES = [
        ("KTIU", "Knowledge Translation and Impact Unit"),
        ("IMCU", "Infrastructure Management and Coordination Unit"),
        ("LSU", "Linkage and Support Unit"),
        ("RICU", "Regional and International Cooperation Unit"),
        ("DTSU", "Digital Technologies and STEM Unit"),
        ("CCU", "Crosscutting Unit"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile"
    )


    role = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        default="REQUESTER",
    )

    approval_role = models.ForeignKey(
        ApprovalRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profiles"
    )

    employee_id = models.CharField(max_length=50, blank=True, null=True)
    check_number = models.CharField(max_length=50, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profiles"
    )

    department_unit = models.ForeignKey(
        DepartmentUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profiles"
    )

    unit_name = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        blank=True,
        null=True,
        db_index=True
    )

    head_of_unit = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_profiles_under_me"
    )

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class ModuleRoleAssignment(models.Model):
    """A user's additional responsibility inside one OutPermit module."""

    class Module(models.TextChoices):
        EVENT = "EVENT", "Event Management"
        FINANCE = "FINANCE", "Financial Management"
        TASK = "TASK", "Task Management"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="module_role_assignments",
    )
    module = models.CharField(max_length=20, choices=Module.choices)
    role_code = models.CharField(max_length=40)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="module_role_assignments",
    )
    is_active = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("user__username", "module")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "module", "role_code"),
                name="unique_user_module_role",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.module}: {self.role_code}"

    @property
    def role_label(self):
        return self.role_code.replace("_", " ").title()

    def save(self, *args, **kwargs):
        self.role_code = self.role_code.strip().upper()
        super().save(*args, **kwargs)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    profile, created = UserProfile.objects.get_or_create(user=instance)
    profile.save()
