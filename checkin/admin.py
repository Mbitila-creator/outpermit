from django.contrib import admin

from .models import ParticipantCheckIn


@admin.register(ParticipantCheckIn)
class ParticipantCheckInAdmin(admin.ModelAdmin):
    change_list_template = "admin/checkin/participantcheckin/change_list.html"
    list_display = (
        "reference_number",
        "participant_name",
        "event_code",
        "checked_in_at",
        "checked_in_by",
        "method",
    )
    list_filter = (
        "submission__event_form__event",
        "method",
        "checked_in_at",
    )
    search_fields = (
        "submission__reference_number",
        "submission__badge_name",
        "submission__badge_organization",
        "submission__submitter_email",
        "submission__submitter_phone",
    )
    readonly_fields = (
        "submission",
        "checked_in_by",
        "checked_in_at",
        "method",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    list_select_related = (
        "submission",
        "submission__event_form__event",
        "checked_in_by",
    )
    date_hierarchy = "checked_in_at"

    @admin.display(description="Reference number")
    def reference_number(self, obj):
        return obj.submission.reference_number

    @admin.display(description="Participant")
    def participant_name(self, obj):
        return obj.submission.badge_display_name

    @admin.display(description="Event")
    def event_code(self, obj):
        return obj.submission.event_form.event.code

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

