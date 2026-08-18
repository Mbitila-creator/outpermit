from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from forms_builder.models import FormSubmission


class ParticipantCheckIn(BaseModel):
    class Method(models.TextChoices):
        QR = "QR", _("QR code")
        MANUAL = "MANUAL", _("Manual lookup")

    submission = models.OneToOneField(
        FormSubmission,
        verbose_name=_("participant submission"),
        related_name="check_in",
        on_delete=models.CASCADE,
    )

    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("checked in by"),
        related_name="participant_check_ins",
        on_delete=models.PROTECT,
    )

    checked_in_at = models.DateTimeField(
        _("checked in at"),
        auto_now_add=True,
        db_index=True,
    )

    method = models.CharField(
        _("check-in method"),
        max_length=20,
        choices=Method.choices,
        default=Method.QR,
    )

    notes = models.TextField(
        _("check-in notes"),
        blank=True,
    )

    class Meta:
        verbose_name = _("participant check-in")
        verbose_name_plural = _("participant check-ins")
        ordering = ["-checked_in_at"]

    def __str__(self):
        return (
            f"{self.submission.reference_number} — "
            f"{self.checked_in_at:%Y-%m-%d %H:%M}"
        )

