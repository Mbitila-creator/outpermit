import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from events.models import Event


MAX_MEETING_DOCUMENT_SIZE = 20 * 1024 * 1024
ALLOWED_MEETING_DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".jpg", ".jpeg", ".png",
}


class Meeting(BaseModel):
    """Meeting-specific configuration attached to the shared event record."""

    class MeetingType(models.TextChoices):
        MANAGEMENT = "MANAGEMENT", _("Management meeting")
        TECHNICAL = "TECHNICAL", _("Technical meeting")
        COMMITTEE = "COMMITTEE", _("Committee meeting")
        BOARD = "BOARD", _("Board meeting")
        STAKEHOLDER = "STAKEHOLDER", _("Stakeholder meeting")
        WORKING_SESSION = "WORKING_SESSION", _("Working session")
        OTHER = "OTHER", _("Other meeting")

    class MinutesStatus(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", _("Not started")
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted for approval")
        RETURNED = "RETURNED", _("Returned for correction")
        APPROVED = "APPROVED", _("Approved")

    class AttendanceMode(models.TextChoices):
        IN_PERSON = "IN_PERSON", _("In-person meeting")
        ONLINE = "ONLINE", _("Online meeting")
        HYBRID = "HYBRID", _("Hybrid meeting")

    class OnlinePlatform(models.TextChoices):
        ZOOM = "ZOOM", _("Zoom")
        MICROSOFT_TEAMS = "MICROSOFT_TEAMS", _("Microsoft Teams")
        GOOGLE_MEET = "GOOGLE_MEET", _("Google Meet")
        WEBEX = "WEBEX", _("Cisco Webex")
        OTHER = "OTHER", _("Other platform")

    class ClosureStatus(models.TextChoices):
        OPEN = "OPEN", _("Open for post-meeting work")
        CLOSED = "CLOSED", _("Formally closed")

    event = models.OneToOneField(
        Event,
        verbose_name=_("event"),
        related_name="meeting",
        on_delete=models.CASCADE,
    )
    series = models.ForeignKey(
        "MeetingSeries",
        verbose_name=_("meeting series"),
        related_name="meetings",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    reference_number = models.CharField(
        _("meeting reference number"),
        max_length=80,
        unique=True,
        help_text=_("Use the official meeting reference when available."),
    )
    meeting_type = models.CharField(
        _("meeting type"),
        max_length=30,
        choices=MeetingType.choices,
        default=MeetingType.MANAGEMENT,
    )
    attendance_mode = models.CharField(
        _("meeting attendance mode"),
        max_length=20,
        choices=AttendanceMode.choices,
        default=AttendanceMode.IN_PERSON,
    )
    online_platform = models.CharField(
        _("online meeting platform"),
        max_length=30,
        choices=OnlinePlatform.choices,
        blank=True,
    )
    online_join_url = models.URLField(
        _("online joining link"), max_length=500, blank=True,
    )
    online_meeting_id = models.CharField(
        _("online meeting ID"), max_length=120, blank=True,
    )
    online_passcode = models.CharField(
        _("online meeting passcode"), max_length=120, blank=True,
    )
    online_instructions_sw = models.TextField(
        _("online joining instructions in Kiswahili"), blank=True,
    )
    online_instructions_en = models.TextField(
        _("online joining instructions in English"), blank=True,
    )
    checkin_enabled = models.BooleanField(
        _("meeting QR check-in enabled"),
        default=False,
    )
    checkin_opens_at = models.DateTimeField(
        _("check-in opens at"),
        null=True,
        blank=True,
    )
    checkin_closes_at = models.DateTimeField(
        _("check-in closes at"),
        null=True,
        blank=True,
    )
    evaluation_enabled = models.BooleanField(
        _("participant evaluation enabled"),
        default=False,
    )
    evaluation_deadline = models.DateTimeField(
        _("evaluation deadline"),
        null=True,
        blank=True,
    )
    closure_status = models.CharField(
        _("meeting closure status"),
        max_length=20,
        choices=ClosureStatus.choices,
        default=ClosureStatus.OPEN,
    )
    closure_summary_sw = models.TextField(
        _("closure summary in Kiswahili"),
        blank=True,
    )
    closure_summary_en = models.TextField(
        _("closure summary in English"),
        blank=True,
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("meeting closed by"),
        related_name="closed_meetings",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    closed_at = models.DateTimeField(
        _("meeting closed at"),
        null=True,
        blank=True,
    )
    chairperson_name = models.CharField(
        _("chairperson"),
        max_length=200,
    )
    secretary_name = models.CharField(
        _("meeting secretary"),
        max_length=200,
        blank=True,
    )
    quorum_required = models.PositiveIntegerField(
        _("required quorum"),
        null=True,
        blank=True,
        help_text=_("Leave empty when the meeting has no formal quorum."),
    )
    invitation_deadline = models.DateTimeField(
        _("invitation response deadline"),
        null=True,
        blank=True,
    )
    objectives_sw = models.TextField(
        _("objectives in Kiswahili"),
        blank=True,
    )
    objectives_en = models.TextField(
        _("objectives in English"),
        blank=True,
    )
    minutes_status = models.CharField(
        _("minutes status"),
        max_length=20,
        choices=MinutesStatus.choices,
        default=MinutesStatus.NOT_STARTED,
    )
    minutes_sw = models.TextField(
        _("minutes in Kiswahili"),
        blank=True,
    )
    minutes_en = models.TextField(
        _("minutes in English"),
        blank=True,
    )
    minutes_document = models.FileField(
        _("signed minutes document"),
        upload_to="meetings/minutes/%Y/%m/",
        null=True,
        blank=True,
    )
    minutes_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("minutes approved by"),
        related_name="approved_meeting_minutes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    minutes_approved_at = models.DateTimeField(
        _("minutes approved at"),
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("meeting")
        verbose_name_plural = _("meetings")
        ordering = ["-event__starts_at", "reference_number"]
        indexes = [
            models.Index(
                fields=["meeting_type", "minutes_status"],
                name="meeting_type_minutes_idx",
            ),
        ]

    def clean(self):
        errors = {}
        if self.event_id and self.event.category.code.upper() != "MEETING":
            errors["event"] = _(
                "Only an event in the MEETING category can have meeting details."
            )
        if (
            self.invitation_deadline
            and self.event_id
            and self.invitation_deadline > self.event.starts_at
        ):
            errors["invitation_deadline"] = _(
                "The invitation deadline cannot be after the meeting starts."
            )
        if self.quorum_required == 0:
            errors["quorum_required"] = _(
                "The required quorum must be greater than zero."
            )
        if (
            self.checkin_opens_at
            and self.checkin_closes_at
            and self.checkin_closes_at <= self.checkin_opens_at
        ):
            errors["checkin_closes_at"] = _(
                "The check-in closing time must be after the opening time."
            )
        if (
            self.evaluation_deadline
            and self.event_id
            and self.evaluation_deadline <= self.event.ends_at
        ):
            errors["evaluation_deadline"] = _(
                "The evaluation deadline must be after the meeting ends."
            )
        if self.attendance_mode in {
            self.AttendanceMode.ONLINE,
            self.AttendanceMode.HYBRID,
        }:
            if not self.online_platform:
                errors["online_platform"] = _(
                    "Select the platform for an online or hybrid meeting."
                )
            if not self.online_join_url:
                errors["online_join_url"] = _(
                    "Enter the joining link for an online or hybrid meeting."
                )
        if (
            self.event_id
            and self.event.venue_id
            and self.event.status != Event.Status.CANCELLED
            and self.attendance_mode != self.AttendanceMode.ONLINE
        ):
            conflicts = Event.objects.filter(
                venue_id=self.event.venue_id,
                starts_at__lt=self.event.ends_at,
                ends_at__gt=self.event.starts_at,
            ).exclude(
                pk=self.event_id,
            ).exclude(
                status=Event.Status.CANCELLED,
            )
            if conflicts.exists():
                errors["event"] = _(
                    "This venue is already booked during the selected time."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.reference_number = self.reference_number.strip().upper()
        if (
            self.minutes_status == self.MinutesStatus.APPROVED
            and not self.minutes_approved_at
        ):
            self.minutes_approved_at = timezone.now()
        if self.closure_status == self.ClosureStatus.CLOSED and not self.closed_at:
            self.closed_at = timezone.now()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference_number} - {self.event.title_sw}"

    def get_absolute_url(self):
        return reverse("meetings:meeting_detail", kwargs={"meeting_id": self.pk})


class MeetingSeries(BaseModel):
    class Frequency(models.TextChoices):
        ON_DEMAND = "ON_DEMAND", _("On demand")
        WEEKLY = "WEEKLY", _("Weekly")
        MONTHLY = "MONTHLY", _("Monthly")
        QUARTERLY = "QUARTERLY", _("Quarterly")
        ANNUALLY = "ANNUALLY", _("Annually")

    code = models.CharField(_("series code"), max_length=50, unique=True)
    name_sw = models.CharField(_("series name in Kiswahili"), max_length=250)
    name_en = models.CharField(_("series name in English"), max_length=250)
    description_sw = models.TextField(_("description in Kiswahili"), blank=True)
    description_en = models.TextField(_("description in English"), blank=True)
    frequency = models.CharField(
        _("meeting frequency"),
        max_length=20,
        choices=Frequency.choices,
        default=Frequency.MONTHLY,
    )
    meeting_type = models.CharField(
        _("default meeting type"),
        max_length=30,
        choices=Meeting.MeetingType.choices,
        default=Meeting.MeetingType.MANAGEMENT,
    )
    attendance_mode = models.CharField(
        _("default meeting attendance mode"),
        max_length=20,
        choices=Meeting.AttendanceMode.choices,
        default=Meeting.AttendanceMode.IN_PERSON,
    )
    online_platform = models.CharField(
        _("default online meeting platform"),
        max_length=30,
        choices=Meeting.OnlinePlatform.choices,
        blank=True,
    )
    online_join_url = models.URLField(
        _("default online joining link"), max_length=500, blank=True,
    )
    online_meeting_id = models.CharField(
        _("default online meeting ID"), max_length=120, blank=True,
    )
    online_passcode = models.CharField(
        _("default online meeting passcode"), max_length=120, blank=True,
    )
    online_instructions_sw = models.TextField(
        _("default online joining instructions in Kiswahili"), blank=True,
    )
    online_instructions_en = models.TextField(
        _("default online joining instructions in English"), blank=True,
    )
    default_duration_minutes = models.PositiveIntegerField(
        _("default duration in minutes"),
        default=120,
    )
    venue = models.ForeignKey(
        "events.Venue",
        verbose_name=_("default venue"),
        related_name="meeting_series",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    chairperson_name = models.CharField(_("default chairperson"), max_length=200)
    secretary_name = models.CharField(
        _("default secretary"),
        max_length=200,
        blank=True,
    )
    quorum_required = models.PositiveIntegerField(
        _("default required quorum"),
        null=True,
        blank=True,
    )
    objectives_sw = models.TextField(_("default objectives in Kiswahili"), blank=True)
    objectives_en = models.TextField(_("default objectives in English"), blank=True)

    class Meta:
        verbose_name = _("meeting series")
        verbose_name_plural = _("meeting series")
        ordering = ["name_sw", "code"]

    def clean(self):
        errors = {}
        if self.default_duration_minutes == 0:
            errors["default_duration_minutes"] = _(
                "The default duration must be greater than zero."
            )
        if self.quorum_required == 0:
            errors["quorum_required"] = _(
                "The required quorum must be greater than zero."
            )
        if self.attendance_mode in {
            Meeting.AttendanceMode.ONLINE,
            Meeting.AttendanceMode.HYBRID,
        }:
            if not self.online_platform:
                errors["online_platform"] = _(
                    "Select the platform for an online or hybrid meeting."
                )
            if not self.online_join_url:
                errors["online_join_url"] = _(
                    "Enter the joining link for an online or hybrid meeting."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name_sw}"

    def get_absolute_url(self):
        return reverse("meetings:series_detail", kwargs={"series_id": self.pk})


class MeetingSeriesAgendaTemplate(BaseModel):
    series = models.ForeignKey(
        MeetingSeries,
        verbose_name=_("meeting series"),
        related_name="agenda_templates",
        on_delete=models.CASCADE,
    )
    item_number = models.PositiveIntegerField(_("agenda item number"))
    title_sw = models.CharField(_("agenda title in Kiswahili"), max_length=300)
    title_en = models.CharField(_("agenda title in English"), max_length=300)
    presenter_name = models.CharField(_("default presenter"), max_length=200, blank=True)
    allocated_minutes = models.PositiveIntegerField(
        _("allocated minutes"),
        null=True,
        blank=True,
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("series agenda template")
        verbose_name_plural = _("series agenda templates")
        ordering = ["series", "item_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["series", "item_number"],
                name="unique_agenda_template_per_series",
            ),
        ]

    def __str__(self):
        return f"{self.series.code} - {self.item_number}. {self.title_sw}"


class MeetingAgendaItem(BaseModel):
    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="agenda_items",
        on_delete=models.CASCADE,
    )
    item_number = models.PositiveIntegerField(_("agenda item number"))
    title_sw = models.CharField(
        _("agenda title in Kiswahili"),
        max_length=300,
    )
    title_en = models.CharField(
        _("agenda title in English"),
        max_length=300,
    )
    presenter_name = models.CharField(
        _("presenter"),
        max_length=200,
        blank=True,
    )
    allocated_minutes = models.PositiveIntegerField(
        _("allocated minutes"),
        null=True,
        blank=True,
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("meeting agenda item")
        verbose_name_plural = _("meeting agenda items")
        ordering = ["meeting", "item_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "item_number"],
                name="unique_agenda_number_per_meeting",
            ),
        ]

    def __str__(self):
        return f"{self.meeting.reference_number} - {self.item_number}. {self.title_sw}"


def meeting_document_upload_path(instance, filename):
    """Store meeting papers under opaque names, not user-supplied paths."""
    extension = Path(filename).suffix.lower()
    return f"meetings/documents/{instance.meeting_id}/{uuid.uuid4().hex}{extension}"


class MeetingDocument(BaseModel):
    class DocumentType(models.TextChoices):
        MEETING_NOTICE = "MEETING_NOTICE", _("Meeting notice")
        AGENDA_PAPER = "AGENDA_PAPER", _("Agenda paper")
        PRESENTATION = "PRESENTATION", _("Presentation")
        SUPPORTING_DOCUMENT = "SUPPORTING_DOCUMENT", _("Supporting document")
        ATTENDANCE_REGISTER = "ATTENDANCE_REGISTER", _("Attendance register")
        SIGNED_MINUTES = "SIGNED_MINUTES", _("Signed minutes")
        OTHER = "OTHER", _("Other document")

    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="documents",
        on_delete=models.CASCADE,
    )
    agenda_item = models.ForeignKey(
        MeetingAgendaItem,
        verbose_name=_("agenda item"),
        related_name="documents",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Optionally link this document to an agenda item."),
    )
    document_type = models.CharField(
        _("document type"),
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.SUPPORTING_DOCUMENT,
    )
    title_sw = models.CharField(_("document title in Kiswahili"), max_length=300)
    title_en = models.CharField(
        _("document title in English"), max_length=300, blank=True,
    )
    description_sw = models.TextField(_("description in Kiswahili"), blank=True)
    description_en = models.TextField(_("description in English"), blank=True)
    file = models.FileField(
        _("document file"),
        upload_to=meeting_document_upload_path,
        max_length=500,
    )
    original_filename = models.CharField(
        _("original filename"), max_length=255, editable=False,
    )
    version = models.PositiveIntegerField(_("version"), default=1)
    is_confidential = models.BooleanField(
        _("confidential document"),
        default=True,
        help_text=_("Confidential files are available only inside the staff workspace."),
    )

    class Meta:
        verbose_name = _("meeting document")
        verbose_name_plural = _("meeting documents")
        ordering = ["meeting", "document_type", "title_sw", "-version"]
        indexes = [
            models.Index(
                fields=["meeting", "document_type", "is_active"],
                name="meeting_doc_type_idx",
            ),
        ]

    def clean(self):
        errors = {}
        if self.agenda_item_id and self.agenda_item.meeting_id != self.meeting_id:
            errors["agenda_item"] = _("The agenda item must belong to this meeting.")
        if self.version == 0:
            errors["version"] = _("The document version must be greater than zero.")
        uploaded_file = getattr(self.file, "_file", None)
        if uploaded_file:
            extension = Path(uploaded_file.name).suffix.lower()
            if extension not in ALLOWED_MEETING_DOCUMENT_EXTENSIONS:
                errors["file"] = _(
                    "Upload a PDF, Office document, text file, or image."
                )
            elif uploaded_file.size > MAX_MEETING_DOCUMENT_SIZE:
                errors["file"] = _("The document must not exceed 20 MB.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.file and not self.original_filename:
            self.original_filename = Path(self.file.name).name[:255]
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.meeting.reference_number} - {self.title_sw} (v{self.version})"


class MeetingMinutesReview(BaseModel):
    class Action(models.TextChoices):
        SUBMITTED = "SUBMITTED", _("Submitted for approval")
        RETURNED = "RETURNED", _("Returned for correction")
        APPROVED = "APPROVED", _("Approved")
        REOPENED = "REOPENED", _("Reopened for correction")

    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="minutes_reviews",
        on_delete=models.CASCADE,
    )
    action = models.CharField(
        _("review action"),
        max_length=20,
        choices=Action.choices,
    )
    comment = models.TextField(_("review comment"), blank=True)

    class Meta:
        verbose_name = _("minutes review record")
        verbose_name_plural = _("minutes review records")
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["meeting", "action", "created_at"],
                name="meeting_minutes_review_idx",
            ),
        ]

    def clean(self):
        if self.action in {self.Action.RETURNED, self.Action.REOPENED}:
            if not self.comment.strip():
                raise ValidationError({
                    "comment": _("Enter a reason for returning the minutes."),
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.meeting.reference_number} - {self.get_action_display()}"


class MeetingResource(BaseModel):
    code = models.CharField(_("resource code"), max_length=50, unique=True)
    name_sw = models.CharField(_("resource name in Kiswahili"), max_length=200)
    name_en = models.CharField(_("resource name in English"), max_length=200)
    description_sw = models.TextField(_("description in Kiswahili"), blank=True)
    description_en = models.TextField(_("description in English"), blank=True)
    total_quantity = models.PositiveIntegerField(_("available quantity"), default=1)
    storage_location = models.CharField(
        _("storage location"), max_length=250, blank=True,
    )

    class Meta:
        verbose_name = _("meeting resource")
        verbose_name_plural = _("meeting resources")
        ordering = ["name_sw", "code"]

    def clean(self):
        if self.total_quantity == 0:
            raise ValidationError({
                "total_quantity": _("Available quantity must be greater than zero."),
            })

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name_sw}"


