import uuid
from itertools import combinations

from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.utils.text import slugify
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from events.models import Event


ANSWER_SCALAR_VALUE_TESTS = (
    ~models.Q(text_value=""),
    models.Q(number_value__isnull=False),
    models.Q(date_value__isnull=False),
    models.Q(datetime_value__isnull=False),
    models.Q(boolean_value__isnull=False),
    models.Q(uploaded_file__isnull=False) & ~models.Q(uploaded_file=""),
)


class EventForm(BaseModel):
    class FormType(models.TextChoices):
        REGISTRATION = "REGISTRATION", _("Registration Form")
        EVALUATION = "EVALUATION", _("Evaluation Form")
        EXHIBITOR = "EXHIBITOR", _("Exhibitor Form")
        SPEAKER = "SPEAKER", _("Speaker Application Form")
        ATTENDANCE = "ATTENDANCE", _("Attendance Confirmation Form")
        OTHER = "OTHER", _("Other Form")

    event = models.ForeignKey(
        Event,
        verbose_name=_("event"),
        related_name="forms",
        on_delete=models.CASCADE,
    )

    name_sw = models.CharField(
        _("form name in Kiswahili"),
        max_length=200,
    )

    name_en = models.CharField(
        _("form name in English"),
        max_length=200,
    )

    form_type = models.CharField(
        _("form type"),
        max_length=30,
        choices=FormType.choices,
        default=FormType.REGISTRATION,
    )

    slug = models.SlugField(
        _("slug"),
        max_length=250,
        blank=True,
    )

    introduction_sw = models.TextField(
        _("introduction in Kiswahili"),
        blank=True,
    )

    introduction_en = models.TextField(
        _("introduction in English"),
        blank=True,
    )

    show_event_summary = models.BooleanField(
        _("show event summary above form"),
        default=True,
        help_text=_(
            "Display the event logo, code, title, dates and venue above this form."
        ),
    )

    success_message_sw = models.TextField(
        _("success message in Kiswahili"),
        blank=True,
        default="Taarifa zako zimepokelewa kwa mafanikio.",
    )

    success_message_en = models.TextField(
        _("success message in English"),
        blank=True,
        default="Your information has been submitted successfully.",
    )

    opens_at = models.DateTimeField(
        _("form opens"),
        null=True,
        blank=True,
    )

    closes_at = models.DateTimeField(
        _("form closes"),
        null=True,
        blank=True,
    )

    requires_login = models.BooleanField(
        _("requires login"),
        default=False,
    )

    allow_multiple_submissions = models.BooleanField(
        _("allow multiple submissions"),
        default=False,
    )

    requires_participant_registration = models.BooleanField(
        _("requires participant registration"),
        default=False,
        help_text=_(
            "Allow access only from the portal of a participant registered "
            "for this event."
        ),
    )

    is_published = models.BooleanField(
        _("published"),
        default=False,
    )

    class Meta:
        verbose_name = _("event form")
        verbose_name_plural = _("event forms")
        ordering = ["event", "form_type", "name_sw"]

        constraints = [
            models.UniqueConstraint(
                fields=["event", "slug"],
                name="unique_form_slug_per_event",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name_en or self.name_sw)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event.code} - {self.name_sw}"


class FormSection(BaseModel):
    event_form = models.ForeignKey(
        EventForm,
        verbose_name=_("event form"),
        related_name="sections",
        on_delete=models.CASCADE,
    )

    title_sw = models.CharField(
        _("section title in Kiswahili"),
        max_length=200,
    )

    title_en = models.CharField(
        _("section title in English"),
        max_length=200,
    )

    description_sw = models.TextField(
        _("section description in Kiswahili"),
        blank=True,
    )

    description_en = models.TextField(
        _("section description in English"),
        blank=True,
    )

    display_order = models.PositiveIntegerField(
        _("display order"),
        default=0,
    )

    condition_question = models.ForeignKey(
        "FormQuestion",
        verbose_name=_("show when question"),
        related_name="conditional_sections",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_(
            "Leave blank to always show this section."
        ),
    )

    condition_value = models.CharField(
        _("show when answer contains"),
        max_length=100,
        blank=True,
        help_text=_(
            "Use the stored value of the controlling question option."
        ),
    )

    class Meta:
        verbose_name = _("form section")
        verbose_name_plural = _("form sections")
        ordering = ["event_form", "display_order", "id"]

    def clean(self):
        super().clean()
        has_question = bool(self.condition_question_id)
        has_value = bool(self.condition_value)

        if has_question != has_value:
            raise ValidationError(
                _(
                    "Both the controlling question and answer value are "
                    "required for conditional display."
                )
            )

        if (
            has_question
            and self.event_form_id
            and self.condition_question.section.event_form_id
            != self.event_form_id
        ):
            raise ValidationError(
                {
                    "condition_question": _(
                        "The controlling question must belong to the same form."
                    )
                }
            )

        if (
            has_question
            and has_value
            and not self.condition_question.options.filter(
                value=self.condition_value,
                is_active=True,
            ).exists()
        ):
            raise ValidationError(
                {
                    "condition_value": _(
                        "Enter an active stored option value from the "
                        "controlling question."
                    )
                }
            )

    def __str__(self):
        return f"{self.event_form.name_sw} - {self.title_sw}"


