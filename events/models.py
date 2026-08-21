import hashlib
import unicodedata
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel, Council


def special_event_researcher_identity(full_name, institution):
    """Return a stable event-local identity for one researcher."""
    normalized_parts = []
    for value in (full_name, institution):
        normalized = unicodedata.normalize("NFKC", str(value or ""))
        normalized_parts.append(" ".join(normalized.split()).casefold())
    return hashlib.sha256("\x00".join(normalized_parts).encode("utf-8")).hexdigest()


class EventCategory(BaseModel):
    SPECIAL_EVENT_CODE = "SPECIAL_EVENT"
    CONFERENCE_CODE = "CONFERENCE"
    name_sw = models.CharField(
        _("name in Kiswahili"),
        max_length=150,
        unique=True,
    )

    name_en = models.CharField(
        _("name in English"),
        max_length=150,
        unique=True,
    )

    code = models.CharField(
        _("category code"),
        max_length=30,
        unique=True,
        help_text=_(
            "Use a short unique code, for example EXHIBITION or MEETING."
        ),
    )

    slug = models.SlugField(
        _("slug"),
        max_length=180,
        unique=True,
        blank=True,
    )

    description_sw = models.TextField(
        _("description in Kiswahili"),
        blank=True,
    )

    description_en = models.TextField(
        _("description in English"),
        blank=True,
    )

    display_order = models.PositiveIntegerField(
        _("display order"),
        default=0,
    )

    class Meta:
        verbose_name = _("event category")
        verbose_name_plural = _("event categories")
        ordering = [
            "display_order",
            "name_sw",
        ]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()

        if not self.slug:
            self.slug = slugify(self.name_en or self.name_sw)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name_sw} / {self.name_en}"

    @property
    def is_special_event(self):
        """Recognize the existing Special Event category without changing it."""
        normalized_code = self.code.strip().upper().replace("-", "_").replace(" ", "_")
        return (
            normalized_code == self.SPECIAL_EVENT_CODE
            or self.slug == "special-event"
            or self.name_en.strip().casefold() == "special event"
        )

    @property
    def is_conference(self):
        """Recognize Conference categories created before or after this module."""
        normalized_code = self.code.strip().upper().replace("-", "_").replace(" ", "_")
        return (
            normalized_code == self.CONFERENCE_CODE
            or self.slug in {"conference", "kongamano"}
            or self.name_en.strip().casefold() == "conference"
        )


class Venue(BaseModel):
    class VenueType(models.TextChoices):
        INDOOR = "INDOOR", _("Indoor")
        OUTDOOR = "OUTDOOR", _("Outdoor")
        HYBRID = "HYBRID", _("Indoor and Outdoor")
        ONLINE = "ONLINE", _("Online")

    name = models.CharField(
        _("venue name"),
        max_length=200,
    )

    council = models.ForeignKey(
        Council,
        verbose_name=_("council"),
        related_name="venues",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    address = models.TextField(
        _("address"),
        blank=True,
    )

    venue_type = models.CharField(
        _("venue type"),
        max_length=20,
        choices=VenueType.choices,
        default=VenueType.INDOOR,
    )

    capacity = models.PositiveIntegerField(
        _("capacity"),
        null=True,
        blank=True,
    )

    contact_person = models.CharField(
        _("contact person"),
        max_length=150,
        blank=True,
    )

    contact_phone = models.CharField(
        _("contact phone"),
        max_length=30,
        blank=True,
    )

    contact_email = models.EmailField(
        _("contact email"),
        blank=True,
    )

    latitude = models.DecimalField(
        _("latitude"),
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )

    longitude = models.DecimalField(
        _("longitude"),
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )

    online_link = models.URLField(
        _("online meeting link"),
        blank=True,
    )

    notes = models.TextField(
        _("notes"),
        blank=True,
    )

    class Meta:
        verbose_name = _("venue")
        verbose_name_plural = _("venues")
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["name", "council"],
                name="unique_venue_name_per_council",
            ),
        ]

    def __str__(self):
        if self.council:
            return f"{self.name} - {self.council.name_sw}"

        return self.name