class MeetingResourceBooking(BaseModel):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", _("Requested")
        CONFIRMED = "CONFIRMED", _("Confirmed")
        DECLINED = "DECLINED", _("Unavailable")
        CANCELLED = "CANCELLED", _("Cancelled")

    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="resource_bookings",
        on_delete=models.CASCADE,
    )
    resource = models.ForeignKey(
        MeetingResource,
        verbose_name=_("meeting resource"),
        related_name="bookings",
        on_delete=models.PROTECT,
    )
    quantity = models.PositiveIntegerField(_("quantity required"), default=1)
    status = models.CharField(
        _("booking status"),
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
    )
    notes = models.TextField(_("booking notes"), blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("confirmed by"),
        related_name="confirmed_meeting_resources",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    confirmed_at = models.DateTimeField(
        _("confirmed at"), null=True, blank=True,
    )

    class Meta:
        verbose_name = _("meeting resource booking")
        verbose_name_plural = _("meeting resource bookings")
        ordering = ["meeting", "resource__name_sw"]
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "resource"],
                condition=Q(
                    is_active=True,
                    status__in=["REQUESTED", "CONFIRMED"],
                ),
                name="unique_active_resource_per_meeting",
            ),
        ]
        indexes = [
            models.Index(
                fields=["resource", "status", "is_active"],
                name="meeting_resource_status_idx",
            ),
        ]

    def overlapping_confirmed_quantity(self):
        if not self.meeting_id or not self.resource_id:
            return 0
        bookings = MeetingResourceBooking.objects.filter(
            resource_id=self.resource_id,
            status=self.Status.CONFIRMED,
            is_active=True,
            meeting__is_active=True,
            meeting__event__starts_at__lt=self.meeting.event.ends_at,
            meeting__event__ends_at__gt=self.meeting.event.starts_at,
        ).exclude(meeting__event__status=Event.Status.CANCELLED)
        if self.pk:
            bookings = bookings.exclude(pk=self.pk)
        return bookings.aggregate(total=Sum("quantity"))["total"] or 0

    def available_quantity(self):
        if not self.resource_id:
            return 0
        return max(
            self.resource.total_quantity - self.overlapping_confirmed_quantity(),
            0,
        )

    def clean(self):
        errors = {}
        if self.quantity == 0:
            errors["quantity"] = _("Required quantity must be greater than zero.")
        if self.resource_id and self.quantity > self.resource.total_quantity:
            errors["quantity"] = _(
                "The requested quantity exceeds the total available quantity."
            )
        if (
            self.status == self.Status.CONFIRMED
            and self.resource_id
            and self.meeting_id
            and self.quantity > self.available_quantity()
        ):
            errors["quantity"] = _(
                "This resource is not available in the requested quantity at the meeting time."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.meeting.reference_number} - {self.resource.code}"


