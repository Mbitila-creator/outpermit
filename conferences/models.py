import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from events.models import Event
from forms_builder.models import FormSubmission


class ConferenceSession(BaseModel):
    event = models.ForeignKey(
        Event,
        related_name="conference_sessions",
        on_delete=models.CASCADE,
        verbose_name=_("conference event"),
    )
    code = models.CharField(_("session code"), max_length=80)
    title = models.CharField(_("session title"), max_length=300)
    starts_at = models.DateTimeField(_("session starts"))
    ends_at = models.DateTimeField(_("session ends"))
    venue_name = models.CharField(_("session venue"), max_length=250, blank=True)
    registration_option_value = models.CharField(
        _("registration option value"),
        max_length=100,
        help_text=_("Stored value of the matching registration-form option."),
    )
    display_order = models.PositiveIntegerField(_("display order"), default=0)

    class Meta:
        ordering = ("starts_at", "display_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "code"),
                name="unique_conference_session_code_per_event",
            ),
            models.UniqueConstraint(
                fields=("event", "registration_option_value"),
                name="unique_conference_session_option_per_event",
            ),
        ]

    def clean(self):
        errors = {}
        if self.event_id and not self.event.category.is_conference:
            errors["event"] = _("Select an event in the Conference category.")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = _("The session must end after it starts.")
        if self.event_id and self.starts_at and self.starts_at < self.event.starts_at:
            errors["starts_at"] = _("The session cannot start before the conference.")
        if self.event_id and self.ends_at and self.ends_at > self.event.ends_at:
            errors["ends_at"] = _("The session cannot end after the conference.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.registration_option_value = self.registration_option_value.strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event.code} — {self.title}"


class ConferenceGuidingTopic(BaseModel):
    session = models.ForeignKey(ConferenceSession, related_name="guiding_topics", on_delete=models.CASCADE, verbose_name=_("conference session"))
    title = models.CharField(_("guiding subtopic"), max_length=500)
    description = models.TextField(_("description"), blank=True)
    display_order = models.PositiveIntegerField(_("display order"), default=0)

    class Meta:
        ordering = ("session", "display_order", "id")
        constraints = [models.UniqueConstraint(fields=("session", "title"), name="unique_guiding_topic_per_session")]

    def __str__(self):
        return f"{self.session.title} — {self.title}"


class ConferenceGuidingQuestion(BaseModel):
    topic = models.ForeignKey(ConferenceGuidingTopic, related_name="questions", on_delete=models.CASCADE, verbose_name=_("guiding subtopic"))
    text = models.TextField(_("question"))
    display_order = models.PositiveIntegerField(_("display order"), default=0)

    class Meta:
        ordering = ("topic", "display_order", "id")
        constraints = [models.UniqueConstraint(fields=("topic", "text"), name="unique_guiding_question_per_topic")]

    def __str__(self):
        return self.text


class ConferenceGuidingSubmission(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted")

    submission = models.ForeignKey(FormSubmission, related_name="conference_guiding_submissions", on_delete=models.CASCADE, verbose_name=_("participant registration"))
    session = models.ForeignKey(ConferenceSession, related_name="guiding_submissions", on_delete=models.CASCADE, verbose_name=_("conference session"))
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField(_("submitted at"), null=True, blank=True)

    class Meta:
        ordering = ("submission", "session")
        constraints = [models.UniqueConstraint(fields=("submission", "session"), name="unique_participant_guiding_session_submission")]

    def __str__(self):
        return f"{self.submission.reference_number} — {self.session.title}"


class ConferenceGuidingResponse(BaseModel):
    submission = models.ForeignKey(FormSubmission, related_name="conference_guiding_responses", on_delete=models.CASCADE, verbose_name=_("participant registration"))
    question = models.ForeignKey(ConferenceGuidingQuestion, related_name="responses", on_delete=models.CASCADE, verbose_name=_("guiding question"))
    response = models.TextField(_("response"), blank=True)

    class Meta:
        ordering = ("submission", "question")
        constraints = [models.UniqueConstraint(fields=("submission", "question"), name="unique_participant_guiding_response")]

    def __str__(self):
        return f"{self.submission.reference_number} — {self.question}"


class ConferenceSessionAttendance(BaseModel):
    class Method(models.TextChoices):
        QR = "QR", _("QR code")
        MANUAL = "MANUAL", _("Manual lookup")

    session = models.ForeignKey(
        ConferenceSession,
        related_name="attendance_records",
        on_delete=models.CASCADE,
        verbose_name=_("conference session"),
    )
    submission = models.ForeignKey(
        FormSubmission,
        related_name="conference_session_attendance",
        on_delete=models.CASCADE,
        verbose_name=_("participant registration"),
    )
    checked_in_at = models.DateTimeField(_("checked in at"), auto_now_add=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="conference_session_checkins",
        on_delete=models.PROTECT,
        verbose_name=_("checked in by"),
    )
    method = models.CharField(
        _("check-in method"),
        max_length=20,
        choices=Method.choices,
        default=Method.QR,
    )

    class Meta:
        ordering = ("-checked_in_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("session", "submission"),
                name="unique_participant_checkin_per_conference_session",
            ),
        ]

    def clean(self):
        errors = {}
        if (
            self.session_id
            and self.submission_id
            and self.submission.event_form.event_id != self.session.event_id
        ):
            errors["submission"] = _(
                "The participant registration belongs to another event."
            )
        if (
            self.submission_id
            and self.submission.review_status
            != FormSubmission.ReviewStatus.APPROVED
        ):
            errors["submission"] = _("Only approved participants may check in.")
        if (
            self.session_id
            and self.submission_id
            and not self.submission.answers.filter(
                question__section__event_form=self.submission.event_form,
                selected_options__value=self.session.registration_option_value,
                selected_options__is_active=True,
            ).exists()
        ):
            errors["submission"] = _("The participant did not select this session.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.session.code} — {self.submission.reference_number}"


class ConferenceSpeaker(BaseModel):
    event = models.ForeignKey(
        Event,
        related_name="conference_speakers",
        on_delete=models.CASCADE,
        verbose_name=_("conference event"),
    )
    full_name = models.CharField(_("full name"), max_length=200)
    position_title = models.CharField(_("position / title"), max_length=200, blank=True)
    institution = models.CharField(_("institution"), max_length=250, blank=True)
    biography = models.TextField(_("short biography"), blank=True)
    photo = models.ImageField(
        _("photo"),
        upload_to="conferences/speakers/",
        blank=True,
        null=True,
    )
    display_order = models.PositiveIntegerField(_("display order"), default=0)

    class Meta:
        ordering = ("display_order", "full_name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "full_name", "institution"),
                name="unique_conference_speaker_per_event",
            ),
        ]

    def clean(self):
        if self.event_id and not self.event.category.is_conference:
            raise ValidationError({
                "event": _("Select an event in the Conference category."),
            })

    def save(self, *args, **kwargs):
        self.full_name = self.full_name.strip()
        self.position_title = self.position_title.strip()
        self.institution = self.institution.strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name


class ConferenceProgrammeItem(BaseModel):
    class ItemType(models.TextChoices):
        OPENING = "OPENING", _("Opening")
        KEYNOTE = "KEYNOTE", _("Keynote address")
        PRESENTATION = "PRESENTATION", _("Presentation")
        PANEL = "PANEL", _("Panel discussion")
        WORKSHOP = "WORKSHOP", _("Workshop")
        BREAK = "BREAK", _("Break")
        NETWORKING = "NETWORKING", _("Networking")
        CLOSING = "CLOSING", _("Closing")
        OTHER = "OTHER", _("Other")

    session = models.ForeignKey(
        ConferenceSession,
        related_name="programme_items",
        on_delete=models.CASCADE,
        verbose_name=_("conference session"),
    )
    code = models.CharField(_("programme item code"), max_length=80)
    item_type = models.CharField(
        _("programme item type"),
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.PRESENTATION,
    )
    title = models.CharField(_("programme title"), max_length=300)
    description = models.TextField(_("description"), blank=True)
    starts_at = models.DateTimeField(_("programme item starts"))
    ends_at = models.DateTimeField(_("programme item ends"))
    venue_name = models.CharField(_("venue"), max_length=250, blank=True)
    is_published = models.BooleanField(_("published"), default=False)
    display_order = models.PositiveIntegerField(_("display order"), default=0)
    speakers = models.ManyToManyField(
        ConferenceSpeaker,
        related_name="programme_items",
        through="ConferenceProgrammeContributor",
        blank=True,
        verbose_name=_("speakers and facilitators"),
    )

    class Meta:
        ordering = ("starts_at", "display_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("session", "code"),
                name="unique_programme_item_code_per_session",
            ),
        ]

    def clean(self):
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = _("The programme item must end after it starts.")
        if self.session_id and self.starts_at and self.starts_at < self.session.starts_at:
            errors["starts_at"] = _("The programme item cannot start before its session.")
        if self.session_id and self.ends_at and self.ends_at > self.session.ends_at:
            errors["ends_at"] = _("The programme item cannot end after its session.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.title = self.title.strip()
        if not self.venue_name and self.session_id:
            self.venue_name = self.session.venue_name
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.session.code} — {self.title}"


