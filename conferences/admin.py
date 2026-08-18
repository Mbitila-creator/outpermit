from django.contrib import admin

from .models import (
    ConferenceCallForPapers,
    ConferencePaper,
    ConferencePaperReview,
    ConferencePaperReviewAssignment,
    ConferenceProgrammeContributor,
    ConferenceProgrammeItem,
    ConferenceSession,
    ConferenceSessionAttendance,
    ConferenceGuidingTopic,
    ConferenceGuidingQuestion,
    ConferenceGuidingResponse,
    ConferenceGuidingSubmission,
    ConferenceSpeaker,
    ConferenceReviewer,
    ConferencePresentation,
    ConferencePaperCommunication,
    ConferenceCertificate,
    ConferenceFeedback,
)


class AuditAdminMixin:
    readonly_fields = ("created_by", "updated_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not obj.pk or not obj.created_by:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


class ConferenceGuidingQuestionInline(admin.TabularInline):
    model = ConferenceGuidingQuestion
    extra = 0


@admin.register(ConferenceGuidingTopic)
class ConferenceGuidingTopicAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("title", "session", "display_order", "is_active")
    list_filter = ("session__event", "session", "is_active")
    search_fields = ("title", "session__title", "session__event__code")
    inlines = (ConferenceGuidingQuestionInline,)


@admin.register(ConferenceGuidingQuestion)
class ConferenceGuidingQuestionAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("text", "topic", "display_order", "is_active")
    list_filter = ("topic__session__event", "topic__session", "is_active")
    search_fields = ("text", "topic__title")


@admin.register(ConferenceGuidingResponse)
class ConferenceGuidingResponseAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("submission", "question", "updated_at", "is_active")
    list_filter = ("question__topic__session__event", "question__topic__session")
    search_fields = ("submission__reference_number", "response", "question__text")
    readonly_fields = AuditAdminMixin.readonly_fields + ("submission", "question")


@admin.register(ConferenceGuidingSubmission)
class ConferenceGuidingSubmissionAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("submission", "session", "status", "submitted_at", "updated_at")
    list_filter = ("status", "session__event", "session")
    search_fields = ("submission__reference_number", "session__title")
    readonly_fields = AuditAdminMixin.readonly_fields + ("submission", "session", "submitted_at")


@admin.register(ConferenceSession)
class ConferenceSessionAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("code", "title", "event", "starts_at", "ends_at", "is_active")
    list_filter = ("event", "is_active")
    search_fields = ("code", "title", "event__code", "event__title_en")
    ordering = ("event", "starts_at", "display_order")


@admin.register(ConferenceSessionAttendance)
class ConferenceSessionAttendanceAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "submission",
        "session",
        "checked_in_at",
        "checked_in_by",
        "method",
    )
    list_filter = ("session__event", "session", "method", "checked_in_at")
    search_fields = (
        "submission__reference_number",
        "submission__badge_name",
        "submission__badge_organization",
    )
    autocomplete_fields = ("submission", "session", "checked_in_by")
    readonly_fields = AuditAdminMixin.readonly_fields + ("checked_in_at",)


class ConferenceProgrammeContributorInline(admin.TabularInline):
    model = ConferenceProgrammeContributor
    extra = 1
    autocomplete_fields = ("speaker",)
    fields = ("speaker", "role", "display_order", "is_active")


@admin.register(ConferenceSpeaker)
class ConferenceSpeakerAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "full_name",
        "position_title",
        "institution",
        "event",
        "is_active",
    )
    list_filter = ("event", "is_active")
    search_fields = (
        "full_name",
        "position_title",
        "institution",
        "event__code",
    )
    ordering = ("event", "display_order", "full_name")


@admin.register(ConferenceProgrammeItem)
class ConferenceProgrammeItemAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "title",
        "session",
        "item_type",
        "starts_at",
        "ends_at",
        "is_published",
        "is_active",
    )
    list_filter = (
        "session__event",
        "session",
        "item_type",
        "is_published",
        "is_active",
    )
    search_fields = (
        "code",
        "title",
        "description",
        "session__title",
        "session__event__code",
    )
    ordering = ("session__event", "starts_at", "display_order")
    inlines = (ConferenceProgrammeContributorInline,)


@admin.register(ConferenceProgrammeContributor)
class ConferenceProgrammeContributorAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("speaker", "programme_item", "role", "is_active")
    list_filter = ("programme_item__session__event", "role", "is_active")
    search_fields = (
        "speaker__full_name",
        "programme_item__title",
        "programme_item__session__event__code",
    )
    autocomplete_fields = ("speaker", "programme_item")


