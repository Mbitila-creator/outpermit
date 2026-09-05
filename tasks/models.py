from django.db import models
from django.contrib.auth.models import User
from permits.models import Department, DepartmentUnit
from django.core.exceptions import ValidationError
from django.utils import timezone


class Task(models.Model):
    APPROVAL_STATUS_CHOICES = [
        ("NOT_REQUIRED", "Approval not required"),
        ("PENDING", "Pending approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]
    PRIORITY_CHOICES = [
        ("LOW", "Low"),
        ("MEDIUM", "Medium"),
        ("HIGH", "High"),
        ("URGENT", "Urgent"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("ON_HOLD", "On Hold"),
        ("CANCELLED", "Cancelled"),
        ("RETURNED", "Returned"),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_tasks")
    proposed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="proposed_tasks",
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="task_approval_requests",
    )
    approval_status = models.CharField(
        max_length=20, choices=APPROVAL_STATUS_CHOICES,
        default="NOT_REQUIRED", db_index=True,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    approval_decision_note = models.TextField(blank=True)

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks"
    )

    department_unit = models.ForeignKey(
        DepartmentUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks"
    )

    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="MEDIUM", db_index=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING", db_index=True)

    start_date = models.DateTimeField(blank=True, null=True)
    due_date = models.DateTimeField(blank=True, null=True, db_index=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    progress_percent = models.PositiveIntegerField(default=0)

    returned_reason = models.TextField(blank=True)
    returned_at = models.DateTimeField(blank=True, null=True)
    returned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="returned_tasks"
    )

    management_note = models.TextField(blank=True)
    management_note_updated_at = models.DateTimeField(blank=True, null=True)
    management_note_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_management_notes"
    )
    management_note_role = models.CharField(max_length=100, blank=True)

    attachment = models.FileField(upload_to="task_files/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        self.progress_percent = max(0, min(self.progress_percent or 0, 100))

        if self.status == "COMPLETED":
            self.progress_percent = 100
            if not self.completed_at:
                self.completed_at = timezone.now()
        else:
            self.completed_at = None

        if self.status == "RETURNED":
            if not self.returned_at:
                self.returned_at = timezone.now()
        else:
            self.returned_at = None
            self.returned_reason = ""
            self.returned_by = None

        super().save(*args, **kwargs)

    def refresh_from_assignments(self, save=True):
        self.refresh_from_db()

        if hasattr(self, "_prefetched_objects_cache"):
            self._prefetched_objects_cache = {}

        assignments = list(self.assignments.all().select_related("assigned_to"))

        if not assignments:
            self.progress_percent = 0
            self.status = "PENDING"
            self.completed_at = None
            self.returned_at = None
            self.returned_reason = ""
            self.returned_by = None

            if save:
                self.save(update_fields=[
                    "progress_percent",
                    "status",
                    "completed_at",
                    "returned_reason",
                    "returned_at",
                    "returned_by",
                    "updated_at",
                ])
            return

        def sort_key(a):
            return (a.last_updated_at or a.updated_at or a.assigned_at, a.id)

        latest = max(assignments, key=sort_key)

        current_assignments = [
            a for a in assignments
            if a.status in ["ASSIGNED", "ACCEPTED", "IN_PROGRESS", "COMPLETED"]
        ]

        if not current_assignments:
            returned_progress = min(
                100,
                (latest.carried_forward_progress or 0) + (latest.progress_percent or 0)
            )

            self.progress_percent = returned_progress
            self.status = "RETURNED"
            self.completed_at = None
            self.returned_at = latest.returned_at or timezone.now()
            self.returned_reason = latest.returned_reason or ""
            self.returned_by = latest.assigned_to

            if save:
                self.save(update_fields=[
                    "progress_percent",
                    "status",
                    "completed_at",
                    "returned_reason",
                    "returned_at",
                    "returned_by",
                    "updated_at",
                ])
            return

        effective_values = [
            min(100, (a.carried_forward_progress or 0) + (a.progress_percent or 0))
            for a in current_assignments
        ]

        overall_progress = round(sum(effective_values) / len(effective_values))
        self.progress_percent = overall_progress

        all_completed = all(a.status == "COMPLETED" for a in current_assignments)
        any_active = any(
            a.status in ["ASSIGNED", "ACCEPTED", "IN_PROGRESS"]
            for a in current_assignments
        )

        if all_completed or overall_progress >= 100:
            self.status = "COMPLETED"
            self.progress_percent = 100
            if not self.completed_at:
                self.completed_at = timezone.now()
            self.returned_at = None
            self.returned_reason = ""
            self.returned_by = None
        else:
            self.completed_at = None

            if self.status not in ["ON_HOLD", "CANCELLED"]:
                if overall_progress > 0 or any_active:
                    self.status = "IN_PROGRESS"
                else:
                    self.status = "PENDING"

            self.returned_at = None
            self.returned_reason = ""
            self.returned_by = None

        if save:
            self.save(update_fields=[
                "progress_percent",
                "status",
                "completed_at",
                "returned_reason",
                "returned_at",
                "returned_by",
                "updated_at",
            ])

    @property
    def is_overdue(self):
        return (
            self.due_date is not None
            and self.due_date < timezone.now()
            and self.status not in ["COMPLETED", "CANCELLED", "RETURNED"]
        )

    @property
    def assignment_count(self):
        return self.assignments.count()

    @property
    def completed_assignment_count(self):
        return self.assignments.filter(status="COMPLETED").count()

    def __str__(self):
        return self.title


class TaskAssignment(models.Model):
    ASSIGNMENT_STATUS_CHOICES = [
        ("ASSIGNED", "Assigned"),
        ("ACCEPTED", "Accepted"),
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("RETURNED", "Returned"),
    ]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignments")
    assigned_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name="task_assignments")
    assigned_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="task_assignments_made")
    is_group_leader = models.BooleanField(default=False, db_index=True)

    status = models.CharField(max_length=20, choices=ASSIGNMENT_STATUS_CHOICES, default="ASSIGNED")

    progress_percent = models.PositiveIntegerField(default=0)
    carried_forward_progress = models.PositiveIntegerField(default=0)

    returned_reason = models.TextField(blank=True)

    assigned_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    returned_at = models.DateTimeField(blank=True, null=True)
    last_updated_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("task", "assigned_to")
        constraints = [
            models.UniqueConstraint(
                fields=["task"],
                condition=models.Q(is_group_leader=True),
                name="unique_group_leader_per_task",
            ),
        ]

    @property
    def effective_progress(self):
        return min(100, (self.carried_forward_progress or 0) + (self.progress_percent or 0))

    @property
    def remaining_progress(self):
        return max(0, 100 - (self.carried_forward_progress or 0))

    @property
    def is_overdue(self):
        return (
            self.task.due_date is not None
            and self.task.due_date < timezone.now()
            and self.status not in ["COMPLETED", "RETURNED"]
        )

    def save(self, *args, **kwargs):
        now = timezone.now()

        self.carried_forward_progress = max(0, min(self.carried_forward_progress or 0, 100))
        self.progress_percent = max(0, self.progress_percent or 0)

        if self.progress_percent > self.remaining_progress:
            self.progress_percent = self.remaining_progress

        self.last_updated_at = now

        if self.status == "ACCEPTED" and not self.accepted_at:
            self.accepted_at = now

        if self.progress_percent > 0 and self.status in ["ASSIGNED", "ACCEPTED"]:
            self.status = "IN_PROGRESS"

        if self.status in ["IN_PROGRESS", "COMPLETED"] and not self.started_at:
            self.started_at = now

        if self.effective_progress >= 100:
            self.status = "COMPLETED"

        if self.status == "COMPLETED":
            self.progress_percent = self.remaining_progress
            if not self.completed_at:
                self.completed_at = now
            self.returned_at = None
            self.returned_reason = ""
        else:
            self.completed_at = None

        if self.status == "RETURNED":
            if not self.returned_at:
                self.returned_at = now
        else:
            self.returned_at = None
            self.returned_reason = ""

        super().save(*args, **kwargs)

        self.task.refresh_from_db()
        self.task.refresh_from_assignments()

    def __str__(self):
        return f"{self.task.title} -> {self.assigned_to.username}"


class CrossDepartmentTaskRequest(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending providing director approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    priority = models.CharField(
        max_length=20, choices=Task.PRIORITY_CHOICES, default="MEDIUM"
    )
    start_date = models.DateTimeField(blank=True, null=True)
    due_date = models.DateTimeField(blank=True, null=True)
    attachment = models.FileField(
        upload_to="task_cross_department_requests/", blank=True, null=True
    )
    requesting_department = models.ForeignKey(
        Department, on_delete=models.PROTECT,
        related_name="outgoing_cross_task_requests",
    )
    providing_department = models.ForeignKey(
        Department, on_delete=models.PROTECT,
        related_name="incoming_cross_task_requests",
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT,
        related_name="cross_task_requests_made",
    )
    providing_director = models.ForeignKey(
        User, on_delete=models.PROTECT,
        related_name="cross_task_requests_received",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="PENDING", db_index=True
    )
    decision_note = models.TextField(blank=True)
    decided_at = models.DateTimeField(blank=True, null=True)
    task = models.OneToOneField(
        Task, on_delete=models.SET_NULL, blank=True, null=True,
        related_name="cross_department_request",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        if (
            self.requesting_department_id
            and self.providing_department_id
            and self.requesting_department_id == self.providing_department_id
        ):
            raise ValidationError(
                "Use normal task assignment for staff in your own department."
            )
        if (
            self.providing_department_id
            and
            self.providing_director_id
            and getattr(self.providing_director, "profile", None)
            and self.providing_director.profile.department_id
            != self.providing_department_id
        ):
            raise ValidationError(
                "The providing director must belong to the providing department."
            )

    def __str__(self):
        return f"{self.requesting_department.code} → {self.providing_department.code}: {self.title}"


class TaskUpdate(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="updates")

    assignment = models.ForeignKey(
        TaskAssignment,
        on_delete=models.CASCADE,
        related_name="updates",
        blank=True,
        null=True
    )

    updated_by = models.ForeignKey(User, on_delete=models.CASCADE)

    comment = models.TextField()
    progress_percent = models.PositiveIntegerField(default=0)

    attachment = models.FileField(upload_to="task_updates/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.assignment and self.assignment.task_id != self.task_id:
            raise ValidationError("Assignment does not belong to this task.")

    def save(self, *args, **kwargs):
        self.progress_percent = max(0, min(self.progress_percent or 0, 100))

        if self.assignment:
            self.task = self.assignment.task

            max_allowed = self.assignment.remaining_progress
            new_progress = min(self.progress_percent, max_allowed)

            if new_progress > self.assignment.progress_percent:
                self.assignment.progress_percent = new_progress

            if self.assignment.status == "ASSIGNED":
                self.assignment.status = "ACCEPTED"

            if 0 < self.assignment.progress_percent < self.assignment.remaining_progress:
                if self.assignment.status in ["ASSIGNED", "ACCEPTED"]:
                    self.assignment.status = "IN_PROGRESS"

            if self.assignment.effective_progress >= 100:
                self.assignment.status = "COMPLETED"

            self.assignment.save()
            self.assignment.refresh_from_db()
            self.task.refresh_from_db()

        self.full_clean()
        super().save(*args, **kwargs)

        self.task.refresh_from_assignments()

    def __str__(self):
        return f"{self.task.title} update"