class MeetingAttendee(BaseModel):
    class AttendeeType(models.TextChoices):
        INTERNAL = "INTERNAL", _("Internal participant")
        EXTERNAL = "EXTERNAL", _("External participant")

    class ResponseStatus(models.TextChoices):
        INVITED = "INVITED", _("Invited")
        ACCEPTED = "ACCEPTED", _("Accepted")
        DECLINED = "DECLINED", _("Declined")
        TENTATIVE = "TENTATIVE", _("Tentative")

    class AttendanceStatus(models.TextChoices):
        NOT_MARKED = "NOT_MARKED", _("Not marked")
        PRESENT = "PRESENT", _("Present")
        ABSENT = "ABSENT", _("Absent")
        EXCUSED = "EXCUSED", _("Excused")

    class PreferredLanguage(models.TextChoices):
        SWAHILI = "sw", _("Kiswahili")
        ENGLISH = "en", _("English")

    class CheckinMethod(models.TextChoices):
        QR = "QR", _("QR scan")
        MANUAL = "MANUAL", _("Manual attendance update")

    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="attendees",
        on_delete=models.CASCADE,
    )
    response_token = models.UUIDField(
        _("invitation response token"),
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    attendee_type = models.CharField(
        _("participant type"),
        max_length=20,
        choices=AttendeeType.choices,
        default=AttendeeType.EXTERNAL,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("system user"),
        related_name="meeting_attendance_records",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    full_name = models.CharField(_("full name"), max_length=200)
    organization = models.CharField(
        _("organization"),
        max_length=250,
        blank=True,
    )
    designation = models.CharField(
        _("designation"),
        max_length=150,
        blank=True,
    )
    email = models.EmailField(_("email address"), blank=True)
    phone_number = models.CharField(
        _("phone number"),
        max_length=30,
        blank=True,
    )
    preferred_language = models.CharField(
        _("preferred language"),
        max_length=5,
        choices=PreferredLanguage.choices,
        default=PreferredLanguage.SWAHILI,
    )
    response_status = models.CharField(
        _("invitation response"),
        max_length=20,
        choices=ResponseStatus.choices,
        default=ResponseStatus.INVITED,
    )
    attendance_status = models.CharField(
        _("attendance status"),
        max_length=20,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.NOT_MARKED,
    )
    invitation_sent_at = models.DateTimeField(
        _("invitation sent at"),
        null=True,
        blank=True,
    )
    responded_at = models.DateTimeField(
        _("invitation responded at"),
        null=True,
        blank=True,
    )
    checked_in_at = models.DateTimeField(
        _("checked in at"),
        null=True,
        blank=True,
    )
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("checked in by"),
        related_name="meeting_participant_checkins",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    checkin_method = models.CharField(
        _("meeting check-in method"),
        max_length=20,
        choices=CheckinMethod.choices,
        blank=True,
    )

    class Meta:
        verbose_name = _("meeting participant")
        verbose_name_plural = _("meeting participants")
        ordering = ["meeting", "full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "user"],
                condition=Q(user__isnull=False),
                name="unique_internal_attendee_per_meeting",
            ),
            models.UniqueConstraint(
                fields=["meeting", "email"],
                condition=~Q(email=""),
                name="unique_attendee_email_per_meeting",
            ),
        ]
        indexes = [
            models.Index(
                fields=["meeting", "attendance_status"],
                name="meeting_attendance_idx",
            ),
        ]

    def clean(self):
        if self.attendee_type == self.AttendeeType.INTERNAL and not self.user_id:
            raise ValidationError({
                "user": _("Select a system user for an internal participant."),
            })

    def save(self, *args, **kwargs):
        if self.user_id:
            if not self.full_name.strip():
                self.full_name = self.user.get_full_name().strip() or self.user.username
            if not self.email:
                self.email = self.user.email
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} - {self.meeting.reference_number}"


