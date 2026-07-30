from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import ExternalWorkRequest, GroupMember, UserProfile


class GroupMemberInline(admin.TabularInline):
    model = GroupMember
    extra = 0


@admin.register(ExternalWorkRequest)
class ExternalWorkRequestAdmin(admin.ModelAdmin):

    list_display = (
        "reference_no",
        "request_type_display",
        "requester",
        "requester_name",
        "destination",
        "status",
        "hou_approved_by",
        "director_approved_by",
        "created_at",
        "view_details_link",
        "edit_link",
    )

    list_filter = (
        "status",
        "is_group_request",
        "created_at",
        "start_time",
        "end_time",
    )

    search_fields = (
        "reference_no",
        "requester__username",
        "requester_name",
        "requester_employee_id",
        "purpose",
        "destination",
        "group_leader_name",
        "group_leader_employee_id",
        "acting_officer_name",
        "acting_officer_employee_id",
        "acting_officer_phone",
    )

    date_hierarchy = "created_at"

    readonly_fields = (
        "reference_no",
        "created_at",
        "updated_at",
        "hou_approved_at",
        "director_approved_at",
        "rejected_at",
        "returned_at",
    )

    inlines = [GroupMemberInline]

    fieldsets = (
        ("Request Information", {
            "fields": (
                "reference_no",
                "requester",
                "requester_name",
                "requester_employee_id",
                "purpose",
                "destination",
                "start_time",
                "end_time",
                "is_group_request",
            )
        }),

        ("Group Request", {
            "fields": (
                "group_leader_name",
                "group_leader_employee_id",
            )
        }),

        ("Acting Officer", {
            "fields": (
                "acting_officer_name",
                "acting_officer_employee_id",
                "acting_officer_phone",
            )
        }),

        ("Workflow Status", {
            "fields": (
                "status",
                "hou_comment",
                "director_comment",
            )
        }),

        ("Head of Unit Approval", {
            "fields": (
                "hou_approved_by",
                "hou_approved_at",
            )
        }),

        ("Director Approval", {
            "fields": (
                "director_approved_by",
                "director_approved_at",
            )
        }),

        ("Rejection Details", {
            "fields": (
                "rejected_by",
                "rejected_by_role",
                "rejected_at",
            )
        }),

        ("Files", {
            "fields": (
                "task_approval_file",
                "report_file",
            )
        }),

        ("Timestamps", {
            "fields": (
                "created_at",
                "updated_at",
                "returned_at",
                "resubmitted_at",
            )
        }),
    )

    def request_type_display(self, obj):
        return "Group" if obj.is_group_request else "Individual"

    request_type_display.short_description = "Request Type"

    def view_details_link(self, obj):
        url = reverse("request_detail", args=[obj.pk])
        return format_html('<a href="{}" target="_blank">View Details</a>', url)

    view_details_link.short_description = "Request Details"

    def edit_link(self, obj):
        url = reverse("admin:permits_externalworkrequest_change", args=[obj.pk])
        return format_html('<a href="{}">Edit</a>', url)

    edit_link.short_description = "Edit"


@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):

    list_display = (
        "full_name",
        "employee_id",
        "request",
    )

    search_fields = (
        "full_name",
        "employee_id",
        "request__reference_no",
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):

    list_display = (
        "user",
        "role",
        "employee_id",
        "check_number",
        "phone_number",
        "department",
        "department_unit",
        "head_of_unit",
    )

    list_filter = (
        "role",
        "department",
        "department_unit",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "employee_id",
        "check_number",
        "phone_number",
        "department__code",
        "department__name",
        "department_unit__code",
        "department_unit__name",
        "head_of_unit__username",
        "head_of_unit__first_name",
        "head_of_unit__last_name",
    )

    fields = (
        "user",
        "role",
        "approval_role",
        "employee_id",
        "check_number",
        "phone_number",
        "department",
        "department_unit",
        "head_of_unit",
    )