class FormQuestion(BaseModel):
    class QuestionType(models.TextChoices):
        SHORT_TEXT = "SHORT_TEXT", _("Short text")
        LONG_TEXT = "LONG_TEXT", _("Long text")
        EMAIL = "EMAIL", _("Email address")
        PHONE = "PHONE", _("Phone number")
        NUMBER = "NUMBER", _("Number")
        DATE = "DATE", _("Date")
        DATETIME = "DATETIME", _("Date and time")
        SINGLE_CHOICE = "SINGLE_CHOICE", _("Single choice")
        MULTIPLE_CHOICE = "MULTIPLE_CHOICE", _("Multiple choice")
        DROPDOWN = "DROPDOWN", _("Dropdown")
        YES_NO = "YES_NO", _("Yes or No")
        FILE = "FILE", _("File upload")
        IMAGE = "IMAGE", _("Image upload")

    section = models.ForeignKey(
        FormSection,
        verbose_name=_("form section"),
        related_name="questions",
        on_delete=models.CASCADE,
    )

    label_sw = models.CharField(
        _("question in Kiswahili"),
        max_length=300,
    )

    label_en = models.CharField(
        _("question in English"),
        max_length=300,
    )

    question_type = models.CharField(
        _("question type"),
        max_length=30,
        choices=QuestionType.choices,
        default=QuestionType.SHORT_TEXT,
    )

    help_text_sw = models.CharField(
        _("help text in Kiswahili"),
        max_length=300,
        blank=True,
    )

    help_text_en = models.CharField(
        _("help text in English"),
        max_length=300,
        blank=True,
    )

    placeholder_sw = models.CharField(
        _("placeholder in Kiswahili"),
        max_length=200,
        blank=True,
    )

    placeholder_en = models.CharField(
        _("placeholder in English"),
        max_length=200,
        blank=True,
    )

    is_required = models.BooleanField(
        _("required"),
        default=False,
    )

    display_order = models.PositiveIntegerField(
        _("display order"),
        default=0,
    )

    minimum_length = models.PositiveIntegerField(
        _("minimum length"),
        null=True,
        blank=True,
    )

    maximum_length = models.PositiveIntegerField(
        _("maximum length"),
        null=True,
        blank=True,
    )

    minimum_value = models.DecimalField(
        _("minimum value"),
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    maximum_value = models.DecimalField(
        _("maximum value"),
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    condition_question = models.ForeignKey(
        "self",
        verbose_name=_("show when question"),
        related_name="conditional_questions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Leave blank to always show this question."),
    )

    condition_value = models.CharField(
        _("show when answer contains"),
        max_length=100,
        blank=True,
        help_text=_("Use the stored value of an option from the controlling question."),
    )

    class Meta:
        verbose_name = _("form question")
        verbose_name_plural = _("form questions")
        ordering = ["section", "display_order", "id"]

    def clean(self):
        super().clean()
        has_question = bool(self.condition_question_id)
        has_value = bool(self.condition_value)
        if has_question != has_value:
            raise ValidationError(_(
                "Both the controlling question and answer value are required for conditional display."
            ))
        if has_question and self.condition_question_id == self.pk:
            raise ValidationError({"condition_question": _("A question cannot control itself.")})
        if (
            has_question
            and self.section_id
            and self.condition_question.section.event_form_id
            != self.section.event_form_id
        ):
            raise ValidationError({
                "condition_question": _("The controlling question must belong to the same form.")
            })
        if (
            has_question
            and has_value
            and not self.condition_question.options.filter(
                value=self.condition_value, is_active=True
            ).exists()
        ):
            raise ValidationError({
                "condition_value": _("Enter an active stored option value from the controlling question.")
            })

    def __str__(self):
        return self.label_sw

    @property
    def supports_options(self):
        return self.question_type in {
            self.QuestionType.SINGLE_CHOICE,
            self.QuestionType.MULTIPLE_CHOICE,
            self.QuestionType.DROPDOWN,
        }

    @property
    def condition_answer_label_en(self):
        if not self.condition_question_id:
            return ""
        option = next(
            (
                item for item in self.condition_question.options.all()
                if item.is_active and item.value == self.condition_value
            ),
            None,
        )
        return option.label_en if option else self.condition_value


class QuestionOption(BaseModel):
    question = models.ForeignKey(
        FormQuestion,
        verbose_name=_("question"),
        related_name="options",
        on_delete=models.CASCADE,
    )

    value = models.CharField(
        _("stored value"),
        max_length=100,
    )

    label_sw = models.CharField(
        _("option in Kiswahili"),
        max_length=200,
    )

    label_en = models.CharField(
        _("option in English"),
        max_length=200,
    )

    display_order = models.PositiveIntegerField(
        _("display order"),
        default=0,
    )

    class Meta:
        verbose_name = _("question option")
        verbose_name_plural = _("question options")
        ordering = ["question", "display_order", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["question", "value"],
                name="unique_option_value_per_question",
            ),
        ]

    def __str__(self):
        return self.label_sw


