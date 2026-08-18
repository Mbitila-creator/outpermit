from django.contrib import admin
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from events.models import Event

from .models import (
    Meeting,
    MeetingActionCompletionReview,
    MeetingActionItem,
    MeetingActionProgressUpdate,
    MeetingAgendaItem,
    MeetingAttendee,
    MeetingCommunicationLog,
    MeetingDecision,
    MeetingDocument,
    MeetingDocumentAcknowledgement,
    MeetingFeedback,
    MeetingMinutesReview,
    MeetingResource,
    MeetingResourceBooking,
    MeetingSeries,
    MeetingSeriesAgendaTemplate,
)


class AuditAdminMixin:
    readonly_fields = ("created_by", "updated_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not obj.pk or not obj.created_by:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for deleted in formset.deleted_objects:
            deleted.delete()
        for instance in instances:
            if not instance.pk or not instance.created_by:
                instance.created_by = request.user
            instance.updated_by = request.user
            instance.save()
        formset.save_m2m()


class MeetingAgendaItemInline(admin.TabularInline):
    model = MeetingAgendaItem
    extra = 0
    fields = (
        "item_number", "title_sw", "title_en", "presenter_name",
        "allocated_minutes", "is_active",
    )
    ordering = ("item_number",)


class MeetingDocumentInline(admin.TabularInline):
    model = MeetingDocument
    extra = 0
    fields = (
        "document_type", "title_sw", "version", "is_confidential", "is_active",
    )
    ordering = ("document_type", "title_sw", "-version")


class MeetingMinutesReviewInline(admin.TabularInline):
    model = MeetingMinutesReview
    extra = 0
    fields = ("action", "comment", "created_by", "created_at")
    readonly_fields = fields
    ordering = ("-created_at",)
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class MeetingResourceBookingInline(admin.TabularInline):
    model = MeetingResourceBooking
    extra = 0
    fields = (
        "resource", "quantity", "status", "notes", "confirmed_by",
        "confirmed_at", "is_active",
    )
    autocomplete_fields = ("resource", "confirmed_by")
    ordering = ("resource__name_sw",)


class MeetingAttendeeInline(admin.TabularInline):
    model = MeetingAttendee
    extra = 0
    fields = (
        "attendee_type", "user", "full_name", "organization",
        "preferred_language", "response_status", "attendance_status",
        "checked_in_at", "checked_in_by", "checkin_method", "is_active",
    )
    autocomplete_fields = ("user", "checked_in_by")
    ordering = ("full_name",)


class MeetingFeedbackInline(admin.TabularInline):
    model = MeetingFeedback
    extra = 0
    fields = (
        "attendee", "overall_rating", "organization_rating", "content_rating",
        "facilitation_rating", "venue_platform_rating", "is_anonymous",
        "submitted_at",
    )
    readonly_fields = fields
    ordering = ("-submitted_at",)
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class MeetingDecisionInline(admin.TabularInline):
    model = MeetingDecision
    extra = 0
    fields = (
        "decision_number", "agenda_item", "decision_sw", "status", "is_active",
    )
    ordering = ("decision_number",)


class MeetingActionItemInline(admin.TabularInline):
    model = MeetingActionItem
    extra = 0
    fields = (
        "action_number", "decision", "description_sw", "responsible_user",
        "responsible_name", "responsible_email", "due_date", "status", "is_active",
    )
    autocomplete_fields = ("responsible_user",)
    ordering = ("action_number",)


class MeetingSeriesAgendaTemplateInline(admin.TabularInline):
    model = MeetingSeriesAgendaTemplate
    extra = 0
    fields = (
        "item_number", "title_sw", "title_en", "presenter_name",
        "allocated_minutes", "is_active",
    )
    ordering = ("item_number",)


@admin.register(Meeting)
class MeetingAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "reference_number", "event", "series", "meeting_type", "attendance_mode",
        "meeting_date", "chairperson_name", "minutes_status", "attendee_total",
        "is_active",
    )
    list_filter = (
        "series", "meeting_type", "attendance_mode", "online_platform",
        "minutes_status", "event__status", "is_active",
    )
    search_fields = (
        "reference_number", "event__code", "event__title_sw", "event__title_en",
        "chairperson_name", "secretary_name",
    )
    autocomplete_fields = (
        "event", "series", "minutes_approved_by", "closed_by",
    )
    date_hierarchy = "event__starts_at"
    inlines = (
        MeetingAgendaItemInline,
        MeetingAttendeeInline,
        MeetingDecisionInline,
        MeetingActionItemInline,
        MeetingDocumentInline,
        MeetingMinutesReviewInline,
        MeetingResourceBookingInline,
        MeetingFeedbackInline,
    )
    fieldsets = (
        (_("Meeting information"), {"fields": (
            "event", "series", "reference_number", "meeting_type", "chairperson_name",
            "secretary_name", "quorum_required", "invitation_deadline", "is_active",
        )}),
        (_("Meeting objectives"), {"fields": ("objectives_sw", "objectives_en")}),
        (_("Online meeting access"), {"fields": (
            "attendance_mode", "online_platform", "online_join_url",
            "online_meeting_id", "online_passcode", "online_instructions_sw",
            "online_instructions_en",
        )}),
        (_("Secure meeting check-in"), {"fields": (
            "checkin_enabled", "checkin_opens_at", "checkin_closes_at",
        )}),
        (_("Evaluation and closure"), {"fields": (
            "evaluation_enabled", "evaluation_deadline", "closure_status",
            "closure_summary_sw", "closure_summary_en", "closed_by", "closed_at",
        )}),
        (_("Meeting minutes"), {"fields": (
            "minutes_status", "minutes_sw", "minutes_en", "minutes_document",
            "minutes_approved_by", "minutes_approved_at",
        )}),
        (_("Audit information"), {"fields": (
            "created_by", "updated_by", "created_at", "updated_at",
        ), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "event", "event__category",
        ).annotate(_attendee_total=Count("attendees"))

    @admin.display(description=_("meeting date"), ordering="event__starts_at")
    def meeting_date(self, obj):
        return obj.event.starts_at

    @admin.display(description=_("participants"), ordering="_attendee_total")
    def attendee_total(self, obj):
        return obj._attendee_total

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "event":
            kwargs["queryset"] = Event.objects.filter(
                category__code="MEETING",
            ).order_by("-starts_at")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if obj.minutes_status == Meeting.MinutesStatus.APPROVED:
            obj.minutes_approved_by = obj.minutes_approved_by or request.user
        super().save_model(request, obj, form, change)


@admin.register(MeetingSeries)
class MeetingSeriesAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "code", "name_sw", "frequency", "meeting_type", "attendance_mode",
        "chairperson_name", "venue", "is_active",
    )
    list_filter = (
        "frequency", "meeting_type", "attendance_mode", "online_platform",
        "is_active",
    )
    search_fields = ("code", "name_sw", "name_en", "chairperson_name")
    autocomplete_fields = ("venue",)
    inlines = (MeetingSeriesAgendaTemplateInline,)
    ordering = ("name_sw", "code")


@admin.register(MeetingAgendaItem)
class MeetingAgendaItemAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("meeting", "item_number", "title_sw", "presenter_name", "is_active")
    list_filter = ("meeting", "is_active")
    search_fields = ("meeting__reference_number", "title_sw", "title_en", "presenter_name")
    autocomplete_fields = ("meeting",)
    ordering = ("meeting", "item_number")


@admin.register(MeetingAttendee)
class MeetingAttendeeAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "full_name", "meeting", "attendee_type", "organization",
        "preferred_language", "response_status", "attendance_status",
        "checked_in_at", "checkin_method", "is_active",
    )
    list_filter = (
        "attendee_type", "preferred_language", "response_status",
        "attendance_status", "meeting", "is_active",
    )
    search_fields = (
        "full_name", "organization", "designation", "email", "phone_number",
        "meeting__reference_number",
    )
    autocomplete_fields = ("meeting", "user", "checked_in_by")


