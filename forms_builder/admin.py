import csv

from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from events.auth import User, has_event_role

from .models import (
    Booth,
    BoothInterest,
    BoothOffering,
    EventForm,
    EventReminder,
    FormAnswer,
    FormQuestion,
    FormSection,
    FormSubmission,
    NotificationLog,
    Payment,
    Participant,
    CertificateRecord,
    QuantityPricingRule,
    QuestionOption,
)
from .notifications import (
    process_event_reminder,
    resend_notification,
    send_submission_notification,
    send_payment_notification,
)
from .services import (
    booth_detail_url,
    generate_qr_png,
    public_form_path,
    public_form_url,
    participant_badge_path,
    participant_certificate_path,
    certificate_number,
    submissions_csv,
    safe_spreadsheet_value,
)
from learning_events.services import certificate_eligibility_for_submission


class AuditAdminMixin:
    readonly_fields = (
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )

    def save_model(self, request, obj, form, change):
        if not obj.pk or not obj.created_by:
            obj.created_by = request.user

        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


class SubmissionFormFilter(admin.SimpleListFilter):
    """Form filter that narrows its choices when an event filter is selected."""

    title = _("form")
    parameter_name = "form_id"

    def lookups(self, request, model_admin):
        forms = EventForm.objects.select_related("event")
        event_id = (
            request.GET.get("event_form__event__id__exact")
            or request.GET.get("event_form__event")
        )
        if event_id and str(event_id).isdigit():
            forms = forms.filter(event_id=event_id)
        return [
            (form.pk, f"{form.event.code} — {form.name_en}")
            for form in forms.order_by("event__code", "name_en")
        ]

    def queryset(self, request, queryset):
        return queryset.filter(event_form_id=self.value()) if self.value() else queryset


@admin.register(QuantityPricingRule)
class QuantityPricingRuleAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "event", "quantity_question", "first_unit_amount",
        "additional_unit_amount", "currency", "is_active",
    )
    list_filter = ("event", "currency", "is_active")
    search_fields = (
        "event__code", "event__title_sw", "event__title_en",
        "quantity_question__label_sw", "quantity_question__label_en",
    )
    autocomplete_fields = ("quantity_question",)


@admin.register(Payment)
class PaymentAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "submission", "amount", "currency", "method", "transaction_reference",
        "paid_at", "status", "verified_by", "receipt_tools",
    )
    list_filter = ("status", "method", "currency", "submission__event_form__event")
    search_fields = (
        "submission__reference_number", "submission__badge_name",
        "transaction_reference", "submission__submitter_email",
    )
    readonly_fields = AuditAdminMixin.readonly_fields + ("verified_by", "verified_at")
    autocomplete_fields = ("submission",)
    actions = ("verify_selected", "reject_selected")

    def _set_status(self, request, queryset, status):
        queryset = queryset.exclude(status=status)
        payments = list(queryset.select_related("submission__event_form__event"))
        verified = status == Payment.Status.VERIFIED
        queryset.update(
            status=status,
            verified_by=request.user if verified else None,
            verified_at=timezone.now() if verified else None,
            updated_by=request.user,
            updated_at=timezone.now(),
        )
        notification_type = (
            NotificationLog.NotificationType.PAYMENT_VERIFIED
            if verified
            else NotificationLog.NotificationType.PAYMENT_REJECTED
        )
        for payment in payments:
            payment.status = status
            send_payment_notification(
                payment, notification_type, request=request,
            )

    @admin.display(description=_("Receipt"))
    def receipt_tools(self, obj):
        if obj.status != Payment.Status.VERIFIED:
            return _("Available after verification.")
        url = reverse(
            "forms_builder:payment_receipt",
            kwargs={"participant_token": obj.submission.participant_token},
        )
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">{}</a>',
            url, _("Open receipt"),
        )

    @admin.action(description=_("Verify selected payments"))
    def verify_selected(self, request, queryset):
        self._set_status(request, queryset, Payment.Status.VERIFIED)

    @admin.action(description=_("Reject selected payments"))
    def reject_selected(self, request, queryset):
        self._set_status(request, queryset, Payment.Status.REJECTED)

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = Payment.objects.filter(pk=obj.pk).values_list(
                "status", flat=True,
            ).first()
        if obj.status == Payment.Status.VERIFIED:
            obj.verified_by = request.user
            obj.verified_at = timezone.now()
        elif obj.status != previous_status:
            obj.verified_by = None
            obj.verified_at = None
        super().save_model(request, obj, form, change)
        if obj.status != previous_status and obj.status in {
            Payment.Status.VERIFIED, Payment.Status.REJECTED,
        }:
            notification_type = (
                NotificationLog.NotificationType.PAYMENT_VERIFIED
                if obj.status == Payment.Status.VERIFIED
                else NotificationLog.NotificationType.PAYMENT_REJECTED
            )
            send_payment_notification(
                obj, notification_type, request=request,
            )