class Event(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PUBLISHED = "PUBLISHED", _("Published")
        REGISTRATION_OPEN = (
            "REGISTRATION_OPEN",
            _("Registration Open"),
        )
        REGISTRATION_CLOSED = (
            "REGISTRATION_CLOSED",
            _("Registration Closed"),
        )
        ONGOING = "ONGOING", _("Ongoing")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")

    category = models.ForeignKey(
        EventCategory,
        verbose_name=_("event category"),
        related_name="events",
        on_delete=models.PROTECT,
    )

    owning_department = models.ForeignKey(
        "permits.Department",
        verbose_name=_("owning department"),
        related_name="events",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=_(
            "The department that owns this event and its operational data."
        ),
    )

    venue = models.ForeignKey(
        Venue,
        verbose_name=_("venue"),
        related_name="events",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    code = models.CharField(
        _("event code"),
        max_length=50,
        unique=True,
        help_text=_(
            "Use a short unique code, for example WEUUTz-2026."
        ),
    )

    title_sw = models.CharField(
        _("event title in Kiswahili"),
        max_length=250,
    )

    title_en = models.CharField(
        _("event title in English"),
        max_length=250,
    )

    slug = models.SlugField(
        _("slug"),
        max_length=280,
        unique=True,
        blank=True,
    )

    description_sw = models.TextField(
        _("description in Kiswahili"),
        blank=True,
    )

    description_en = models.TextField(
        _("description in English"),
        blank=True,
    )

    organizer_name_sw = models.CharField(
        _("organizer name in Kiswahili"),
        max_length=250,
        blank=True,
    )

    organizer_name_en = models.CharField(
        _("organizer name in English"),
        max_length=250,
        blank=True,
    )

    contact_person = models.CharField(
        _("contact person"),
        max_length=150,
        blank=True,
    )

    contact_email = models.EmailField(
        _("contact email"),
        blank=True,
    )

    contact_phone = models.CharField(
        _("contact phone"),
        max_length=50,
        blank=True,
    )

    registration_opens_at = models.DateTimeField(
        _("registration opens"),
        null=True,
        blank=True,
    )

    registration_closes_at = models.DateTimeField(
        _("registration closes"),
        null=True,
        blank=True,
    )

    starts_at = models.DateTimeField(
        _("event starts"),
    )

    ends_at = models.DateTimeField(
        _("event ends"),
    )

    maximum_participants = models.PositiveIntegerField(
        _("maximum participants"),
        null=True,
        blank=True,
        help_text=_(
            "Leave empty when the event has no participant limit."
        ),
    )

    logo = models.ImageField(
        _("event logo"),
        upload_to="events/logos/",
        null=True,
        blank=True,
    )

    banner = models.ImageField(
        _("event banner"),
        upload_to="events/banners/",
        null=True,
        blank=True,
    )

    status = models.CharField(
        _("status"),
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    is_public = models.BooleanField(
        _("public event"),
        default=True,
        help_text=_(
            "Public events may be viewed without signing in."
        ),
    )

    registration_enabled = models.BooleanField(
        _("registration enabled"),
        default=True,
    )

    evaluation_enabled = models.BooleanField(
        _("evaluation enabled"),
        default=False,
    )

    qr_checkin_enabled = models.BooleanField(
        _("QR check-in enabled"),
        default=True,
    )

    badge_enabled = models.BooleanField(
        _("badge printing enabled"),
        default=True,
    )

    certificate_enabled = models.BooleanField(
        _("certificate enabled"),
        default=False,
    )

    booth_enabled = models.BooleanField(
        _("booth management enabled"),
        default=False,
    )

    payment_enabled = models.BooleanField(
        _("payment collection enabled"), default=False,
    )
    participation_fee = models.DecimalField(
        _("participation fee"), max_digits=14, decimal_places=2,
        null=True, blank=True,
    )
    payment_currency = models.CharField(
        _("payment currency"), max_length=3, default="TZS",
    )
    payment_instructions_sw = models.TextField(
        _("payment instructions in Kiswahili"), blank=True,
    )
    payment_instructions_en = models.TextField(
        _("payment instructions in English"), blank=True,
    )

    class Meta:
        verbose_name = _("event")
        verbose_name_plural = _("events")
        ordering = [
            "-starts_at",
            "title_sw",
        ]

        indexes = [
            models.Index(
                fields=["owning_department", "status", "starts_at"],
                name="event_dept_status_start_idx",
            ),
            models.Index(
                fields=["status", "starts_at"],
                name="event_status_start_idx",
            ),
            models.Index(
                fields=["category", "status"],
                name="event_category_status_idx",
            ),
        ]

    def clean(self):
        errors = {}

        if self.starts_at and self.ends_at:
            if self.ends_at <= self.starts_at:
                errors["ends_at"] = _(
                    "The event ending date must be after the starting date."
                )

        if (
            self.registration_opens_at
            and self.registration_closes_at
            and self.registration_closes_at
            <= self.registration_opens_at
        ):
            errors["registration_closes_at"] = _(
                "Registration must close after it opens."
            )

        if (
            self.registration_closes_at
            and self.ends_at
            and self.registration_closes_at > self.ends_at
        ):
            errors["registration_closes_at"] = _(
                "Registration cannot close after the event has ended."
            )

        if self.payment_enabled:
            if self.participation_fee is None or self.participation_fee <= 0:
                errors["participation_fee"] = _(
                    "Enter a participation fee greater than zero."
                )
            if not self.payment_instructions_sw:
                errors["payment_instructions_sw"] = _(
                    "Enter payment instructions in Kiswahili."
                )
            if not self.payment_instructions_en:
                errors["payment_instructions_en"] = _(
                    "Enter payment instructions in English."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        normalized_code = self.code.strip().upper()
        self.code = (
            "WEUUTz-2026"
            if normalized_code == "WEUUTZ-2026"
            else normalized_code
        )
        self.payment_currency = self.payment_currency.strip().upper()

        if not self.slug:
            base_slug = slugify(self.title_en or self.title_sw)
            self.slug = f"{base_slug}-{self.code.lower()}"

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.title_sw}"


class SpecialEventParticipant(BaseModel):
    """One researcher with one secure QR record in a Special Event."""

    event = models.ForeignKey(
        Event,
        verbose_name="special event",
        related_name="special_event_participants",
        on_delete=models.CASCADE,
    )
    identity_key = models.CharField(
        "researcher identity key",
        max_length=64,
        editable=False,
    )
    full_name = models.CharField(
        "researcher name",
        max_length=300,
    )
    institution = models.TextField(
        "institution",
        blank=True,
    )
    verification_token = models.UUIDField(
        "verification token",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    class Meta:
        verbose_name = "special event researcher"
        verbose_name_plural = "special event researchers"
        ordering = ["event", "full_name", "institution"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "identity_key"],
                name="unique_special_event_researcher",
            ),
        ]
        indexes = [
            models.Index(
                fields=["event", "is_active"],
                name="special_event_researcher_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.event_id and not self.event.category.is_special_event:
            raise ValidationError({
                "event": "Select an event in the Special Event category.",
            })

    def save(self, *args, **kwargs):
        self.full_name = self.full_name.strip()
        self.institution = self.institution.strip()
        self.identity_key = special_event_researcher_identity(
            self.full_name,
            self.institution,
        )
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} — {self.event.code}"


class SpecialEventPublication(BaseModel):
    """One publication and award attached to a Special Event researcher."""

    participant = models.ForeignKey(
        SpecialEventParticipant,
        verbose_name="researcher",
        related_name="publications",
        on_delete=models.CASCADE,
    )
    source_sheet = models.CharField("source sheet", max_length=100)
    source_number = models.CharField("source row number", max_length=50)
    source_row_index = models.PositiveIntegerField(
        "source row position",
        default=0,
        editable=False,
    )
    research_title = models.TextField("research title")
    award_category = models.TextField("award category")
    award_year = models.CharField(
        "award year",
        max_length=50,
        blank=True,
        help_text="May be left blank for legacy records and completed later.",
    )

    class Meta:
        verbose_name = "special event publication"
        verbose_name_plural = "special event publications"
        ordering = ["source_sheet", "source_row_index", "research_title"]
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "source_sheet", "source_number"],
                name="unique_special_event_publication_source",
            ),
        ]
        indexes = [
            models.Index(
                fields=["participant", "is_active"],
                name="special_event_publication_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        self.source_sheet = self.source_sheet.strip()
        self.source_number = self.source_number.strip()
        self.research_title = self.research_title.strip()
        self.award_category = self.award_category.strip()
        self.award_year = self.award_year.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.participant.full_name} — {self.research_title}"