class DisplayLogicGroup(BaseModel):
    class MatchType(models.TextChoices):
        ALL = "ALL", _("Match all rules (AND)")
        ANY = "ANY", _("Match any rule (OR)")

    event_form = models.ForeignKey(
        EventForm,
        related_name="display_logic_groups",
        on_delete=models.CASCADE,
    )
    target_section = models.OneToOneField(
        FormSection,
        related_name="display_logic",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    target_question = models.OneToOneField(
        FormQuestion,
        related_name="display_logic",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    match_type = models.CharField(
        max_length=3,
        choices=MatchType.choices,
        default=MatchType.ALL,
    )

    class Meta:
        verbose_name = _("display logic group")
        verbose_name_plural = _("display logic groups")
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(target_section__isnull=False, target_question__isnull=True)
                    | models.Q(target_section__isnull=True, target_question__isnull=False)
                ),
                name="logic_group_has_exactly_one_target",
            ),
        ]

    def clean(self):
        super().clean()
        targets = int(bool(self.target_section_id)) + int(bool(self.target_question_id))
        if targets != 1:
            raise ValidationError("A logic group must control exactly one section or question.")
        target_form_id = (
            self.target_section.event_form_id
            if self.target_section_id
            else self.target_question.section.event_form_id
        )
        if self.event_form_id and target_form_id != self.event_form_id:
            raise ValidationError("The target must belong to the logic group's form.")

    @property
    def target(self):
        return self.target_section or self.target_question

    @property
    def summary_en(self):
        rules = [rule.summary_en for rule in self.rules.filter(is_active=True)]
        if not rules:
            return "Always show"
        joiner = " AND " if self.match_type == self.MatchType.ALL else " OR "
        return joiner.join(rules)

    def __str__(self):
        return f"{self.get_match_type_display()}: {self.target}"


class DisplayLogicRule(BaseModel):
    class Operator(models.TextChoices):
        EQUALS = "EQUALS", _("equals")
        NOT_EQUALS = "NOT_EQUALS", _("does not equal")
        CONTAINS = "CONTAINS", _("contains")
        NOT_CONTAINS = "NOT_CONTAINS", _("does not contain")
        ANY_OF = "ANY_OF", _("is any of")
        NONE_OF = "NONE_OF", _("is none of")
        ANSWERED = "ANSWERED", _("is answered")
        NOT_ANSWERED = "NOT_ANSWERED", _("is not answered")
        GREATER_THAN = "GREATER_THAN", _("is greater than")
        LESS_THAN = "LESS_THAN", _("is less than")
        DATE_BEFORE = "DATE_BEFORE", _("is before date")
        DATE_AFTER = "DATE_AFTER", _("is after date")

    group = models.ForeignKey(
        DisplayLogicGroup,
        related_name="rules",
        on_delete=models.CASCADE,
    )
    source_question = models.ForeignKey(
        FormQuestion,
        related_name="display_logic_rules",
        on_delete=models.PROTECT,
    )
    operator = models.CharField(max_length=30, choices=Operator.choices)
    comparison_value = models.TextField(blank=True)
    comparison_values = models.JSONField(default=list, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "pk"]
        verbose_name = _("display logic rule")
        verbose_name_plural = _("display logic rules")

    def clean(self):
        super().clean()
        if (
            self.group_id
            and self.source_question_id
            and self.source_question.section.event_form_id != self.group.event_form_id
        ):
            raise ValidationError("The controlling question must belong to the same form.")
        if (
            self.group_id
            and self.group.target_question_id == self.source_question_id
        ):
            raise ValidationError("A question cannot control itself.")
        no_value = {
            self.Operator.ANSWERED,
            self.Operator.NOT_ANSWERED,
        }
        multiple_values = {self.Operator.ANY_OF, self.Operator.NONE_OF}
        if self.operator in no_value:
            return
        if self.operator in multiple_values and not self.comparison_values:
            raise ValidationError({"comparison_values": "Select at least one answer."})
        if self.operator not in multiple_values and not self.comparison_value:
            raise ValidationError({"comparison_value": "Enter or select a comparison value."})

    @property
    def display_value(self):
        values = self.comparison_values if self.operator in {
            self.Operator.ANY_OF, self.Operator.NONE_OF
        } else [self.comparison_value]
        option_labels = {
            option.value: option.label_en
            for option in self.source_question.options.filter(is_active=True)
        }
        return ", ".join(option_labels.get(str(value), str(value)) for value in values)

    @property
    def summary_en(self):
        suffix = "" if self.operator in {
            self.Operator.ANSWERED, self.Operator.NOT_ANSWERED
        } else f' “{self.display_value}”'
        return (
            f'“{self.source_question.label_en}” '
            f'{self.get_operator_display()}{suffix}'
        )

    def __str__(self):
        return self.summary_en