class MeetingDocumentAcknowledgement(BaseModel):
    document = models.ForeignKey(
        MeetingDocument,
        verbose_name=_("meeting document"),
        related_name="acknowledgements",
        on_delete=models.CASCADE,
    )
    attendee = models.ForeignKey(
        MeetingAttendee,
        verbose_name=_("meeting participant"),
        related_name="document_acknowledgements",
        on_delete=models.CASCADE,
    )
    acknowledged_at = models.DateTimeField(
        _("acknowledged at"),
        default=timezone.now,
    )

    class Meta:
        verbose_name = _("meeting document acknowledgement")
        verbose_name_plural = _("meeting document acknowledgements")
        ordering = ["-acknowledged_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "attendee"],
                condition=Q(is_active=True),
                name="unique_active_meeting_document_ack",
            ),
        ]
        indexes = [
            models.Index(
                fields=["document", "acknowledged_at"],
                name="meeting_document_ack_idx",
            ),
        ]

    def clean(self):
        if (
            self.document_id
            and self.attendee_id
            and self.document.meeting_id != self.attendee.meeting_id
        ):
            raise ValidationError({
                "attendee": _("The participant and document must belong to the same meeting."),
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.document} - {self.attendee.full_name}"


class MeetingFeedback(BaseModel):
    class Rating(models.IntegerChoices):
        VERY_POOR = 1, _("Very poor")
        POOR = 2, _("Poor")
        SATISFACTORY = 3, _("Satisfactory")
        GOOD = 4, _("Good")
        EXCELLENT = 5, _("Excellent")

    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="feedback_responses",
        on_delete=models.CASCADE,
    )
    attendee = models.OneToOneField(
        MeetingAttendee,
        verbose_name=_("meeting participant"),
        related_name="feedback",
        on_delete=models.CASCADE,
    )
    organization_rating = models.PositiveSmallIntegerField(
        _("organization and logistics rating"),
        choices=Rating.choices,
    )
    content_rating = models.PositiveSmallIntegerField(
        _("agenda and content rating"),
        choices=Rating.choices,
    )
    facilitation_rating = models.PositiveSmallIntegerField(
        _("chairing and facilitation rating"),
        choices=Rating.choices,
    )
    venue_platform_rating = models.PositiveSmallIntegerField(
        _("venue or online platform rating"),
        choices=Rating.choices,
    )
    overall_rating = models.PositiveSmallIntegerField(
        _("overall meeting rating"),
        choices=Rating.choices,
    )
    comments = models.TextField(_("feedback comments"), blank=True)
    recommendations = models.TextField(
        _("recommendations for future meetings"),
        blank=True,
    )
    is_anonymous = models.BooleanField(
        _("hide my identity in staff feedback reports"),
        default=False,
    )
    submitted_at = models.DateTimeField(
        _("feedback submitted at"),
        default=timezone.now,
    )

    class Meta:
        verbose_name = _("meeting feedback")
        verbose_name_plural = _("meeting feedback")
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(
                fields=["meeting", "submitted_at"],
                name="meeting_feedback_date_idx",
            ),
        ]

    def clean(self):
        errors = {}
        if self.attendee_id and self.meeting_id:
            if self.attendee.meeting_id != self.meeting_id:
                errors["attendee"] = _(
                    "The participant must belong to this meeting."
                )
            if (
                self.attendee.attendance_status
                != MeetingAttendee.AttendanceStatus.PRESENT
            ):
                errors["attendee"] = _(
                    "Only a participant marked present can submit feedback."
                )
        if errors:
            raise ValidationError(errors)

    @property
    def average_rating(self):
        values = (
            self.organization_rating,
            self.content_rating,
            self.facilitation_rating,
            self.venue_platform_rating,
            self.overall_rating,
        )
        return round(sum(values) / len(values), 1)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.meeting.reference_number} - {self.submitted_at:%Y-%m-%d}"


