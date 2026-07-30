from PIL import Image, ImageOps
import qrcode
from io import BytesIO
from django.core.files import File
from django.db import models


class SummitEvent(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30, unique=True)
    venue = models.CharField(max_length=200, default='Not specified')
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)

    # Old field kept for compatibility, but no longer used as the main event logic
    is_active = models.BooleanField(default=True)

    # New multi-event status fields
    is_open = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)

    registration_qr_code = models.ImageField(
        upload_to='summit/event_qrcodes/',
        blank=True,
        null=True
    )

    # Badge settings
    badge_footer_text = models.CharField(
        max_length=200,
        default='Ministry of Education, Science and Technology'
    )

    badge_use_watermark = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()

        super().save(*args, **kwargs)

        if not self.registration_qr_code:
            registration_url = f"http://192.168.10.221:8000/summit/register/{self.code}/"

            img = qrcode.make(registration_url)

            buffer = BytesIO()
            img.save(buffer, format='PNG')

            file_name = f"{self.code}_registration_qr.png"
            self.registration_qr_code.save(file_name, File(buffer), save=False)

            super().save(update_fields=['registration_qr_code'])

    def __str__(self):
        return f"{self.code} - {self.name}"


class SummitParticipant(models.Model):
    event = models.ForeignKey(
        SummitEvent,
        on_delete=models.CASCADE,
        related_name='participants',
        blank=True,
        null=True
    )

    registration_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True
    )

    title = models.CharField(
        max_length=20,
        choices=[
            ('Mr.', 'Mr.'),
            ('Ms.', 'Ms.'),
            ('Dr.', 'Dr.'),
            ('Prof.', 'Prof.'),
            ('Mx.', 'Mx.'),
            ('Hon.', 'Hon.'),
            ('Other', 'Other'),
        ],
        default='Mr.'
    )

    other_title = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    full_name = models.CharField(max_length=150, default='Not specified')
    institution = models.CharField(max_length=200, default='Not specified')
    designation = models.CharField(max_length=150, default='Not specified')
    phone = models.CharField(max_length=30, default='Not specified')
    email = models.EmailField(default='notprovided@example.com')
    region = models.CharField(max_length=100, default='Not specified')

    attendance_type = models.CharField(
        max_length=50,
        choices=[
            ('Physical', 'Physical'),
            ('Online', 'Online'),
        ],
        default='Physical'
    )

    photo = models.ImageField(
        upload_to='summit/photos/',
        blank=True,
        null=True
    )

    qr_code = models.ImageField(
        upload_to='summit/qrcodes/',
        blank=True,
        null=True
    )

    checked_in = models.BooleanField(default=False)

    checked_in_at = models.DateTimeField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'full_name', 'email', 'phone'],
                name='unique_participant_per_event_name_email_phone'
            )
        ]

    def save(self, *args, **kwargs):
        if not self.event:
            self.event = SummitEvent.objects.filter(
                is_open=True,
                is_archived=False
            ).order_by('-start_date').first()

        if not self.registration_number:
            event_code = self.event.code if self.event else 'SUMMIT'

            if self.event:
                next_id = self.event.participants.count() + 1
            else:
                next_id = SummitParticipant.objects.count() + 1

            self.registration_number = f"{event_code}-{next_id:04d}"

        selected_title = self.other_title if self.title == 'Other' else self.title

        if selected_title:
            selected_title = selected_title.strip()
            clean_name = self.full_name.strip()

            if not clean_name.startswith(selected_title):
                self.full_name = f"{selected_title} {clean_name}"

        super().save(*args, **kwargs)

        if self.photo:
            photo_path = self.photo.path

            img = Image.open(photo_path)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail((300, 300))

            img.save(photo_path, format="JPEG", quality=40, optimize=True)

        if not self.qr_code:
            qr_data = self.registration_number
            img = qrcode.make(qr_data)

            buffer = BytesIO()
            img.save(buffer, format='PNG')

            file_name = f"{self.registration_number}.png"
            self.qr_code.save(file_name, File(buffer), save=False)

            super().save(update_fields=['qr_code'])

    def __str__(self):
        return f"{self.registration_number} - {self.full_name}"