@admin.register(MeetingFeedback)
class MeetingFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "meeting", "attendee", "overall_rating", "is_anonymous", "submitted_at",
    )
    list_filter = ("overall_rating", "is_anonymous", "meeting", "submitted_at")
    search_fields = (
        "meeting__reference_number", "attendee__full_name", "comments",
        "recommendations",
    )
    autocomplete_fields = ("meeting", "attendee")
    readonly_fields = (
        "meeting", "attendee", "organization_rating", "content_rating",
        "facilitation_rating", "venue_platform_rating", "overall_rating",
        "comments", "recommendations", "is_anonymous", "submitted_at",
        "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MeetingDocument)
class MeetingDocumentAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "title_sw", "meeting", "document_type", "version", "is_confidential",
        "is_active", "created_at",
    )
    list_filter = ("document_type", "is_confidential", "is_active", "meeting")
    search_fields = (
        "title_sw", "title_en", "original_filename", "meeting__reference_number",
    )
    autocomplete_fields = ("meeting", "agenda_item")
    readonly_fields = AuditAdminMixin.readonly_fields + ("original_filename",)
    ordering = ("meeting", "document_type", "title_sw", "-version")


@admin.register(MeetingDocumentAcknowledgement)
class MeetingDocumentAcknowledgementAdmin(admin.ModelAdmin):
    list_display = ("document", "attendee", "acknowledged_at", "is_active")
    list_filter = ("acknowledged_at", "document__meeting", "is_active")
    search_fields = (
        "document__meeting__reference_number", "document__title_sw",
        "document__title_en", "attendee__full_name", "attendee__email",
    )
    readonly_fields = (
        "document", "attendee", "acknowledged_at", "created_by", "updated_by",
        "created_at", "updated_at", "is_active",
    )
    ordering = ("-acknowledged_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MeetingMinutesReview)
class MeetingMinutesReviewAdmin(admin.ModelAdmin):
    list_display = ("meeting", "action", "created_by", "created_at")
    list_filter = ("action", "created_at")
    search_fields = (
        "meeting__reference_number", "meeting__event__title_sw",
        "meeting__event__title_en", "comment", "created_by__username",
    )
    readonly_fields = (
        "meeting", "action", "comment", "created_by", "updated_by",
        "created_at", "updated_at", "is_active",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MeetingResource)
class MeetingResourceAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "code", "name_sw", "name_en", "total_quantity", "storage_location",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("code", "name_sw", "name_en", "storage_location")
    ordering = ("name_sw", "code")


@admin.register(MeetingResourceBooking)
class MeetingResourceBookingAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "meeting", "resource", "quantity", "status", "confirmed_by",
        "confirmed_at", "is_active",
    )
    list_filter = ("status", "resource", "is_active")
    search_fields = (
        "meeting__reference_number", "resource__code", "resource__name_sw",
        "resource__name_en",
    )
    autocomplete_fields = ("meeting", "resource", "confirmed_by")
    ordering = ("-meeting__event__starts_at", "resource__name_sw")