class MeetingDecision(BaseModel):
    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", _("Proposed")
        APPROVED = "APPROVED", _("Approved")
        DEFERRED = "DEFERRED", _("Deferred")

    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="decisions",
        on_delete=models.CASCADE,
    )
    agenda_item = models.ForeignKey(
        MeetingAgendaItem,
        verbose_name=_("agenda item"),
        related_name="decisions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    decision_number = models.PositiveIntegerField(_("decision number"))
    decision_sw = models.TextField(_("decision in Kiswahili"))
    decision_en = models.TextField(_("decision in English"), blank=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.APPROVED,
    )

    class Meta:
        verbose_name = _("meeting decision")
        verbose_name_plural = _("meeting decisions")
        ordering = ["meeting", "decision_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "decision_number"],
                name="unique_decision_number_per_meeting",
            ),
        ]

    def clean(self):
        if self.agenda_item_id and self.agenda_item.meeting_id != self.meeting_id:
            raise ValidationError({
                "agenda_item": _("The agenda item must belong to this meeting."),
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.meeting.reference_number} - {self.decision_number}"


class MeetingActionItem(BaseModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        AWAITING_REVIEW = "AWAITING_REVIEW", _("Awaiting completion review")
        RETURNED = "RETURNED", _("Returned for correction")
        COMPLETED = "COMPLETED", _("Completed")
        OVERDUE = "OVERDUE", _("Overdue")
        CANCELLED = "CANCELLED", _("Cancelled")

    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="action_items",
        on_delete=models.CASCADE,
    )
    decision = models.ForeignKey(
        MeetingDecision,
        verbose_name=_("decision"),
        related_name="action_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action_number = models.PositiveIntegerField(_("action number"))
    description_sw = models.TextField(_("action in Kiswahili"))
    description_en = models.TextField(_("action in English"), blank=True)
    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("responsible system user"),
        related_name="meeting_action_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    responsible_name = models.CharField(
        _("responsible person"),
        max_length=200,
        blank=True,
    )
    responsible_email = models.EmailField(
        _("responsible person's email"),
        blank=True,
    )
    due_date = models.DateField(_("due date"), null=True, blank=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    progress_notes = models.TextField(_("progress notes"), blank=True)
    completion_percentage = models.PositiveSmallIntegerField(
        _("completion percentage"),
        default=0,
        validators=[MaxValueValidator(100)],
    )
    completed_at = models.DateTimeField(
        _("completed at"),
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("meeting action item")
        verbose_name_plural = _("meeting action items")
        ordering = ["meeting", "action_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "action_number"],
                name="unique_action_number_per_meeting",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "due_date"],
                name="meeting_action_due_idx",
            ),
        ]

    def clean(self):
        errors = {}
        if self.decision_id and self.decision.meeting_id != self.meeting_id:
            errors["decision"] = _("The decision must belong to this meeting.")
        if not self.responsible_user_id and not self.responsible_name.strip():
            errors["responsible_name"] = _(
                "Enter a responsible person or select a system user."
            )
        full_progress_statuses = {
            self.Status.AWAITING_REVIEW,
            self.Status.RETURNED,
            self.Status.COMPLETED,
        }
        if self.status not in full_progress_statuses and self.completion_percentage == 100:
            errors["completion_percentage"] = _(
                "Submit the action for completion review when progress reaches 100 percent."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.responsible_user_id and not self.responsible_name.strip():
            self.responsible_name = (
                self.responsible_user.get_full_name().strip()
                or self.responsible_user.username
            )
        if self.responsible_user_id and not self.responsible_email:
            self.responsible_email = self.responsible_user.email
        if self.status == self.Status.COMPLETED:
            if not self.completed_at:
                self.completed_at = timezone.now()
        else:
            self.completed_at = None
        if self.status in {
            self.Status.AWAITING_REVIEW,
            self.Status.RETURNED,
            self.Status.COMPLETED,
        }:
            self.completion_percentage = 100
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.meeting.reference_number} - {self.action_number}"


def meeting_action_evidence_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"meetings/action-evidence/{instance.action_id}/{uuid.uuid4().hex}{extension}"


class MeetingActionProgressUpdate(BaseModel):
    action = models.ForeignKey(
        MeetingActionItem,
        verbose_name=_("meeting action item"),
        related_name="progress_updates",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=MeetingActionItem.Status.choices,
    )
    completion_percentage = models.PositiveSmallIntegerField(
        _("completion percentage"),
        validators=[MaxValueValidator(100)],
    )
    notes = models.TextField(_("progress update"), blank=True)
    evidence_file = models.FileField(
        _("supporting evidence"),
        upload_to=meeting_action_evidence_upload_path,
        max_length=500,
        blank=True,
    )
    original_filename = models.CharField(
        _("original filename"),
        max_length=255,
        blank=True,
        editable=False,
    )
    reported_at = models.DateTimeField(
        _("reported at"),
        default=timezone.now,
    )

    class Meta:
        verbose_name = _("meeting action progress update")
        verbose_name_plural = _("meeting action progress updates")
        ordering = ["-reported_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["action", "reported_at"],
                name="meeting_action_progress_idx",
            ),
        ]

    def clean(self):
        errors = {}
        full_progress_statuses = {
            MeetingActionItem.Status.AWAITING_REVIEW,
            MeetingActionItem.Status.RETURNED,
            MeetingActionItem.Status.COMPLETED,
        }
        if self.status in full_progress_statuses and self.completion_percentage != 100:
            errors["completion_percentage"] = _(
                "Completion review actions must show 100 percent progress."
            )
        if self.status not in full_progress_statuses and self.completion_percentage == 100:
            errors["completion_percentage"] = _(
                "Submit the action for completion review when progress reaches 100 percent."
            )
        uploaded_file = getattr(self.evidence_file, "_file", None)
        if uploaded_file:
            extension = Path(uploaded_file.name).suffix.lower()
            if extension not in ALLOWED_MEETING_DOCUMENT_EXTENSIONS:
                errors["evidence_file"] = _(
                    "Upload a PDF, Office document, text file, or image."
                )
            elif uploaded_file.size > MAX_MEETING_DOCUMENT_SIZE:
                errors["evidence_file"] = _("The document must not exceed 20 MB.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.evidence_file and not self.original_filename:
            self.original_filename = Path(self.evidence_file.name).name[:255]
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.action} - {self.completion_percentage}%"


