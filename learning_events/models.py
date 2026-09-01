from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from events.models import Event
from forms_builder.models import FormSubmission


LEARNING_CATEGORY_CODES = {"SEMINAR", "WORKSHOP", "TRAINING"}


def normalized_category_code(event):
    return event.category.code.strip().upper().replace("-", "_").replace(" ", "_")


def validate_learning_event(event):
    if event and normalized_category_code(event) not in LEARNING_CATEGORY_CODES:
        raise ValidationError(_("Select a Seminar, Workshop or Training event."))


class LearningEventProfile(BaseModel):
    event = models.OneToOneField(
        Event, related_name="learning_profile", on_delete=models.CASCADE,
    )
    learning_objectives = models.TextField(blank=True)
    target_audience = models.TextField(blank=True)
    minimum_attendance_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("80.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    post_assessment_pass_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("50.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    certificate_requires_manual_approval = models.BooleanField(default=False)

    class Meta:
        ordering = ("event__starts_at", "event__code")

    def clean(self):
        if self.event_id:
            validate_learning_event(self.event)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event.code} learning operations"


class LearningFacilitator(BaseModel):
    class Role(models.TextChoices):
        SPEAKER = "SPEAKER", _("Speaker")
        FACILITATOR = "FACILITATOR", _("Facilitator")
        TRAINER = "TRAINER", _("Trainer")
        MODERATOR = "MODERATOR", _("Moderator")

    profile = models.ForeignKey(
        LearningEventProfile, related_name="facilitators", on_delete=models.CASCADE,
    )
    full_name = models.CharField(max_length=200)
    role = models.CharField(max_length=20, choices=Role.choices)
    position_title = models.CharField(max_length=200, blank=True)
    institution = models.CharField(max_length=250, blank=True)
    biography = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("display_order", "full_name")
        constraints = [models.UniqueConstraint(
            fields=("profile", "full_name", "institution"),
            name="unique_learning_facilitator_per_event",
        )]

    def __str__(self):
        return self.full_name


