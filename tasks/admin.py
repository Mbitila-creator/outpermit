from django.contrib import admin
from django.utils import timezone
from .models import (
    Task, TaskAssignment, TaskUpdate, CrossDepartmentTaskRequest,
)


# --------------------------------------------------
# Inlines
# --------------------------------------------------
class TaskAssignmentInline(admin.TabularInline):
    model = TaskAssignment
    extra = 0
    readonly_fields = (
        "assigned_at",
        "accepted_at",
        "started_at",
        "completed_at",
        "returned_at",
        "last_updated_at",
        "is_overdue_display",
    )
    fields = (
        "assigned_to",
        "assigned_by",
        "is_group_leader",
        "status",
        "progress_percent",
        "assigned_at",
        "accepted_at",
        "started_at",
        "completed_at",
        "returned_at",
        "last_updated_at",
        "is_overdue_display",
    )

    def is_overdue_display(self, obj):
        if not obj or not obj.pk or not obj.task:
            return False
        return (
            obj.task.due_date is not None
            and obj.task.due_date < timezone.now()
            and obj.status not in ["COMPLETED", "RETURNED"]
        )
    is_overdue_display.boolean = True
    is_overdue_display.short_description = "Overdue"


class TaskUpdateInline(admin.TabularInline):
    model = TaskUpdate
    extra = 0
    readonly_fields = ("created_at",)
    fields = (
        "updated_by",
        "assignment",
        "progress_percent",
        "comment",
        "created_at",
    )


# --------------------------------------------------
# Task Admin
# --------------------------------------------------
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "created_by",
        "approval_status",
        "department_unit",
        "priority",
        "status",
        "progress_percent",
        "assignment_summary",
        "management_note_updated_at",
        "due_date",
        "is_overdue_display",
        "created_at",
    )

    list_filter = (
        "priority",
        "status",
        "department",
        "department_unit",
        "created_at",
        "due_date",
        "management_note_updated_at",
    )

    search_fields = (
        "title",
        "description",
        "management_note",
        "created_by__username",
        "created_by__first_name",
        "created_by__last_name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "completed_at",
        "management_note_updated_at",
        "approved_at",
        "is_overdue_display",
    )

    fields = (
        "title",
        "description",
        "created_by",
        "proposed_by",
        "approver",
        "approval_status",
        "approved_at",
        "approval_decision_note",
        "department",
        "department_unit",
        "priority",
        "status",
        "progress_percent",
        "start_date",
        "due_date",
        "completed_at",
        "management_note",
        "management_note_updated_at",
        "attachment",
        "is_overdue_display",
        "created_at",
        "updated_at",
    )

    inlines = [TaskAssignmentInline, TaskUpdateInline]

    def assignment_summary(self, obj):
        return f"{obj.completed_assignment_count}/{obj.assignment_count}"
    assignment_summary.short_description = "Completed"

    def is_overdue_display(self, obj):
        return (
            obj.due_date is not None
            and obj.due_date < timezone.now()
            and obj.status not in ["COMPLETED", "CANCELLED", "RETURNED"]
        )
    is_overdue_display.boolean = True
    is_overdue_display.short_description = "Overdue"


# --------------------------------------------------
# Task Assignment Admin
# --------------------------------------------------
@admin.register(TaskAssignment)
class TaskAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "task",
        "assigned_to",
        "assigned_by",
        "is_group_leader",
        "status",
        "progress_percent",
        "is_overdue_display",
        "assigned_at",
        "accepted_at",
        "started_at",
        "completed_at",
        "last_updated_at",
    )

    list_filter = (
        "is_group_leader",
        "status",
        "assigned_at",
        "accepted_at",
        "completed_at",
    )

    search_fields = (
        "task__title",
        "assigned_to__username",
        "assigned_to__first_name",
        "assigned_to__last_name",
        "assigned_by__username",
    )

    readonly_fields = (
        "assigned_at",
        "accepted_at",
        "started_at",
        "completed_at",
        "returned_at",
        "last_updated_at",
        "is_overdue_display",
    )

    fields = (
        "task",
        "assigned_to",
        "assigned_by",
        "status",
        "progress_percent",
        "carried_forward_progress",
        "returned_reason",
        "assigned_at",
        "accepted_at",
        "started_at",
        "completed_at",
        "returned_at",
        "last_updated_at",
        "is_overdue_display",
    )

    def is_overdue_display(self, obj):
        if not obj.task:
            return False
        return (
            obj.task.due_date is not None
            and obj.task.due_date < timezone.now()
            and obj.status not in ["COMPLETED", "RETURNED"]
        )
    is_overdue_display.boolean = True
    is_overdue_display.short_description = "Overdue"


@admin.register(CrossDepartmentTaskRequest)
class CrossDepartmentTaskRequestAdmin(admin.ModelAdmin):
    list_display = (
        "title", "requesting_department", "providing_department",
        "requested_by", "providing_director", "status", "created_at",
    )
    list_filter = ("status", "requesting_department", "providing_department")
    search_fields = (
        "title", "requested_by__username", "providing_director__username",
    )
    readonly_fields = ("created_at", "updated_at", "decided_at", "task")


# --------------------------------------------------
# Task Update Admin
# --------------------------------------------------
@admin.register(TaskUpdate)
class TaskUpdateAdmin(admin.ModelAdmin):
    list_display = (
        "task",
        "assignment",
        "updated_by",
        "progress_percent",
        "created_at",
    )

    list_filter = ("created_at",)

    search_fields = (
        "task__title",
        "updated_by__username",
        "updated_by__first_name",
        "updated_by__last_name",
        "comment",
    )

    readonly_fields = ("created_at",)