class MeetingActionCompletionReview(BaseModel):
    class Outcome(models.TextChoices):
        VERIFIED = "VERIFIED", _("Completion verified")
        RETURNED = "RETURNED", _("Returned for correction")

    action = models.ForeignKey(
        MeetingActionItem,
        verbose_name=_("meeting action item"),
        related_name="completion_reviews",
        on_delete=models.CASCADE,
    )
    outcome = models.CharField(
        _("review outcome"),
        max_length=20,
        choices=Outcome.choices,
    )
    comment = models.TextField(_("review comment"), blank=True)
    reviewed_at = models.DateTimeField(_("reviewed at"), default=timezone.now)

    class Meta:
        verbose_name = _("meeting action completion review")
        verbose_name_plural = _("meeting action completion reviews")
        ordering = ["-reviewed_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["action", "reviewed_at"],
                name="meeting_action_review_idx",
            ),
        ]

    def clean(self):
        if self.outcome == self.Outcome.RETURNED and not self.comment.strip():
            raise ValidationError({
                "comment": _("Enter correction instructions before returning the action."),
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.action} - {self.get_outcome_display()}"


class MeetingCommunicationLog(BaseModel):
    class CommunicationType(models.TextChoices):
        INVITATION = "INVITATION", _("Meeting invitation")
        RSVP_REMINDER = "RSVP_REMINDER", _("Attendance confirmation reminder")
        MEETING_REMINDER = "MEETING_REMINDER", _("Upcoming meeting reminder")
        ACTION_REMINDER = "ACTION_REMINDER", _("Action deadline reminder")
        ACTION_ESCALATION = "ACTION_ESCALATION", _("Overdue action escalation")
        ACTION_REVIEW_SUBMITTED = (
            "ACTION_REVIEW_SUBMITTED",
            _("Action completion review submitted"),
        )
        ACTION_REVIEW_RESULT = (
            "ACTION_REVIEW_RESULT",
            _("Action completion review result"),
        )

    class DeliveryStatus(models.TextChoices):
        SENT = "SENT", _("Sent")
        FAILED = "FAILED", _("Failed")

    meeting = models.ForeignKey(
        Meeting,
        verbose_name=_("meeting"),
        related_name="communications",
        on_delete=models.CASCADE,
    )
    attendee = models.ForeignKey(
        MeetingAttendee,
        verbose_name=_("meeting participant"),
        related_name="communications",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action_item = models.ForeignKey(
        MeetingActionItem,
        verbose_name=_("meeting action item"),
        related_name="communications",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    communication_type = models.CharField(
        _("communication type"),
        max_length=30,
        choices=CommunicationType.choices,
    )
    delivery_status = models.CharField(
        _("delivery status"),
        max_length=20,
        choices=DeliveryStatus.choices,
    )
    recipient_name = models.CharField(_("recipient name"), max_length=200)
    recipient_email = models.EmailField(_("recipient email"))
    subject = models.CharField(_("subject"), max_length=300)
    message = models.TextField(_("message"))
    sent_at = models.DateTimeField(_("sent at"), default=timezone.now)
    error_message = models.TextField(_("error message"), blank=True)

    class Meta:
        verbose_name = _("meeting communication")
        verbose_name_plural = _("meeting communications")
        ordering = ["-sent_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["meeting", "communication_type", "delivery_status"],
                name="meeting_comm_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.meeting.reference_number} - {self.recipient_email}"