class BoothOfferingInline(admin.StackedInline):
    model = BoothOffering
    extra = 0
    fields = (
        "offering_type",
        "name_sw",
        "name_en",
        "description_sw",
        "description_en",
        "display_order",
        "is_active",
    )


@admin.register(Booth)
class BoothAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "name_en",
        "event",
        "zone_en",
        "assigned_exhibitor",
        "status",
        "public_tools",
        "interest_count",
        "is_active",
    )
    list_filter = (
        "event",
        "status",
        "is_active",
    )
    search_fields = (
        "code",
        "name_sw",
        "name_en",
        "zone_sw",
        "zone_en",
        "assigned_submission__reference_number",
        "assigned_submission__badge_name",
        "assigned_submission__badge_organization",
    )
    autocomplete_fields = ("assigned_submission",)
    readonly_fields = AuditAdminMixin.readonly_fields + (
        "public_token",
        "public_tools",
    )
    list_select_related = (
        "event",
        "assigned_submission",
        "assigned_submission__event_form",
    )
    inlines = [BoothOfferingInline]

    @admin.display(description="Assigned exhibitor")
    def assigned_exhibitor(self, obj):
        if not obj.assigned_submission:
            return "Unassigned"
        return format_html(
            "<strong>{}</strong><br><small>{}</small>",
            obj.assigned_submission.badge_display_name,
            obj.assigned_submission.reference_number,
        )

    @admin.display(description="Visitor interests")
    def interest_count(self, obj):
        return obj.interests.count()

    @admin.display(description="Public page and QR")
    def public_tools(self, obj):
        if not obj or not obj.pk:
            return "Save the booth first."
        if (
            not obj.is_active
            or not obj.assigned_submission
            or obj.status not in {Booth.Status.ASSIGNED, Booth.Status.READY}
            or not obj.event.booth_enabled
        ):
            return "Available after an active booth is assigned."
        detail_url = booth_detail_url(obj, language="sw")
        qr_url = reverse(
            "forms_builder:booth_qr",
            kwargs={"public_token": obj.public_token},
        )
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Open page</a>'
            ' &nbsp;|&nbsp; '
            '<a href="{}" target="_blank" rel="noopener">View QR</a>'
            ' &nbsp;|&nbsp; '
            '<a href="{}?download=1">Download QR</a>',
            detail_url,
            qr_url,
            qr_url,
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assigned_submission":
            kwargs["queryset"] = FormSubmission.objects.filter(
                review_status=FormSubmission.ReviewStatus.APPROVED,
                is_active=True,
                is_complete=True,
                event_form__form_type__in=[
                    EventForm.FormType.REGISTRATION,
                    EventForm.FormType.EXHIBITOR,
                ],
            ).select_related("event_form__event")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(BoothOffering)
class BoothOfferingAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "name_en",
        "booth",
        "offering_type",
        "display_order",
        "is_active",
    )
    list_filter = (
        "booth__event",
        "offering_type",
        "is_active",
    )
    search_fields = (
        "name_sw",
        "name_en",
        "description_sw",
        "description_en",
        "booth__code",
        "booth__name_en",
    )
    list_select_related = ("booth", "booth__event")