@admin.register(ConferenceCallForPapers)
class ConferenceCallForPapersAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("title", "event", "opens_at", "closes_at", "is_published")
    list_filter = ("is_published", "event")
    search_fields = ("title", "event__code", "event__title_en")


class ConferencePaperReviewInline(admin.TabularInline):
    model = ConferencePaperReview
    extra = 0
    readonly_fields = (
        "decision", "message_to_author", "internal_notes", "assigned_session",
        "reviewer", "created_at",
    )
    fields = readonly_fields
    can_delete = False


@admin.register(ConferencePaper)
class ConferencePaperAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "reference_number", "title", "corresponding_author", "submission_type",
        "status", "assigned_session", "created_at",
    )
    list_filter = ("call__event", "status", "submission_type", "presentation_format")
    search_fields = (
        "reference_number", "title", "corresponding_author", "institution", "email",
    )
    readonly_fields = AuditAdminMixin.readonly_fields + (
        "public_token", "reference_number", "reviewed_by", "reviewed_at",
    )
    autocomplete_fields = ("assigned_session",)
    inlines = (ConferencePaperReviewInline,)


@admin.register(ConferencePaperReview)
class ConferencePaperReviewAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("paper", "decision", "reviewer", "assigned_session", "created_at")
    list_filter = ("decision", "paper__call__event")
    search_fields = ("paper__reference_number", "paper__title", "reviewer__username")
    autocomplete_fields = ("paper", "assigned_session", "reviewer")


@admin.register(ConferenceReviewer)
class ConferenceReviewerAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("user", "event", "institution", "is_active")
    list_filter = ("event", "is_active")
    search_fields = (
        "user__username", "user__first_name", "user__last_name",
        "user__email", "institution", "expertise",
    )
    autocomplete_fields = ("user", "event")


@admin.register(ConferencePaperReviewAssignment)
class ConferencePaperReviewAssignmentAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "paper", "reviewer", "status", "average_score_display",
        "recommendation", "due_at", "submitted_at",
    )
    list_filter = ("paper__call__event", "status", "recommendation")
    search_fields = (
        "paper__reference_number", "paper__title", "reviewer__user__username",
        "reviewer__user__first_name", "reviewer__user__last_name",
    )
    autocomplete_fields = ("paper", "reviewer", "assigned_by")
    readonly_fields = AuditAdminMixin.readonly_fields + ("submitted_at",)

    @admin.display(description="Average score")
    def average_score_display(self, obj):
        return f"{obj.average_score:.1f}" if obj.average_score is not None else "—"


@admin.register(ConferencePresentation)
class ConferencePresentationAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "paper", "presenter_name", "session", "starts_at", "ends_at", "status",
    )
    list_filter = ("paper__call__event", "session", "status")
    search_fields = (
        "paper__reference_number", "paper__title", "presenter_name", "venue_name",
    )
    autocomplete_fields = ("paper", "session", "programme_item")
    readonly_fields = AuditAdminMixin.readonly_fields + ("confirmed_at",)


@admin.register(ConferencePaperCommunication)
class ConferencePaperCommunicationAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "paper", "communication_type", "recipient_email", "delivery_status", "sent_at",
    )
    list_filter = ("paper__call__event", "communication_type", "delivery_status")
    search_fields = ("paper__reference_number", "recipient_email", "subject", "message")
    readonly_fields = AuditAdminMixin.readonly_fields + (
        "delivery_status", "sent_by", "sent_at", "failure_message",
    )


@admin.register(ConferenceCertificate)
class ConferenceCertificateAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "certificate_number", "recipient_name", "recipient_type", "event",
        "issued_at", "is_revoked",
    )
    list_filter = ("event", "recipient_type", "is_revoked", "issued_at")
    search_fields = ("certificate_number", "recipient_name", "institution", "event__code")
    readonly_fields = AuditAdminMixin.readonly_fields + (
        "certificate_number", "verification_token", "issued_by", "issued_at",
    )
    autocomplete_fields = ("participant_submission", "paper", "reviewer")

    def has_add_permission(self, request):
        return False


@admin.register(ConferenceFeedback)
class ConferenceFeedbackAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "reference_number", "event", "session", "display_name", "overall_rating",
        "would_recommend", "created_at",
    )
    list_filter = ("event", "session", "is_anonymous", "would_recommend", "created_at")
    search_fields = (
        "reference_number", "respondent_name", "institution", "email",
        "most_valuable", "improvements", "additional_comments",
    )
    readonly_fields = AuditAdminMixin.readonly_fields + (
        "reference_number", "public_token",
    )
    autocomplete_fields = ("event", "session")