class LearningSession(BaseModel):
    class SessionType(models.TextChoices):
        OPENING = "OPENING", _("Opening")
        PRESENTATION = "PRESENTATION", _("Presentation")
        DISCUSSION = "DISCUSSION", _("Discussion")
        PRACTICAL = "PRACTICAL", _("Practical exercise")
        LESSON = "LESSON", _("Training lesson")
        ASSESSMENT = "ASSESSMENT", _("Assessment")
        BREAK = "BREAK", _("Break")
        CLOSING = "CLOSING", _("Closing")
        OTHER = "OTHER", _("Other")

    profile = models.ForeignKey(
        LearningEventProfile, related_name="sessions", on_delete=models.CASCADE,
    )
    code = models.CharField(max_length=60)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    session_type = models.CharField(
        max_length=20, choices=SessionType.choices, default=SessionType.PRESENTATION,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    venue_name = models.CharField(max_length=250, blank=True)
    facilitators = models.ManyToManyField(
        LearningFacilitator, related_name="sessions", blank=True,
    )
    material = models.FileField(
        upload_to="learning-events/materials/", blank=True, null=True,
        validators=[FileExtensionValidator(["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip"])],
    )
    is_published = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("starts_at", "display_order", "id")
        constraints = [models.UniqueConstraint(
            fields=("profile", "code"), name="unique_learning_session_code_per_event",
        )]

    def clean(self):
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = _("The session must end after it starts.")
        if self.profile_id:
            event = self.profile.event
            if self.starts_at and self.starts_at < event.starts_at:
                errors["starts_at"] = _("The session cannot start before the event.")
            if self.ends_at and self.ends_at > event.ends_at:
                errors["ends_at"] = _("The session cannot end after the event.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.profile.event.code} — {self.title}"


class LearningEnrollment(BaseModel):
    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", _("Registered")
        APPROVED = "APPROVED", _("Approved")
        COMPLETED = "COMPLETED", _("Completed")
        WITHDRAWN = "WITHDRAWN", _("Withdrawn")

    profile = models.ForeignKey(
        LearningEventProfile, related_name="enrollments", on_delete=models.CASCADE,
    )
    registration = models.OneToOneField(
        FormSubmission, related_name="learning_enrollment", on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    full_name = models.CharField(max_length=200)
    institution = models.CharField(max_length=250, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REGISTERED)
    certificate_approved = models.BooleanField(default=False)
    certificate_approved_at = models.DateTimeField(null=True, blank=True)
    certificate_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="approved_learning_certificates",
        on_delete=models.SET_NULL, null=True, blank=True,
    )

    class Meta:
        ordering = ("full_name", "id")
        constraints = [models.UniqueConstraint(
            fields=("profile", "full_name", "email"),
            name="unique_learning_enrollment_identity",
        )]

    @property
    def attendance_percentage(self):
        required = self.profile.sessions.filter(is_active=True).exclude(
            session_type=LearningSession.SessionType.BREAK,
        ).count()
        if not required:
            return Decimal("0.00")
        attended = self.attendance_records.filter(
            session__is_active=True,
        ).exclude(session__session_type=LearningSession.SessionType.BREAK).count()
        return (Decimal(attended) * Decimal("100") / Decimal(required)).quantize(Decimal("0.01"))

    @property
    def post_assessment_percentage(self):
        result = self.assessment_results.filter(
            assessment__assessment_type=LearningAssessment.AssessmentType.POST,
            assessment__is_active=True,
        ).order_by("-submitted_at", "-id").first()
        return result.percentage if result else None

    @property
    def automatically_certificate_eligible(self):
        if normalized_category_code(self.profile.event) != "TRAINING":
            return self.attendance_percentage >= self.profile.minimum_attendance_percentage
        score = self.post_assessment_percentage
        return bool(
            score is not None
            and score >= self.profile.post_assessment_pass_percentage
            and self.attendance_percentage >= self.profile.minimum_attendance_percentage
        )

    @property
    def certificate_eligible(self):
        if not self.automatically_certificate_eligible:
            return False
        return not self.profile.certificate_requires_manual_approval or self.certificate_approved

    def approve_certificate(self, user):
        if not self.automatically_certificate_eligible:
            raise ValidationError(_("Attendance and assessment requirements are not satisfied."))
        self.certificate_approved = True
        self.certificate_approved_at = timezone.now()
        self.certificate_approved_by = user
        self.save(update_fields=("certificate_approved", "certificate_approved_at", "certificate_approved_by", "updated_at"))

    def clean(self):
        if self.registration_id and self.registration.event_form.event_id != self.profile.event_id:
            raise ValidationError({"registration": _("The registration belongs to another event.")})

    def __str__(self):
        return self.full_name


class LearningAttendance(BaseModel):
    session = models.ForeignKey(LearningSession, related_name="attendance_records", on_delete=models.CASCADE)
    enrollment = models.ForeignKey(LearningEnrollment, related_name="attendance_records", on_delete=models.CASCADE)
    checked_in_at = models.DateTimeField(default=timezone.now)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="learning_attendance_records", on_delete=models.PROTECT,
    )

    class Meta:
        ordering = ("-checked_in_at",)
        constraints = [models.UniqueConstraint(
            fields=("session", "enrollment"), name="unique_learning_session_attendance",
        )]

    def clean(self):
        if self.session_id and self.enrollment_id and self.session.profile_id != self.enrollment.profile_id:
            raise ValidationError(_("The participant and session belong to different events."))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class LearningAssessment(BaseModel):
    class AssessmentType(models.TextChoices):
        PRE = "PRE", _("Pre-assessment")
        POST = "POST", _("Post-assessment")

    profile = models.ForeignKey(LearningEventProfile, related_name="assessments", on_delete=models.CASCADE)
    title = models.CharField(max_length=250)
    assessment_type = models.CharField(max_length=10, choices=AssessmentType.choices)
    maximum_score = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ("assessment_type", "title")
        constraints = [models.UniqueConstraint(
            fields=("profile", "title", "assessment_type"), name="unique_learning_assessment",
        )]

    def clean(self):
        if self.profile_id and normalized_category_code(self.profile.event) != "TRAINING":
            raise ValidationError({"profile": _("Assessments are available only for Training events.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class LearningAssessmentResult(BaseModel):
    assessment = models.ForeignKey(LearningAssessment, related_name="results", on_delete=models.CASCADE)
    enrollment = models.ForeignKey(LearningEnrollment, related_name="assessment_results", on_delete=models.CASCADE)
    score = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    submitted_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="learning_assessment_results", on_delete=models.PROTECT,
    )

    class Meta:
        ordering = ("-submitted_at", "-id")
        constraints = [models.UniqueConstraint(
            fields=("assessment", "enrollment"), name="unique_learning_assessment_result",
        )]

    @property
    def percentage(self):
        if not self.assessment.maximum_score:
            return Decimal("0.00")
        return (self.score * Decimal("100") / self.assessment.maximum_score).quantize(Decimal("0.01"))

    def clean(self):
        errors = {}
        if self.assessment_id and self.enrollment_id and self.assessment.profile_id != self.enrollment.profile_id:
            errors["enrollment"] = _("The participant and assessment belong to different events.")
        if self.assessment_id and self.score is not None and self.score > self.assessment.maximum_score:
            errors["score"] = _("The score cannot exceed the assessment maximum.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class WorkshopActivity(BaseModel):
    session = models.ForeignKey(LearningSession, related_name="activities", on_delete=models.CASCADE)
    title = models.CharField(max_length=250)
    instructions = models.TextField()
    due_at = models.DateTimeField(null=True, blank=True)
    maximum_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ("session", "due_at", "title")

    def clean(self):
        if self.session_id and normalized_category_code(self.session.profile.event) != "WORKSHOP":
            raise ValidationError({"session": _("Practical activities are available only for Workshop events.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class WorkshopActivitySubmission(BaseModel):
    activity = models.ForeignKey(WorkshopActivity, related_name="submissions", on_delete=models.CASCADE)
    enrollment = models.ForeignKey(LearningEnrollment, related_name="workshop_submissions", on_delete=models.CASCADE)
    response = models.TextField(blank=True)
    attachment = models.FileField(upload_to="learning-events/workshop-outputs/", blank=True, null=True)
    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-submitted_at",)
        constraints = [models.UniqueConstraint(
            fields=("activity", "enrollment"), name="unique_workshop_activity_submission",
        )]

    def clean(self):
        errors = {}
        if self.activity_id and self.enrollment_id and self.activity.session.profile_id != self.enrollment.profile_id:
            errors["enrollment"] = _("The participant and activity belong to different events.")
        if self.activity_id and self.score is not None and self.activity.maximum_score is not None and self.score > self.activity.maximum_score:
            errors["score"] = _("The score cannot exceed the activity maximum.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SeminarQuestion(BaseModel):
    profile = models.ForeignKey(LearningEventProfile, related_name="seminar_questions", on_delete=models.CASCADE)
    session = models.ForeignKey(LearningSession, related_name="seminar_questions", on_delete=models.SET_NULL, null=True, blank=True)
    participant_name = models.CharField(max_length=200, blank=True)
    question = models.TextField()
    answer = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-submitted_at",)

    def clean(self):
        if self.profile_id and normalized_category_code(self.profile.event) != "SEMINAR":
            raise ValidationError({"profile": _("Audience questions are available only for Seminar events.")})
        if self.session_id and self.session.profile_id != self.profile_id:
            raise ValidationError({"session": _("The session belongs to another event.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