@admin.register(BoothInterest)
class BoothInterestAdmin(admin.ModelAdmin):
    list_display = (
        "visitor_name",
        "booth",
        "offering",
        "email",
        "phone",
        "created_at",
    )
    list_filter = (
        "booth__event",
        "booth",
        "offering__offering_type",
        "language",
        "created_at",
    )
    search_fields = (
        "visitor_name",
        "email",
        "phone",
        "message",
        "booth__code",
        "booth__name_en",
        "offering__name_en",
    )
    readonly_fields = (
        "booth",
        "offering",
        "visitor_name",
        "email",
        "phone",
        "message",
        "language",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    list_select_related = ("booth", "booth__event", "offering")
    actions = ("export_interests_csv",)

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Export selected visitor interests to CSV"))
    def export_interests_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response.write("\ufeff")
        response["Content-Disposition"] = (
            'attachment; filename="booth-visitor-interests.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                _("Event"),
                _("Booth"),
                _("Offering"),
                _("Visitor name"),
                _("Email"),
                _("Phone"),
                _("Message"),
                _("Submitted on"),
            ]
        )
        for interest in queryset.select_related(
            "booth__event",
            "offering",
        ):
            writer.writerow(
                [
                    safe_spreadsheet_value(interest.booth.event.code),
                    safe_spreadsheet_value(interest.booth.code),
                    safe_spreadsheet_value(
                        interest.offering.name_en if interest.offering else ""
                    ),
                    safe_spreadsheet_value(interest.visitor_name),
                    safe_spreadsheet_value(interest.email),
                    safe_spreadsheet_value(interest.phone),
                    safe_spreadsheet_value(interest.message),
                    safe_spreadsheet_value(interest.created_at.isoformat()),
                ]
            )
        return response


class FormSectionInline(admin.TabularInline):
    model = FormSection
    extra = 0
    fields = (
        "title_sw",
        "title_en",
        "display_order",
        "condition_question",
        "condition_value",
        "is_active",
    )


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 0
    fields = (
        "value",
        "label_sw",
        "label_en",
        "display_order",
        "is_active",
    )


@admin.register(EventForm)
class EventFormAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "name_sw",
        "event",
        "form_type",
        "is_published",
        "registration_tools",
        "submission_tools",
        "requires_login",
        "is_active",
    )

    list_filter = (
        "form_type",
        "is_published",
        "requires_login",
        "allow_multiple_submissions",
        "is_active",
    )

    search_fields = (
        "name_sw",
        "name_en",
        "event__code",
        "event__title_sw",
        "event__title_en",
    )

    readonly_fields = AuditAdminMixin.readonly_fields + (
        "slug",
        "registration_tools",
    )

    inlines = [
        FormSectionInline,
    ]

    @admin.display(description="Public link and QR code")
    def registration_tools(self, obj):
        if not obj or not obj.pk:
            return "Save the form first."

        if not obj.is_published or not obj.is_active:
            return "Publish and activate the form first."

        public_url = public_form_path(obj)
        if obj.requires_participant_registration:
            return format_html(
                '<a href="{}?preview=1" target="_blank" rel="noopener">'
                'Preview form</a>'
                '<br><small>Participants access this form from their '
                'participant portal. A generic public QR code is not used.'
                '</small>',
                public_url,
            )
        qr_url = reverse(
            "admin:forms_builder_eventform_qr_code",
            args=[obj.pk],
        )
        download_url = f"{qr_url}?download=1"

        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Open form</a>'
            ' &nbsp;|&nbsp; '
            '<a href="{}" target="_blank" rel="noopener">View QR</a>'
            ' &nbsp;|&nbsp; '
            '<a href="{}">Download QR</a>',
            public_url,
            qr_url,
            download_url,
        )

    @admin.display(description="Submissions")
    def submission_tools(self, obj):
        submission_url = reverse("admin:forms_builder_formsubmission_changelist")
        if obj.form_type == EventForm.FormType.EVALUATION:
            report_url = reverse("forms_builder:evaluation_reports")
            return format_html(
                '<a href="{}?form_id={}">Find submissions</a>'
                ' &nbsp;|&nbsp; <a href="{}?form={}">Evaluation report</a>',
                submission_url, obj.pk, report_url, obj.pk,
            )
        return format_html(
            '<a href="{}?form_id={}">Find submissions</a>',
            submission_url, obj.pk,
        )

    def get_urls(self):
        custom_urls = [
            path(
                "<int:form_id>/qr-code/",
                self.admin_site.admin_view(self.qr_code_view),
                name="forms_builder_eventform_qr_code",
            ),
        ]
        return custom_urls + super().get_urls()

    def qr_code_view(self, request, form_id):
        event_form = get_object_or_404(
            EventForm.objects.select_related("event"),
            pk=form_id,
            is_active=True,
            is_published=True,
        )
        registration_url = public_form_url(
            event_form,
            request=request,
            language="sw",
        )
        image_data = generate_qr_png(registration_url)
        response = HttpResponse(image_data, content_type="image/png")

        if request.GET.get("download") == "1":
            filename = (
                f"{event_form.event.code}-"
                f"{event_form.slug}-form-qr.png"
            )
            response["Content-Disposition"] = (
                f'attachment; filename="{filename}"'
            )

        response["X-Content-Type-Options"] = "nosniff"
        return response