class FormSubmission(BaseModel):
    class ReviewStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending review")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")

    event_form = models.ForeignKey(
        EventForm,
        verbose_name=_("event form"),
        related_name="submissions",
        on_delete=models.CASCADE,
    )

    registration_submission = models.ForeignKey(
        "self",
        verbose_name=_("linked participant registration"),
        related_name="linked_evaluation_submissions",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=_(
            "The participant registration that supplied the identity for "
            "this evaluation submission."
        ),
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("submitted by"),
        related_name="event_form_submissions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    reference_number = models.CharField(
        _("reference number"),
        max_length=60,
        unique=True,
        blank=True,
    )

    language = models.CharField(
        _("submission language"),
        max_length=5,
        choices=(
            ("sw", _("Kiswahili")),
            ("en", _("English")),
        ),
        default="sw",
    )

    submitter_email = models.EmailField(
        _("submitter email"),
        blank=True,
    )

    submitter_phone = models.CharField(
        _("submitter phone"),
        max_length=30,
        blank=True,
    )

    ip_address = models.GenericIPAddressField(
        _("IP address"),
        null=True,
        blank=True,
    )

    user_agent = models.TextField(
        _("user agent"),
        blank=True,
    )

    is_complete = models.BooleanField(
        _("complete submission"),
        default=True,
    )

    review_status = models.CharField(
        _("review status"),
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        db_index=True,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("reviewed by"),
        related_name="reviewed_form_submissions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    reviewed_at = models.DateTimeField(
        _("reviewed at"),
        null=True,
        blank=True,
    )

    review_notes = models.TextField(
        _("internal review notes"),
        blank=True,
        help_text=_(
            "Visible to administrators only. Do not include passwords or secrets."
        ),
    )

    participant_token = models.UUIDField(
        _("participant token"),
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    badge_name = models.CharField(
        _("badge name"),
        max_length=200,
        blank=True,
        help_text=_("Name that will be printed on the participant badge."),
    )

    badge_organization = models.CharField(
        _("badge organization"),
        max_length=250,
        blank=True,
    )

    badge_title = models.CharField(
        _("badge title or role"),
        max_length=150,
        blank=True,
    )

    class Meta:
        verbose_name = _("form submission")
        verbose_name_plural = _("form submissions")
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["event_form", "created_at"],
                name="form_submit_created_idx",
            ),
            models.Index(
                fields=["reference_number"],
                name="form_submit_ref_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.reference_number:
            prefix = self.event_form.event.code.replace(" ", "-").upper()
            form_code = self.event_form.form_type[:3].upper()
            reference_prefix = f"{prefix}-{form_code}-"
            suffixes = []
            for reference in FormSubmission.objects.filter(
                event_form=self.event_form,
                reference_number__startswith=reference_prefix,
            ).values_list("reference_number", flat=True):
                suffix = reference.removeprefix(reference_prefix)
                if suffix.isdigit():
                    suffixes.append(int(suffix))
            self.reference_number = f"{reference_prefix}{max(suffixes, default=0) + 1:05d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return self.reference_number

    @property
    def badge_display_name(self):
        return (
            self.badge_name
            or self.submitter_email
            or self.submitter_phone
            or self.reference_number
        )


class Participant(FormSubmission):
    class Meta:
        proxy = True
        verbose_name = _("participant")
        verbose_name_plural = _("participants")


class CertificateRecord(BaseModel):
    class Status(models.TextChoices):
        AUTHORIZED = "AUTHORIZED", _("Authorized")
        DENIED = "DENIED", _("Not authorized")
        REVOKED = "REVOKED", _("Revoked")

    submission = models.OneToOneField(
        FormSubmission,
        verbose_name=_("participant submission"),
        related_name="certificate_record",
        on_delete=models.CASCADE,
    )
    certificate_number = models.CharField(
        _("certificate number"), max_length=50, unique=True,
    )
    status = models.CharField(
        _("certificate status"), max_length=20,
        choices=Status.choices, default=Status.AUTHORIZED, db_index=True,
    )
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("authorized by"),
        related_name="authorized_certificate_records",
        on_delete=models.PROTECT,
        null=True, blank=True,
    )
    authorized_at = models.DateTimeField(_("authorized at"), null=True, blank=True)
    denied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("denied by"),
        related_name="denied_certificate_records",
        on_delete=models.PROTECT,
        null=True, blank=True,
    )
    denied_at = models.DateTimeField(_("denied at"), null=True, blank=True)
    denial_reason = models.TextField(_("denial reason"), blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("revoked by"),
        related_name="revoked_certificate_records",
        on_delete=models.PROTECT,
        null=True, blank=True,
    )
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)
    revocation_reason = models.TextField(_("revocation reason"), blank=True)

    class Meta:
        verbose_name = _("certificate")
        verbose_name_plural = _("certificates")
        ordering = ["-authorized_at"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(
                        status="AUTHORIZED", revoked_by__isnull=True,
                        revoked_at__isnull=True, denied_by__isnull=True,
                        denied_at__isnull=True,
                    )
                    | models.Q(
                        status="DENIED", authorized_by__isnull=True,
                        authorized_at__isnull=True, denied_by__isnull=False,
                        denied_at__isnull=False, revoked_by__isnull=True,
                        revoked_at__isnull=True,
                    )
                    | models.Q(
                        status="REVOKED", authorized_by__isnull=False,
                        authorized_at__isnull=False, revoked_by__isnull=False,
                        revoked_at__isnull=False, denied_by__isnull=True,
                        denied_at__isnull=True,
                    )
                ),
                name="valid_certificate_lifecycle_state",
            ),
        ]

    def clean(self):
        super().clean()
        if self.status == self.Status.AUTHORIZED:
            if self.revoked_by_id or self.revoked_at or self.denied_by_id or self.denied_at:
                raise ValidationError(_("An authorized certificate cannot contain denial or revocation details."))
            eligible = (
                not self.submission_id
                or FormSubmission.objects.filter(
                    pk=self.submission_id,
                    review_status=FormSubmission.ReviewStatus.APPROVED,
                    check_in__isnull=False,
                    event_form__event__certificate_enabled=True,
                ).exists()
            )
            if not eligible:
                raise ValidationError(_("Only an approved, checked-in participant may receive a certificate."))
        elif self.status == self.Status.DENIED:
            if not self.denied_by_id or not self.denied_at or not self.denial_reason.strip():
                raise ValidationError(_("A certificate denial requires the officer, time and reason."))
        elif not self.revoked_by_id or not self.revoked_at or not self.revocation_reason.strip():
            raise ValidationError(_("A revoked certificate requires the officer, time and reason."))

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.certificate_number} — {self.submission.reference_number}"