class ConferenceProgrammeContributor(BaseModel):
    class Role(models.TextChoices):
        SPEAKER = "SPEAKER", _("Speaker")
        KEYNOTE_SPEAKER = "KEYNOTE_SPEAKER", _("Keynote speaker")
        MODERATOR = "MODERATOR", _("Moderator")
        PANELIST = "PANELIST", _("Panelist")
        FACILITATOR = "FACILITATOR", _("Facilitator")

    programme_item = models.ForeignKey(
        ConferenceProgrammeItem,
        related_name="contributors",
        on_delete=models.CASCADE,
        verbose_name=_("programme item"),
    )
    speaker = models.ForeignKey(
        ConferenceSpeaker,
        related_name="programme_contributions",
        on_delete=models.CASCADE,
        verbose_name=_("speaker / facilitator"),
    )
    role = models.CharField(
        _("programme role"),
        max_length=30,
        choices=Role.choices,
        default=Role.SPEAKER,
    )
    display_order = models.PositiveIntegerField(_("display order"), default=0)

    class Meta:
        ordering = ("display_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("programme_item", "speaker", "role"),
                name="unique_contributor_role_per_programme_item",
            ),
        ]

    def clean(self):
        if (
            self.programme_item_id
            and self.speaker_id
            and self.programme_item.session.event_id != self.speaker.event_id
        ):
            raise ValidationError({
                "speaker": _("The contributor belongs to another conference."),
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.speaker} — {self.get_role_display()}"


class ConferenceCallForPapers(BaseModel):
    event = models.OneToOneField(
        Event,
        related_name="conference_call_for_papers",
        on_delete=models.CASCADE,
        verbose_name=_("conference event"),
    )
    title = models.CharField(_("call title"), max_length=250)
    introduction = models.TextField(_("introduction"))
    guidelines = models.TextField(_("submission guidelines"))
    opens_at = models.DateTimeField(_("opens at"), null=True, blank=True)
    closes_at = models.DateTimeField(_("closes at"), null=True, blank=True)
    is_published = models.BooleanField(_("published"), default=False)

    class Meta:
        verbose_name = _("conference call for papers")
        verbose_name_plural = _("conference calls for papers")

    def clean(self):
        errors = {}
        if self.event_id and not self.event.category.is_conference:
            errors["event"] = _("Select an event in the Conference category.")
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            errors["closes_at"] = _("The closing time must be after the opening time.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event.code} — {self.title}"


class ConferencePaper(BaseModel):
    class SubmissionType(models.TextChoices):
        ABSTRACT = "ABSTRACT", _("Abstract")
        FULL_PAPER = "FULL_PAPER", _("Full paper")

    class PresentationFormat(models.TextChoices):
        ORAL = "ORAL", _("Oral presentation")
        POSTER = "POSTER", _("Poster presentation")
        PANEL = "PANEL", _("Panel contribution")
        WORKSHOP = "WORKSHOP", _("Workshop contribution")

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", _("Submitted")
        UNDER_REVIEW = "UNDER_REVIEW", _("Under review")
        REVISION_REQUIRED = "REVISION_REQUIRED", _("Revision required")
        ACCEPTED = "ACCEPTED", _("Accepted")
        REJECTED = "REJECTED", _("Rejected")
        WITHDRAWN = "WITHDRAWN", _("Withdrawn")

    call = models.ForeignKey(
        ConferenceCallForPapers,
        related_name="papers",
        on_delete=models.CASCADE,
        verbose_name=_("call for papers"),
    )
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reference_number = models.CharField(
        _("reference number"), max_length=80, unique=True, null=True, blank=True,
    )
    submission_type = models.CharField(
        _("submission type"), max_length=20, choices=SubmissionType.choices,
        default=SubmissionType.ABSTRACT,
    )
    presentation_format = models.CharField(
        _("preferred presentation format"), max_length=20,
        choices=PresentationFormat.choices, default=PresentationFormat.ORAL,
    )
    title = models.CharField(_("research / paper title"), max_length=400)
    abstract = models.TextField(_("abstract"))
    thematic_area = models.CharField(_("thematic area"), max_length=250)
    keywords = models.CharField(_("keywords"), max_length=400, blank=True)
    corresponding_author = models.CharField(_("corresponding author"), max_length=200)
    institution = models.CharField(_("institution"), max_length=250)
    email = models.EmailField(_("email address"))
    phone = models.CharField(_("phone number"), max_length=40)
    co_authors = models.TextField(
        _("co-authors"), blank=True,
        help_text=_("Enter one co-author per line, including institution where applicable."),
    )
    document = models.FileField(
        _("abstract or paper document"), upload_to="conferences/papers/%Y/%m/",
        blank=True, null=True,
        validators=[FileExtensionValidator(("pdf", "doc", "docx"))],
    )
    status = models.CharField(
        _("review status"), max_length=30, choices=Status.choices,
        default=Status.SUBMITTED,
    )
    assigned_session = models.ForeignKey(
        ConferenceSession, related_name="accepted_papers", on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name=_("assigned conference session"),
    )
    decision_message = models.TextField(_("message to the author"), blank=True)
    internal_notes = models.TextField(_("internal review notes"), blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="reviewed_conference_papers",
        on_delete=models.SET_NULL, null=True, blank=True, editable=False,
        verbose_name=_("reviewed by"),
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True, editable=False)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("call", "email", "title"),
                name="unique_conference_paper_title_per_author",
            ),
        ]

    def clean(self):
        errors = {}
        if (
            self.assigned_session_id
            and self.call_id
            and self.assigned_session.event_id != self.call.event_id
        ):
            errors["assigned_session"] = _("Select a session from the same conference.")
        uploaded_file = getattr(self.document, "_file", None)
        if uploaded_file and uploaded_file.size > 10 * 1024 * 1024:
            errors["document"] = _("The uploaded document must not exceed 10 MB.")
        if self.submission_type == self.SubmissionType.FULL_PAPER and not self.document:
            errors["document"] = _("Upload the document when submitting a full paper.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
        self.corresponding_author = self.corresponding_author.strip()
        self.institution = self.institution.strip()
        self.email = self.email.strip().lower()
        self.full_clean()
        super().save(*args, **kwargs)
        if not self.reference_number:
            reference = f"{self.call.event.code}-ABS-{self.pk:05d}"
            type(self).objects.filter(pk=self.pk).update(reference_number=reference)
            self.reference_number = reference

    def __str__(self):
        return f"{self.reference_number or 'New'} — {self.title}"


class ConferencePaperReview(BaseModel):
    paper = models.ForeignKey(
        ConferencePaper, related_name="review_history", on_delete=models.CASCADE,
        verbose_name=_("conference paper"),
    )
    decision = models.CharField(
        _("decision"), max_length=30, choices=ConferencePaper.Status.choices,
    )
    message_to_author = models.TextField(_("message to the author"), blank=True)
    internal_notes = models.TextField(_("internal notes"), blank=True)
    assigned_session = models.ForeignKey(
        ConferenceSession, related_name="paper_review_assignments",
        on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_("assigned conference session"),
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="conference_paper_reviews",
        on_delete=models.PROTECT, verbose_name=_("reviewer"),
    )

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        if (
            self.assigned_session_id
            and self.paper_id
            and self.assigned_session.event_id != self.paper.call.event_id
        ):
            raise ValidationError({
                "assigned_session": _("Select a session from the same conference."),
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.paper.reference_number} — {self.get_decision_display()}"


class ConferenceReviewer(BaseModel):
    event = models.ForeignKey(
        Event, related_name="conference_reviewers", on_delete=models.CASCADE,
        verbose_name=_("conference event"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="conference_reviewer_profiles",
        on_delete=models.CASCADE, verbose_name=_("reviewer account"),
    )
    institution = models.CharField(_("institution"), max_length=250, blank=True)
    expertise = models.TextField(
        _("areas of expertise"),
        help_text=_("Enter the research fields or thematic areas this reviewer can assess."),
    )

    class Meta:
        ordering = ("user__first_name", "user__last_name", "user__username")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "user"), name="unique_reviewer_per_conference",
            ),
        ]

    def clean(self):
        if self.event_id and not self.event.category.is_conference:
            raise ValidationError({"event": _("Select a Conference event.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} — {self.event.code}"


class ConferencePaperReviewAssignment(BaseModel):
    class Status(models.TextChoices):
        ASSIGNED = "ASSIGNED", _("Assigned")
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        COMPLETED = "COMPLETED", _("Completed")
        CONFLICT = "CONFLICT", _("Conflict of interest")

    class Recommendation(models.TextChoices):
        ACCEPT = "ACCEPT", _("Accept")
        MINOR_REVISION = "MINOR_REVISION", _("Minor revision")
        MAJOR_REVISION = "MAJOR_REVISION", _("Major revision")
        REJECT = "REJECT", _("Reject")

    paper = models.ForeignKey(
        ConferencePaper, related_name="peer_review_assignments",
        on_delete=models.CASCADE, verbose_name=_("conference paper"),
    )
    reviewer = models.ForeignKey(
        ConferenceReviewer, related_name="assignments",
        on_delete=models.PROTECT, verbose_name=_("reviewer"),
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="assigned_conference_paper_reviews",
        on_delete=models.PROTECT, verbose_name=_("assigned by"),
    )
    due_at = models.DateTimeField(_("review deadline"), null=True, blank=True)
    status = models.CharField(
        _("assignment status"), max_length=20, choices=Status.choices,
        default=Status.ASSIGNED,
    )
    conflict_reason = models.TextField(_("conflict reason"), blank=True)
    relevance_score = models.PositiveSmallIntegerField(_("relevance score"), null=True, blank=True)
    originality_score = models.PositiveSmallIntegerField(_("originality score"), null=True, blank=True)
    methodology_score = models.PositiveSmallIntegerField(_("methodology score"), null=True, blank=True)
    clarity_score = models.PositiveSmallIntegerField(_("clarity score"), null=True, blank=True)
    impact_score = models.PositiveSmallIntegerField(_("potential impact score"), null=True, blank=True)
    recommendation = models.CharField(
        _("recommendation"), max_length=30, choices=Recommendation.choices, blank=True,
    )
    comments_to_author = models.TextField(_("comments to the author"), blank=True)
    confidential_comments = models.TextField(_("confidential comments"), blank=True)
    submitted_at = models.DateTimeField(_("review submitted at"), null=True, blank=True)

    class Meta:
        ordering = ("due_at", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("paper", "reviewer"), name="unique_reviewer_assignment_per_paper",
            ),
        ]

    @property
    def average_score(self):
        scores = (
            self.relevance_score, self.originality_score, self.methodology_score,
            self.clarity_score, self.impact_score,
        )
        if any(score is None for score in scores):
            return None
        return sum(scores) / len(scores)

    def clean(self):
        errors = {}
        if self.paper_id and self.reviewer_id and self.paper.call.event_id != self.reviewer.event_id:
            errors["reviewer"] = _("The reviewer belongs to another conference.")
        scores = {
            "relevance_score": self.relevance_score,
            "originality_score": self.originality_score,
            "methodology_score": self.methodology_score,
            "clarity_score": self.clarity_score,
            "impact_score": self.impact_score,
        }
        for field_name, score in scores.items():
            if score is not None and score not in range(1, 6):
                errors[field_name] = _("Enter a score from 1 to 5.")
        if self.status == self.Status.COMPLETED:
            for field_name, score in scores.items():
                if score is None:
                    errors[field_name] = _("All scores are required to complete the review.")
            if not self.recommendation:
                errors["recommendation"] = _("Select a recommendation.")
        if self.status == self.Status.CONFLICT and not self.conflict_reason.strip():
            errors["conflict_reason"] = _("Explain the conflict of interest.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.paper.reference_number} — {self.reviewer}"


class ConferencePresentation(BaseModel):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", _("Scheduled")
        CONFIRMED = "CONFIRMED", _("Confirmed by presenter")
        READY = "READY", _("Slides received / ready")
        DELIVERED = "DELIVERED", _("Delivered")
        CANCELLED = "CANCELLED", _("Cancelled")

    paper = models.OneToOneField(
        ConferencePaper, related_name="presentation", on_delete=models.CASCADE,
        verbose_name=_("accepted paper"),
    )
    session = models.ForeignKey(
        ConferenceSession, related_name="paper_presentations", on_delete=models.PROTECT,
        verbose_name=_("conference session"),
    )
    programme_item = models.ForeignKey(
        ConferenceProgrammeItem, related_name="paper_presentations",
        on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_("programme item"),
    )
    presenter_name = models.CharField(_("presenter name"), max_length=200)
    starts_at = models.DateTimeField(_("presentation starts"))
    ends_at = models.DateTimeField(_("presentation ends"))
    venue_name = models.CharField(_("presentation venue"), max_length=250, blank=True)
    status = models.CharField(
        _("presentation status"), max_length=20, choices=Status.choices,
        default=Status.SCHEDULED,
    )
    slides = models.FileField(
        _("presentation slides"), upload_to="conferences/presentations/%Y/%m/",
        blank=True, null=True,
        validators=[FileExtensionValidator(("pdf", "ppt", "pptx"))],
    )
    presenter_notes = models.TextField(_("presenter notes"), blank=True)
    manager_notes = models.TextField(_("manager notes"), blank=True)
    confirmed_at = models.DateTimeField(_("confirmed at"), null=True, blank=True)

    class Meta:
        ordering = ("starts_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("session", "starts_at", "venue_name"),
                name="unique_presentation_slot_per_venue",
            ),
        ]

    def clean(self):
        errors = {}
        if self.paper_id and self.paper.status != ConferencePaper.Status.ACCEPTED:
            errors["paper"] = _("Only accepted papers may be scheduled for presentation.")
        if self.paper_id and self.session_id and self.paper.call.event_id != self.session.event_id:
            errors["session"] = _("Select a session from the paper's conference.")
        if self.programme_item_id and self.session_id and self.programme_item.session_id != self.session_id:
            errors["programme_item"] = _("Select a programme item from the chosen session.")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = _("The presentation must end after it starts.")
        if self.session_id and self.starts_at and self.starts_at < self.session.starts_at:
            errors["starts_at"] = _("The presentation cannot start before its session.")
        if self.session_id and self.ends_at and self.ends_at > self.session.ends_at:
            errors["ends_at"] = _("The presentation cannot end after its session.")
        uploaded_file = getattr(self.slides, "_file", None)
        if uploaded_file and uploaded_file.size > 20 * 1024 * 1024:
            errors["slides"] = _("Presentation slides must not exceed 20 MB.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.presenter_name = self.presenter_name.strip()
        if not self.venue_name and self.session_id:
            self.venue_name = self.session.venue_name
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.paper.reference_number} — {self.starts_at:%d %b %Y %H:%M}"


class ConferencePaperCommunication(BaseModel):
    class CommunicationType(models.TextChoices):
        ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT", _("Submission acknowledgement")
        REVISION = "REVISION", _("Revision request")
        ACCEPTANCE = "ACCEPTANCE", _("Acceptance notification")
        REJECTION = "REJECTION", _("Rejection notification")
        PRESENTATION_INVITATION = "PRESENTATION_INVITATION", _("Presentation invitation")
        PRESENTATION_REMINDER = "PRESENTATION_REMINDER", _("Presentation reminder")
        OTHER = "OTHER", _("Other communication")

    class DeliveryStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        SENT = "SENT", _("Sent")
        FAILED = "FAILED", _("Failed")

    paper = models.ForeignKey(
        ConferencePaper, related_name="communications", on_delete=models.CASCADE,
        verbose_name=_("conference paper"),
    )
    communication_type = models.CharField(
        _("communication type"), max_length=30, choices=CommunicationType.choices,
    )
    recipient_email = models.EmailField(_("recipient email"))
    subject = models.CharField(_("email subject"), max_length=300)
    message = models.TextField(_("message"))
    delivery_status = models.CharField(
        _("delivery status"), max_length=20, choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="sent_conference_paper_communications",
        on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_("sent by"),
    )
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)
    failure_message = models.TextField(_("failure message"), blank=True)

    class Meta:
        ordering = ("-created_at",)

    def save(self, *args, **kwargs):
        self.recipient_email = self.recipient_email.strip().lower()
        self.subject = self.subject.strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.paper.reference_number} — {self.get_communication_type_display()}"