@admin.register(FormSection)
class FormSectionAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "title_sw",
        "event_form",
        "display_order",
        "condition_question",
        "condition_value",
        "is_active",
    )

    list_filter = (
        "event_form__event",
        "event_form",
        "is_active",
    )

    search_fields = (
        "title_sw",
        "title_en",
        "event_form__name_sw",
        "event_form__name_en",
    )

    ordering = (
        "event_form",
        "display_order",
    )


@admin.register(FormQuestion)
class FormQuestionAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "label_sw",
        "section",
        "question_type",
        "condition_question",
        "condition_value",
        "is_required",
        "display_order",
        "is_active",
    )

    list_filter = (
        "question_type",
        "is_required",
        "section__event_form",
        "is_active",
    )

    search_fields = (
        "label_sw",
        "label_en",
        "section__title_sw",
        "section__title_en",
    )

    ordering = (
        "section",
        "display_order",
    )

    inlines = [
        QuestionOptionInline,
    ]


@admin.register(QuestionOption)
class QuestionOptionAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "label_sw",
        "question",
        "value",
        "display_order",
        "is_active",
    )

    list_filter = (
        "question__section__event_form",
        "is_active",
    )

    search_fields = (
        "label_sw",
        "label_en",
        "value",
        "question__label_sw",
        "question__label_en",
    )