class QuantityPricingRule(BaseModel):
    event = models.OneToOneField(
        Event, verbose_name=_("event"), related_name="quantity_pricing_rule",
        on_delete=models.CASCADE,
    )
    quantity_question = models.ForeignKey(
        FormQuestion, verbose_name=_("quantity question"),
        related_name="pricing_rules", on_delete=models.PROTECT,
        help_text=_("Select the numeric question that determines the quantity."),
    )
    first_unit_amount = models.DecimalField(
        _("first unit price"), max_digits=14, decimal_places=2,
    )
    additional_unit_amount = models.DecimalField(
        _("each additional unit price"), max_digits=14, decimal_places=2,
    )
    currency = models.CharField(_("currency"), max_length=3, default="TZS")

    class Meta:
        verbose_name = _("quantity pricing rule")
        verbose_name_plural = _("quantity pricing rules")

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.quantity_question_id
            and self.event_id
            and self.quantity_question.section.event_form.event_id != self.event_id
        ):
            errors["quantity_question"] = _(
                "The quantity question must belong to the selected event."
            )
        if self.first_unit_amount is not None and self.first_unit_amount < 0:
            errors["first_unit_amount"] = _("The first unit price cannot be negative.")
        if (
            self.additional_unit_amount is not None
            and self.additional_unit_amount < 0
        ):
            errors["additional_unit_amount"] = _(
                "The additional unit price cannot be negative."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.currency = self.currency.strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event.code} — {self.quantity_question.label_en}"