class ConferenceCertificate(BaseModel):
    class RecipientType(models.TextChoices):
        PARTICIPANT = "PARTICIPANT", _("Participant")
        PRESENTER = "PRESENTER", _("Presenter")
        REVIEWER = "REVIEWER", _("Peer reviewer")

    event = models.ForeignKey(
        Event, related_name="conference_certificates", on_delete=models.CASCADE,
        verbose_name=_("conference event"),
    )
    recipient_type = models.CharField(
        _("recipient type"), max_length=20, choices=RecipientType.choices,
    )
    recipient_name = models.CharField(_("recipient name"), max_length=200)
    institution = models.CharField(_("institution"), max_length=250, blank=True)
    participant_submission = models.ForeignKey(
        FormSubmission, related_name="conference_certificates",
        on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_("participant registration"),
    )
    paper = models.ForeignKey(
        ConferencePaper, related_name="conference_certificates",
        on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_("presented paper"),
    )
    reviewer = models.ForeignKey(
        ConferenceReviewer, related_name="conference_certificates",
        on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_("peer reviewer"),
    )
    certificate_number = models.CharField(
        _("certificate number"), max_length=100, unique=True,
    )
    verification_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="issued_conference_certificates",
        on_delete=models.PROTECT, verbose_name=_("issued by"),
    )
    issued_at = models.DateTimeField(_("issued at"), auto_now_add=True)
    is_revoked = models.BooleanField(_("revoked"), default=False)
    revocation_reason = models.TextField(_("revocation reason"), blank=True)

    class Meta:
        ordering = ("-issued_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("event", "recipient_type", "participant_submission"),
                condition=models.Q(participant_submission__isnull=False),
                name="unique_participant_conference_certificate",
            ),
            models.UniqueConstraint(
                fields=("event", "recipient_type", "paper"),
                condition=models.Q(paper__isnull=False),
                name="unique_presenter_conference_certificate",
            ),
            models.UniqueConstraint(
                fields=("event", "recipient_type", "reviewer"),
                condition=models.Q(reviewer__isnull=False),
                name="unique_reviewer_conference_certificate",
            ),
        ]

    def clean(self):
        errors = {}
        source_fields = {
            self.RecipientType.PARTICIPANT: "participant_submission",
            self.RecipientType.PRESENTER: "paper",
            self.RecipientType.REVIEWER: "reviewer",
        }
        required_source = source_fields.get(self.recipient_type)
        for field_name in source_fields.values():
            if field_name == required_source and not getattr(self, f"{field_name}_id"):
                errors[field_name] = _("Select the record that supports this certificate.")
            elif field_name != required_source and getattr(self, f"{field_name}_id"):
                errors[field_name] = _("This record does not match the recipient type.")
        if self.participant_submission_id and self.participant_submission.event_form.event_id != self.event_id:
            errors["participant_submission"] = _("The participant belongs to another event.")
        if self.paper_id and self.paper.call.event_id != self.event_id:
            errors["paper"] = _("The paper belongs to another event.")
        if self.reviewer_id and self.reviewer.event_id != self.event_id:
            errors["reviewer"] = _("The reviewer belongs to another event.")
        if self.is_revoked and not self.revocation_reason.strip():
            errors["revocation_reason"] = _("Enter a reason for revoking the certificate.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.recipient_name = self.recipient_name.strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.certificate_number} — {self.recipient_name}"


class ConferenceFeedback(BaseModel):
    RATING_CHOICES = tuple((value, str(value)) for value in range(1, 6))

    event = models.ForeignKey(
        Event, related_name="conference_feedback", on_delete=models.CASCADE,
        verbose_name=_("conference event"),
    )
    session = models.ForeignKey(
        ConferenceSession, related_name="feedback_responses",
        on_delete=models.PROTECT, null=True, blank=True,
        verbose_name=_("conference session"),
    )
    reference_number = models.CharField(
        _("feedback reference"), max_length=100, unique=True, null=True, blank=True,
    )
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_anonymous = models.BooleanField(_("submit anonymously"), default=True)
    respondent_name = models.CharField(_("respondent name"), max_length=200, blank=True)
    institution = models.CharField(_("institution"), max_length=250, blank=True)
    email = models.EmailField(_("email address"), blank=True)
    overall_rating = models.PositiveSmallIntegerField(
        _("overall experience"), choices=RATING_CHOICES,
    )
    content_rating = models.PositiveSmallIntegerField(
        _("content relevance and quality"), choices=RATING_CHOICES,
    )
    speakers_rating = models.PositiveSmallIntegerField(
        _("speakers and presentations"), choices=RATING_CHOICES,
    )
    organization_rating = models.PositiveSmallIntegerField(
        _("organization and communication"), choices=RATING_CHOICES,
    )
    venue_rating = models.PositiveSmallIntegerField(
        _("venue and facilities"), choices=RATING_CHOICES,
    )
    would_recommend = models.BooleanField(_("would recommend this conference"))
    most_valuable = models.TextField(_("most valuable aspect"), blank=True)
    improvements = models.TextField(_("suggested improvements"), blank=True)
    additional_comments = models.TextField(_("additional comments"), blank=True)

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        errors = {}
        if self.event_id and not self.event.category.is_conference:
            errors["event"] = _("Select a Conference event.")
        if self.session_id and self.event_id and self.session.event_id != self.event_id:
            errors["session"] = _("Select a session from the same conference.")
        if not self.is_anonymous and not self.respondent_name.strip():
            errors["respondent_name"] = _("Enter your name or submit anonymously.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.is_anonymous:
            self.respondent_name = ""
            self.institution = ""
            self.email = ""
        else:
            self.respondent_name = self.respondent_name.strip()
            self.institution = self.institution.strip()
            self.email = self.email.strip().lower()
        self.full_clean()
        super().save(*args, **kwargs)
        if not self.reference_number:
            reference = f"{self.event.code}-FB-{self.pk:05d}"
            type(self).objects.filter(pk=self.pk).update(reference_number=reference)
            self.reference_number = reference

    @property
    def display_name(self):
        return _("Anonymous respondent") if self.is_anonymous else self.respondent_name

    def __str__(self):
        return f"{self.reference_number or 'New'} — {self.display_name}"