class FormAnswerInline(admin.TabularInline):
    model = FormAnswer
    extra = 0
    can_delete = False

    fields = (
        "question",
        "text_value",
        "number_value",
        "date_value",
        "datetime_value",
        "boolean_value",
        "uploaded_file",
    )

    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "reference_number",
        "event_name",
        "form_name",
        "submitter_email",
        "submitter_phone",
        "language",
        "is_complete",
        "review_status_badge",
        "booth_assignment_display",
        "badge_tools",
        "certificate_tools",
        "submitted_on",
    )

    list_filter = (
        "event_form__event",
        SubmissionFormFilter,
        "event_form__form_type",
        "language",
        "is_complete",
        "review_status",
        "created_at",
    )

    search_fields = (
        "reference_number",
        "submitter_email",
        "submitter_phone",
        "event_form__event__code",
        "event_form__event__title_sw",
        "event_form__event__title_en",
        "event_form__name_sw",
        "event_form__name_en",
        "badge_name",
        "badge_organization",
        "badge_title",
        "submitted_by__username",
        "submitted_by__first_name",
        "submitted_by__last_name",
        "answers__text_value",
        "answers__selected_options__label_sw",
        "answers__selected_options__label_en",
    )

    readonly_fields = (
        "reference_number",
        "event_form",
        "submitted_by",
        "language",
        "ip_address",
        "user_agent",
        "is_complete",
        "reviewed_by",
        "reviewed_at",
        "participant_token",
        "badge_tools",
        "certificate_tools",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            _("Registration record"),
            {
                "fields": (
                    "reference_number", "event_form", "submitted_by",
                    "language", "is_complete",
                ),
            },
        ),
        (
            _("Participant contact information"),
            {
                "fields": ("submitter_email", "submitter_phone"),
                "description": _(
                    "Update these fields when a participant reports an incorrect email address or phone number."
                ),
            },
        ),
        (
            _("Registration review"),
            {
                "fields": (
                    "review_status", "review_notes", "reviewed_by",
                    "reviewed_at",
                ),
            },
        ),
        (
            _("Badge information"),
            {
                "fields": (
                    "badge_name", "badge_organization", "badge_title",
                    "badge_tools", "certificate_tools",
                ),
            },
        ),
        (
            _("Technical and audit information"),
            {
                "classes": ("collapse",),
                "fields": (
                    "participant_token", "ip_address", "user_agent",
                    "is_active", "created_by", "updated_by", "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    date_hierarchy = "created_at"
    list_per_page = 50
    list_select_related = (
        "event_form",
        "event_form__event",
        "check_in",
        "booth_assignment",
    )
    actions = (
        "approve_submissions",
        "reject_submissions",
        "reset_submissions_to_pending",
        "export_submissions_csv",
        "authorize_certificates",
        "revoke_certificate_authorization",
    )

    inlines = [
        FormAnswerInline,
    ]

    def has_add_permission(self, request):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not (
            request.user.is_superuser
            or has_event_role(request.user, {
                User.Role.SYSTEM_ADMIN,
                User.Role.EVENT_ADMIN,
            })
        ):
            actions.pop("authorize_certificates", None)
            actions.pop("revoke_certificate_authorization", None)
        return actions

    @admin.display(description="Event", ordering="event_form__event__code")
    def event_name(self, obj):
        return obj.event_form.event.code

    @admin.display(description="Form", ordering="event_form__name_en")
    def form_name(self, obj):
        return obj.event_form.name_en

    @admin.display(description="Submitted on", ordering="created_at")
    def submitted_on(self, obj):
        return obj.created_at

    @admin.display(description="Review status", ordering="review_status")
    def review_status_badge(self, obj):
        if not obj.is_complete:
            return "Draft — not submitted"
        if obj.event_form.form_type == EventForm.FormType.EVALUATION:
            return "Not applicable"
        colors = {
            FormSubmission.ReviewStatus.PENDING: ("#854d0e", "#fef9c3"),
            FormSubmission.ReviewStatus.APPROVED: ("#166534", "#dcfce7"),
            FormSubmission.ReviewStatus.REJECTED: ("#991b1b", "#fee2e2"),
        }
        foreground, background = colors[obj.review_status]
        return format_html(
            '<span style="display:inline-block;padding:3px 8px;'
            'border-radius:999px;color:{};background:{};font-weight:700">'
            "{}</span>",
            foreground,
            background,
            obj.get_review_status_display(),
        )

    @admin.display(description="Booth")
    def booth_assignment_display(self, obj):
        if obj.event_form.form_type == EventForm.FormType.EVALUATION:
            return "Not applicable"
        if not hasattr(obj, "booth_assignment"):
            return "Unassigned"
        return format_html(
            "<strong>{}</strong><br><small>{}</small>",
            obj.booth_assignment.code,
            obj.booth_assignment.get_status_display(),
        )

    @admin.display(description="Participant badge")
    def badge_tools(self, obj):
        if not obj.is_complete:
            return "Available after the form is submitted."
        if obj.event_form.form_type == EventForm.FormType.EVALUATION:
            return "Not applicable"
        if obj.review_status != FormSubmission.ReviewStatus.APPROVED:
            return "Available after approval."

        if not obj.event_form.event.badge_enabled:
            return "Badges are disabled for this event."

        badge_url = participant_badge_path(obj, language=obj.language)
        qr_url = reverse(
            "forms_builder:participant_badge_qr",
            kwargs={"participant_token": obj.participant_token},
        )
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Open badge</a>'
            ' &nbsp;|&nbsp; '
            '<a href="{}?download=1">Download badge QR</a>',
            badge_url,
            qr_url,
        )

    @admin.display(description="Certificate")
    def certificate_tools(self, obj):
        if not obj.is_complete:
            return "Available after the form is submitted and participant check-in."
        if obj.event_form.form_type == EventForm.FormType.EVALUATION:
            return "Not applicable"
        if not obj.event_form.event.certificate_enabled:
            return "Certificates are disabled for this event."

        if obj.review_status != FormSubmission.ReviewStatus.APPROVED:
            return "Available after approval and check-in."

        if not hasattr(obj, "check_in"):
            return "Available after participant check-in."
        certificate = getattr(obj, "certificate_record", None)
        if not certificate or certificate.status != CertificateRecord.Status.AUTHORIZED:
            return "Waiting for certificate authorization."

        certificate_url = participant_certificate_path(
            obj,
            language=obj.language,
        )
        certificate_pdf_url = reverse(
            "forms_builder:participant_certificate_pdf",
            kwargs={"participant_token": obj.participant_token},
        )
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">'
            "Open certificate</a> &nbsp;|&nbsp; "
            '<a href="{}">Download PDF</a>',
            certificate_url,
            certificate_pdf_url,
        )

    @admin.action(description=_("Authorize certificates for selected participants"))
    def authorize_certificates(self, request, queryset):
        if not (
            request.user.is_superuser
            or has_event_role(request.user, {
                User.Role.SYSTEM_ADMIN,
                User.Role.EVENT_ADMIN,
            })
        ):
            self.message_user(
                request, _("You cannot authorize certificates."), messages.ERROR,
            )
            return
        eligible = list(queryset.filter(
            event_form__event__certificate_enabled=True,
            review_status=FormSubmission.ReviewStatus.APPROVED,
            check_in__isnull=False,
        ).exclude(
            certificate_record__status=CertificateRecord.Status.AUTHORIZED,
        ).select_related("event_form__event", "certificate_record"))
        eligible = [
            submission for submission in eligible
            if certificate_eligibility_for_submission(submission)[0]
        ]
        now = timezone.now()
        for submission in eligible:
            certificate, created = CertificateRecord.objects.get_or_create(
                submission=submission,
                defaults={
                    "certificate_number": certificate_number(submission),
                    "status": CertificateRecord.Status.AUTHORIZED,
                    "authorized_by": request.user,
                    "authorized_at": now,
                    "denied_by": None,
                    "denied_at": None,
                    "denial_reason": "",
                    "revoked_by": None,
                    "revoked_at": None,
                    "revocation_reason": "",
                    "updated_by": request.user,
                    "created_by": request.user,
                },
            )
            if not created:
                certificate.certificate_number = certificate_number(submission)
                certificate.status = CertificateRecord.Status.AUTHORIZED
                certificate.authorized_by = request.user
                certificate.authorized_at = now
                certificate.denied_by = None
                certificate.denied_at = None
                certificate.denial_reason = ""
                certificate.revoked_by = None
                certificate.revoked_at = None
                certificate.revocation_reason = ""
                certificate.updated_by = request.user
                certificate.save()
            send_submission_notification(
                submission,
                NotificationLog.NotificationType.CERTIFICATE_AUTHORIZED,
                request=request,
            )
        self.message_user(
            request,
            _("Certificates authorized: %(count)s") % {"count": len(eligible)},
            messages.SUCCESS,
        )

    @admin.action(description=_("Revoke certificate authorization"))
    def revoke_certificate_authorization(self, request, queryset):
        if not (
            request.user.is_superuser
            or has_event_role(request.user, {
                User.Role.SYSTEM_ADMIN,
                User.Role.EVENT_ADMIN,
            })
        ):
            return
        CertificateRecord.objects.filter(
            submission__in=queryset,
            status=CertificateRecord.Status.AUTHORIZED,
        ).update(
            status=CertificateRecord.Status.REVOKED,
            revoked_by=request.user,
            revoked_at=timezone.now(),
            revocation_reason=_("Revoked through system administration."),
            updated_by=request.user,
            updated_at=timezone.now(),
        )

    def save_model(self, request, obj, form, change):
        old_status = None
        if change:
            old_status = (
                FormSubmission.objects
                .filter(pk=obj.pk)
                .values_list("review_status", flat=True)
                .first()
            )

        if not obj.is_complete and obj.review_status != FormSubmission.ReviewStatus.PENDING:
            obj.review_status = FormSubmission.ReviewStatus.PENDING
            self.message_user(
                request,
                _("An unfinished draft cannot be reviewed. Its status remains pending."),
                messages.WARNING,
            )

        if obj.review_status != old_status:
            if obj.review_status == FormSubmission.ReviewStatus.PENDING:
                obj.reviewed_by = None
                obj.reviewed_at = None
            else:
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()

        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

        if obj.review_status != old_status:
            notification_types = {
                FormSubmission.ReviewStatus.APPROVED: (
                    NotificationLog.NotificationType.REGISTRATION_APPROVED
                ),
                FormSubmission.ReviewStatus.REJECTED: (
                    NotificationLog.NotificationType.REGISTRATION_REJECTED
                ),
            }
            notification_type = notification_types.get(obj.review_status)
            if notification_type:
                send_submission_notification(
                    obj,
                    notification_type,
                    request=request,
                )

    def _set_review_status(self, request, queryset, status):
        selected_count = queryset.count()
        queryset = queryset.filter(is_complete=True).exclude(
            event_form__form_type=EventForm.FormType.EVALUATION
        ).exclude(review_status=status)
        submissions = list(
            queryset.select_related("event_form__event")
        )
        current_time = timezone.now()
        reviewer = (
            request.user
            if status != FormSubmission.ReviewStatus.PENDING
            else None
        )
        reviewed_at = (
            current_time
            if status != FormSubmission.ReviewStatus.PENDING
            else None
        )
        updated = queryset.update(
            review_status=status,
            reviewed_by=reviewer,
            reviewed_at=reviewed_at,
            updated_by=request.user,
            updated_at=current_time,
        )
        self.message_user(
            request,
            f"{updated} submission(s) updated.",
            messages.SUCCESS,
        )
        skipped = selected_count - len(submissions)
        if skipped:
            self.message_user(
                request,
                _(
                    "%(count)s draft, evaluation, or already-matching "
                    "submission(s) were not changed."
                ) % {"count": skipped},
                messages.WARNING,
            )
        notification_types = {
            FormSubmission.ReviewStatus.APPROVED: (
                NotificationLog.NotificationType.REGISTRATION_APPROVED
            ),
            FormSubmission.ReviewStatus.REJECTED: (
                NotificationLog.NotificationType.REGISTRATION_REJECTED
            ),
        }
        notification_type = notification_types.get(status)
        if notification_type:
            for submission in submissions:
                submission.review_status = status
                send_submission_notification(
                    submission,
                    notification_type,
                    request=request,
                )

    @admin.action(description="Approve selected submissions")
    def approve_submissions(self, request, queryset):
        self._set_review_status(
            request,
            queryset,
            FormSubmission.ReviewStatus.APPROVED,
        )

    @admin.action(description="Reject selected submissions")
    def reject_submissions(self, request, queryset):
        self._set_review_status(
            request,
            queryset,
            FormSubmission.ReviewStatus.REJECTED,
        )

    @admin.action(description="Reset selected submissions to pending")
    def reset_submissions_to_pending(self, request, queryset):
        self._set_review_status(
            request,
            queryset,
            FormSubmission.ReviewStatus.PENDING,
        )

    @admin.action(description="Export selected submissions to CSV")
    def export_submissions_csv(self, request, queryset):
        submissions = (
            queryset
            .select_related("event_form", "event_form__event")
            .prefetch_related(
                "answers__question",
                "answers__selected_options",
            )
            .order_by("-created_at")
        )
        csv_content = submissions_csv(submissions)
        response = HttpResponse(
            "\ufeff" + csv_content,
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = (
            'attachment; filename="registration-submissions.csv"'
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response


@admin.register(Participant)
class ParticipantAdmin(FormSubmissionAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).exclude(
            event_form__form_type=EventForm.FormType.EVALUATION,
        )


@admin.register(CertificateRecord)
class CertificateRecordAdmin(admin.ModelAdmin):
    actions = ()
    list_display = (
        "certificate_number", "reference_number", "event_name",
        "participant_name", "status", "authorized_by", "authorized_at",
        "certificate_link",
    )
    list_filter = ("status", "submission__event_form__event", "authorized_at")
    search_fields = (
        "certificate_number", "submission__reference_number",
        "submission__badge_name", "submission__submitter_email",
    )
    readonly_fields = (
        "submission", "certificate_number", "status", "authorized_by",
        "authorized_at", "denied_by", "denied_at", "denial_reason",
        "revoked_by", "revoked_at", "revocation_reason",
        "created_by", "updated_by", "created_at", "updated_at",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "submission__event_form__event", "authorized_by", "denied_by",
            "revoked_by",
        )

    @admin.display(description=_("Reference number"), ordering="submission__reference_number")
    def reference_number(self, obj):
        return obj.submission.reference_number

    @admin.display(description=_("Event"), ordering="submission__event_form__event__code")
    def event_name(self, obj):
        return obj.submission.event_form.event.code

    @admin.display(description=_("Participant"), ordering="submission__badge_name")
    def participant_name(self, obj):
        return obj.submission.badge_display_name

    @admin.display(description=_("Certificate"))
    def certificate_link(self, obj):
        if obj.status != CertificateRecord.Status.AUTHORIZED:
            return _("Revoked")
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            participant_certificate_path(obj.submission, obj.submission.language),
            _("Open certificate"),
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EventReminder)
class EventReminderAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "event",
        "subject_en",
        "scheduled_for",
        "status",
        "sent_count",
        "skipped_count",
        "failed_count",
        "processed_at",
    )
    list_filter = (
        "status",
        "event",
        "scheduled_for",
    )
    search_fields = (
        "event__code",
        "event__title_sw",
        "event__title_en",
        "subject_sw",
        "subject_en",
        "message_sw",
        "message_en",
    )
    readonly_fields = AuditAdminMixin.readonly_fields + (
        "sent_count",
        "skipped_count",
        "failed_count",
        "processed_at",
    )
    actions = ("send_reminders_now",)
    date_hierarchy = "scheduled_for"

    @admin.action(description=_("Send selected reminders now"))
    def send_reminders_now(self, request, queryset):
        completed = 0
        already_completed = 0
        for reminder in queryset.select_related("event"):
            if reminder.status == EventReminder.Status.COMPLETED:
                already_completed += 1
                continue
            process_event_reminder(reminder, request=request, force=True)
            completed += 1
        self.message_user(
            request,
            _("%(completed)s reminder(s) sent; %(skipped)s already completed.")
            % {"completed": completed, "skipped": already_completed},
            messages.SUCCESS,
        )


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "submission",
        "notification_type",
        "event_reminder",
        "recipient",
        "delivery_status",
        "sent_at",
    )
    list_filter = (
        "notification_type",
        "event_reminder",
        "delivery_status",
        "submission__event_form__event",
        "created_at",
    )
    search_fields = (
        "submission__reference_number",
        "recipient",
        "subject",
        "error_message",
    )
    readonly_fields = (
        "submission",
        "event_reminder",
        "notification_type",
        "recipient",
        "subject",
        "delivery_status",
        "error_message",
        "sent_at",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    list_select_related = (
        "submission",
        "submission__event_form__event",
        "event_reminder",
    )
    actions = ("resend_selected_notifications",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.action(description=_("Resend selected notifications"))
    def resend_selected_notifications(self, request, queryset):
        resent = 0
        for log in queryset.select_related(
            "submission__event_form__event",
            "event_reminder__event",
        ):
            resend_notification(log, request=request)
            resent += 1
        self.message_user(
            request,
            _("%(count)s notification(s) resent.") % {"count": resent},
            messages.SUCCESS,
        )


@admin.register(FormAnswer)
class FormAnswerAdmin(admin.ModelAdmin):
    list_display = (
        "submission",
        "question",
        "short_answer",
        "created_at",
    )

    list_filter = (
        "question__question_type",
        "question__section__event_form",
    )

    search_fields = (
        "submission__reference_number",
        "question__label_sw",
        "question__label_en",
        "text_value",
    )

    readonly_fields = (
        "submission",
        "question",
        "text_value",
        "number_value",
        "date_value",
        "datetime_value",
        "boolean_value",
        "uploaded_file",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )

    def short_answer(self, obj):
        value = (
            obj.text_value
            or obj.number_value
            or obj.date_value
            or obj.datetime_value
            or obj.boolean_value
            or obj.uploaded_file
            or "-"
        )

        return str(value)[:80]

    short_answer.short_description = "Answer"

    def has_add_permission(self, request):
        return False