class Payment(BaseModel):
    class Method(models.TextChoices):
        BANK = "BANK", _("Bank deposit or transfer")
        MOBILE = "MOBILE", _("Mobile money")
        CASH = "CASH", _("Cash")
        OTHER = "OTHER", _("Other")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending verification")
        VERIFIED = "VERIFIED", _("Verified")
        REJECTED = "REJECTED", _("Rejected")
        REFUNDED = "REFUNDED", _("Refunded")

    submission = models.ForeignKey(
        FormSubmission, verbose_name=_("participant submission"),
        related_name="payments", on_delete=models.PROTECT,
    )
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, default="TZS")
    method = models.CharField(
        _("payment method"), max_length=20, choices=Method.choices,
        default=Method.BANK,
    )
    transaction_reference = models.CharField(
        _("transaction reference"), max_length=100, blank=True,
    )
    paid_at = models.DateTimeField(_("paid at"), null=True, blank=True)
    proof = models.FileField(_("payment proof"), upload_to="payments/%Y/%m/", blank=True)
    status = models.CharField(
        _("payment status"), max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True,
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("verified by"),
        related_name="verified_payments", on_delete=models.SET_NULL,
        null=True, blank=True, editable=False,
    )
    verified_at = models.DateTimeField(
        _("verified at"), null=True, blank=True, editable=False,
    )
    notes = models.TextField(_("payment notes"), blank=True)

    class Meta:
        verbose_name = _("payment")
        verbose_name_plural = _("payments")
        ordering = ["-paid_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["method", "transaction_reference"],
                condition=~models.Q(transaction_reference=""),
                name="unique_nonempty_payment_reference_per_method",
            ),
            models.CheckConstraint(
                check=models.Q(amount__gte=0),
                name="payment_amount_not_negative",
            ),
        ]

    def save(self, *args, **kwargs):
        self.currency = self.currency.strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.submission.reference_number} — {self.currency} {self.amount}"


class Booth(BaseModel):
    class Status(models.TextChoices):
        UNASSIGNED = "UNASSIGNED", _("Unassigned")
        ASSIGNED = "ASSIGNED", _("Assigned")
        READY = "READY", _("Ready")
        CLOSED = "CLOSED", _("Closed")

    event = models.ForeignKey(
        Event,
        verbose_name=_("event"),
        related_name="booths",
        on_delete=models.CASCADE,
    )
    public_token = models.UUIDField(
        _("booth public token"),
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    code = models.CharField(
        _("booth code"),
        max_length=30,
        help_text=_("For example A-01 or HALL-B-12."),
    )
    name_sw = models.CharField(
        _("booth name in Kiswahili"),
        max_length=200,
    )
    name_en = models.CharField(
        _("booth name in English"),
        max_length=200,
    )
    zone_sw = models.CharField(
        _("zone or location in Kiswahili"),
        max_length=150,
        blank=True,
    )
    zone_en = models.CharField(
        _("zone or location in English"),
        max_length=150,
        blank=True,
    )
    assigned_submission = models.OneToOneField(
        FormSubmission,
        verbose_name=_("assigned exhibitor submission"),
        related_name="booth_assignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Only an approved submission from this event may be assigned."),
    )
    status = models.CharField(
        _("booth setup status"),
        max_length=20,
        choices=Status.choices,
        default=Status.UNASSIGNED,
    )
    notes = models.TextField(
        _("internal booth notes"),
        blank=True,
    )
    description_sw = models.TextField(
        _("public booth description in Kiswahili"),
        blank=True,
    )
    description_en = models.TextField(
        _("public booth description in English"),
        blank=True,
    )
    public_email = models.EmailField(
        _("public booth email"),
        blank=True,
    )
    public_phone = models.CharField(
        _("public booth phone"),
        max_length=30,
        blank=True,
    )
    public_website = models.URLField(
        _("public booth website"),
        blank=True,
    )

    class Meta:
        verbose_name = _("booth")
        verbose_name_plural = _("booths")
        ordering = ["event", "zone_en", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "code"],
                name="unique_booth_code_per_event",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        submission = self.assigned_submission

        if submission:
            if submission.event_form.event_id != self.event_id:
                errors["assigned_submission"] = _(
                    "The assigned exhibitor must belong to the same event."
                )
            elif submission.review_status != FormSubmission.ReviewStatus.APPROVED:
                errors["assigned_submission"] = _(
                    "Only an approved exhibitor submission may be assigned."
                )
            elif not submission.is_active or not submission.is_complete:
                errors["assigned_submission"] = _(
                    "The assigned exhibitor submission must be active and complete."
                )
            elif submission.event_form.form_type not in {
                EventForm.FormType.REGISTRATION,
                EventForm.FormType.EXHIBITOR,
            }:
                errors["assigned_submission"] = _(
                    "This submission type cannot be assigned to a booth."
                )

            if self.status == self.Status.UNASSIGNED:
                self.status = self.Status.ASSIGNED
        elif self.status in {self.Status.ASSIGNED, self.Status.READY}:
            self.status = self.Status.UNASSIGNED

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event.code} — {self.code} — {self.name_en}"


class BoothOffering(BaseModel):
    class OfferingType(models.TextChoices):
        PRODUCT = "PRODUCT", _("Product")
        TECHNOLOGY = "TECHNOLOGY", _("Technology")
        SERVICE = "SERVICE", _("Service")
        OTHER = "OTHER", _("Other")

    booth = models.ForeignKey(
        Booth,
        verbose_name=_("booth"),
        related_name="offerings",
        on_delete=models.CASCADE,
    )
    offering_type = models.CharField(
        _("offering type"),
        max_length=20,
        choices=OfferingType.choices,
        default=OfferingType.PRODUCT,
    )
    name_sw = models.CharField(
        _("offering name in Kiswahili"),
        max_length=200,
    )
    name_en = models.CharField(
        _("offering name in English"),
        max_length=200,
    )
    description_sw = models.TextField(
        _("offering description in Kiswahili"),
        blank=True,
    )
    description_en = models.TextField(
        _("offering description in English"),
        blank=True,
    )
    display_order = models.PositiveIntegerField(
        _("display order"),
        default=0,
    )

    class Meta:
        verbose_name = _("booth offering")
        verbose_name_plural = _("booth offerings")
        ordering = ["booth", "display_order", "name_en"]

    def __str__(self):
        return f"{self.booth.code} — {self.name_en}"