@admin.register(MeetingDecision)
class MeetingDecisionAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("meeting", "decision_number", "short_decision", "status", "is_active")
    list_filter = ("status", "meeting", "is_active")
    search_fields = ("meeting__reference_number", "decision_sw", "decision_en")
    autocomplete_fields = ("meeting", "agenda_item")
    ordering = ("meeting", "decision_number")

    @admin.display(description=_("decision"))
    def short_decision(self, obj):
        return obj.decision_sw[:90]


@admin.register(MeetingActionItem)
class MeetingActionItemAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "meeting", "action_number", "short_action", "responsible_name",
        "due_date", "status", "completion_percentage", "is_active",
    )
    list_filter = ("status", "due_date", "meeting", "is_active")
    search_fields = (
        "meeting__reference_number", "description_sw", "description_en",
        "responsible_name", "responsible_email",
    )
    autocomplete_fields = ("meeting", "decision", "responsible_user")
    ordering = ("meeting", "action_number")

    @admin.display(description=_("action"))
    def short_action(self, obj):
        return obj.description_sw[:90]


@admin.register(MeetingActionProgressUpdate)
class MeetingActionProgressUpdateAdmin(admin.ModelAdmin):
    list_display = (
        "action", "status", "completion_percentage", "reported_at",
        "created_by", "is_active",
    )
    list_filter = ("status", "reported_at", "action__meeting", "is_active")
    search_fields = (
        "action__meeting__reference_number", "action__description_sw",
        "action__description_en", "notes", "created_by__username",
    )
    readonly_fields = (
        "action", "status", "completion_percentage", "notes", "evidence_file",
        "original_filename", "reported_at", "created_by", "updated_by",
        "created_at", "updated_at", "is_active",
    )
    ordering = ("-reported_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MeetingActionCompletionReview)
class MeetingActionCompletionReviewAdmin(admin.ModelAdmin):
    list_display = (
        "action", "outcome", "reviewed_at", "created_by", "is_active",
    )
    list_filter = ("outcome", "reviewed_at", "action__meeting", "is_active")
    search_fields = (
        "action__meeting__reference_number", "action__description_sw",
        "action__description_en", "comment", "created_by__username",
    )
    readonly_fields = (
        "action", "outcome", "comment", "reviewed_at", "created_by",
        "updated_by", "created_at", "updated_at", "is_active",
    )
    ordering = ("-reviewed_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MeetingCommunicationLog)
class MeetingCommunicationLogAdmin(admin.ModelAdmin):
    list_display = (
        "meeting", "communication_type", "recipient_name", "recipient_email",
        "delivery_status", "sent_at",
    )
    list_filter = (
        "communication_type", "delivery_status", "sent_at", "meeting",
    )
    search_fields = (
        "meeting__reference_number", "recipient_name", "recipient_email",
        "subject", "message",
    )
    readonly_fields = (
        "meeting", "attendee", "action_item", "communication_type",
        "delivery_status", "recipient_name", "recipient_email", "subject",
        "message", "sent_at", "error_message", "created_by", "updated_by",
        "created_at", "updated_at",
    )
    ordering = ("-sent_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