class BoothInterest(BaseModel):
    booth = models.ForeignKey(
        Booth,
        verbose_name=_("booth"),
        related_name="interests",
        on_delete=models.CASCADE,
    )
    offering = models.ForeignKey(
        BoothOffering,
        verbose_name=_("offering of interest"),
        related_name="interests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    visitor_name = models.CharField(
        _("visitor name"),
        max_length=200,
        blank=True,
    )
    email = models.EmailField(
        _("visitor email"),
        blank=True,
    )
    phone = models.CharField(
        _("visitor phone"),
        max_length=30,
        blank=True,
    )
    message = models.TextField(
        _("visitor message"),
        blank=True,
    )
    language = models.CharField(
        _("language"),
        max_length=5,
        choices=FormSubmission._meta.get_field("language").choices,
        default="sw",
    )

    class Meta:
        verbose_name = _("booth visitor interest")
        verbose_name_plural = _("booth visitor interests")
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        errors = {}
        if not self.email and not self.phone:
            errors["email"] = _("Enter an email address or phone number.")
            errors["phone"] = _("Enter an email address or phone number.")
        if self.offering and self.offering.booth_id != self.booth_id:
            errors["offering"] = _(
                "The selected offering must belong to this booth."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.booth.code} — {self.visitor_name or self.email or self.phone}"


class EventReminder(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SCHEDULED = "SCHEDULED", _("Scheduled")
        PROCESSING = "PROCESSING", _("Processing")
        COMPLETED = "COMPLETED", _("Completed")

    event = models.ForeignKey(
        Event,
        verbose_name=_("event"),
        related_name="email_reminders",
        on_delete=models.CASCADE,
    )
    subject_sw = models.CharField(
        _("reminder subject in Kiswahili"),
        max_length=250,
    )
    subject_en = models.CharField(
        _("reminder subject in English"),
        max_length=250,
    )
    message_sw = models.TextField(
        _("reminder message in Kiswahili"),
    )
    message_en = models.TextField(
        _("reminder message in English"),
    )
    scheduled_for = models.DateTimeField(
        _("scheduled sending time"),
        db_index=True,
    )
    status = models.CharField(
        _("reminder status"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    sent_count = models.PositiveIntegerField(
        _("sent count"),
        default=0,
        editable=False,
    )
    skipped_count = models.PositiveIntegerField(
        _("skipped count"),
        default=0,
        editable=False,
    )
    failed_count = models.PositiveIntegerField(
        _("failed count"),
        default=0,
        editable=False,
    )
    processed_at = models.DateTimeField(
        _("processed at"),
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        verbose_name = _("event reminder")
        verbose_name_plural = _("event reminders")
        ordering = ["-scheduled_for"]

    def __str__(self):
        return f"{self.event.code} — {self.subject_en}"


class NotificationLog(BaseModel):
    class NotificationType(models.TextChoices):
        REGISTRATION_RECEIVED = "REGISTRATION_RECEIVED", _("Registration received")
        REGISTRATION_APPROVED = "REGISTRATION_APPROVED", _("Registration approved")
        REGISTRATION_REJECTED = "REGISTRATION_REJECTED", _("Registration rejected")
        CHECK_IN_CONFIRMED = "CHECK_IN_CONFIRMED", _("Check-in confirmed")
        EVENT_REMINDER = "EVENT_REMINDER", _("Event reminder")
        PAYMENT_RECEIVED = "PAYMENT_RECEIVED", _("Payment received")
        PAYMENT_VERIFIED = "PAYMENT_VERIFIED", _("Payment verified")
        PAYMENT_REJECTED = "PAYMENT_REJECTED", _("Payment rejected")
        CERTIFICATE_AUTHORIZED = (
            "CERTIFICATE_AUTHORIZED", _("Certificate authorized")
        )
        CERTIFICATE_DENIED = (
            "CERTIFICATE_DENIED", _("Certificate not authorized")
        )

    class DeliveryStatus(models.TextChoices):
        SENT = "SENT", _("Sent")
        FAILED = "FAILED", _("Failed")
        SKIPPED = "SKIPPED", _("Skipped")

    submission = models.ForeignKey(
        FormSubmission,
        verbose_name=_("form submission"),
        related_name="notification_logs",
        on_delete=models.CASCADE,
    )
    event_reminder = models.ForeignKey(
        EventReminder,
        verbose_name=_("event reminder"),
        related_name="notification_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notification_type = models.CharField(
        _("notification type"),
        max_length=40,
        choices=NotificationType.choices,
    )
    recipient = models.EmailField(
        _("recipient email"),
        blank=True,
    )
    subject = models.CharField(
        _("email subject"),
        max_length=250,
        blank=True,
    )
    delivery_status = models.CharField(
        _("delivery status"),
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.SKIPPED,
    )
    error_message = models.TextField(
        _("delivery error"),
        blank=True,
    )
    sent_at = models.DateTimeField(
        _("sent at"),
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("notification log")
        verbose_name_plural = _("notification logs")
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.submission.reference_number} — "
            f"{self.get_notification_type_display()} — "
            f"{self.get_delivery_status_display()}"
        )


class FormAnswer(BaseModel):
    submission = models.ForeignKey(
        FormSubmission,
        verbose_name=_("submission"),
        related_name="answers",
        on_delete=models.CASCADE,
    )

    question = models.ForeignKey(
        FormQuestion,
        verbose_name=_("question"),
        related_name="answers",
        on_delete=models.PROTECT,
    )

    text_value = models.TextField(
        _("text value"),
        blank=True,
    )

    number_value = models.DecimalField(
        _("number value"),
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
    )

    date_value = models.DateField(
        _("date value"),
        null=True,
        blank=True,
    )

    datetime_value = models.DateTimeField(
        _("date and time value"),
        null=True,
        blank=True,
    )

    boolean_value = models.BooleanField(
        _("boolean value"),
        null=True,
        blank=True,
    )

    selected_options = models.ManyToManyField(
        QuestionOption,
        verbose_name=_("selected options"),
        related_name="answers",
        blank=True,
    )

    uploaded_file = models.FileField(
        _("uploaded file"),
        upload_to="form_submissions/files/",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("form answer")
        verbose_name_plural = _("form answers")
        ordering = ["submission", "question__display_order"]

        constraints = [
            models.UniqueConstraint(
                fields=["submission", "question"],
                name="unique_answer_per_submission_question",
            ),
        ] + [
            models.CheckConstraint(
                check=~(first & second),
                name=f"answer_scalar_exclusive_{index:02d}",
            )
            for index, (first, second) in enumerate(
                combinations(ANSWER_SCALAR_VALUE_TESTS, 2), start=1,
            )
        ]

    def __str__(self):
        return f"{self.submission.reference_number} - {self.question}"

    def clean(self):
        super().clean()
        if (
            self.submission_id
            and self.question_id
            and self.question.section.event_form_id != self.submission.event_form_id
        ):
            raise ValidationError({
                "question": _("The question must belong to the submitted form."),
            })

        scalar_values = {
            "text_value": bool(self.text_value),
            "number_value": self.number_value is not None,
            "date_value": self.date_value is not None,
            "datetime_value": self.datetime_value is not None,
            "boolean_value": self.boolean_value is not None,
            "uploaded_file": bool(self.uploaded_file),
        }
        if sum(scalar_values.values()) > 1:
            raise ValidationError(_("An answer may contain only one scalar value type."))

        expected_fields = {
            FormQuestion.QuestionType.SHORT_TEXT: {"text_value"},
            FormQuestion.QuestionType.LONG_TEXT: {"text_value"},
            FormQuestion.QuestionType.EMAIL: {"text_value"},
            FormQuestion.QuestionType.PHONE: {"text_value"},
            FormQuestion.QuestionType.NUMBER: {"number_value"},
            FormQuestion.QuestionType.DATE: {"date_value"},
            FormQuestion.QuestionType.DATETIME: {"datetime_value"},
            FormQuestion.QuestionType.YES_NO: {"boolean_value"},
            FormQuestion.QuestionType.FILE: {"uploaded_file"},
            FormQuestion.QuestionType.IMAGE: {"uploaded_file"},
            FormQuestion.QuestionType.SINGLE_CHOICE: set(),
            FormQuestion.QuestionType.MULTIPLE_CHOICE: set(),
            FormQuestion.QuestionType.DROPDOWN: set(),
        }
        populated = {name for name, present in scalar_values.items() if present}
        if populated - expected_fields.get(self.question.question_type, set()):
            raise ValidationError(_("The stored answer type does not match the question type."))

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


@receiver(m2m_changed, sender=FormAnswer.selected_options.through)
def validate_answer_selected_options(sender, instance, action, pk_set, **kwargs):
    if action != "pre_add" or not pk_set:
        return
    invalid = QuestionOption.objects.filter(pk__in=pk_set).exclude(
        question_id=instance.question_id,
    ).exists()
    if invalid:
        raise ValidationError(_("Selected options must belong to the answered question."))
