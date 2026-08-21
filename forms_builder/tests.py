from types import SimpleNamespace
from io import BytesIO
from tempfile import NamedTemporaryFile

from django.test import SimpleTestCase
from PIL import Image

from .services import (
    certificate_is_for_institution,
    certificate_recipient_name,
    generate_qr_png,
)
from .views import registration_identity_conflicts


class RegistrationIdentityConflictTests(SimpleTestCase):
    def setUp(self):
        self.existing = SimpleNamespace(
            submitter_email="Participant@Example.com",
            submitter_phone="+255 712 345 678",
        )

    def test_matching_email_blocks_registration_even_with_different_phone(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                " participant@example.com ",
                "0755000000",
            )
        )
        self.assertIs(duplicate, self.existing)
        self.assertTrue(email_conflict)
        self.assertFalse(phone_conflict)

    def test_matching_phone_blocks_registration_even_with_different_email(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                "different@example.com",
                "0712-345-678",
            )
        )
        self.assertIs(duplicate, self.existing)
        self.assertFalse(email_conflict)
        self.assertTrue(phone_conflict)

    def test_different_email_and_phone_are_allowed(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                "different@example.com",
                "0755000000",
            )
        )
        self.assertIsNone(duplicate)
        self.assertFalse(email_conflict)
        self.assertFalse(phone_conflict)


class InstitutionCertificateTests(SimpleTestCase):
    def submission(self, event_code="WEUUTZ-2026", organization="Innovation Institute"):
        event = SimpleNamespace(code=event_code)
        event_form = SimpleNamespace(event=event)
        return SimpleNamespace(
            event_form=event_form,
            badge_organization=organization,
            badge_display_name="Asha Representative",
        )

    def test_weuutz_certificate_is_awarded_to_institution(self):
        submission = self.submission()

        self.assertTrue(certificate_is_for_institution(submission))
        self.assertEqual(
            certificate_recipient_name(submission),
            "Innovation Institute",
        )
        self.assertEqual(submission.badge_display_name, "Asha Representative")

    def test_other_event_certificate_remains_awarded_to_participant(self):
        submission = self.submission(event_code="NESIF-2026")

        self.assertFalse(certificate_is_for_institution(submission))
        self.assertEqual(
            certificate_recipient_name(submission),
            "Asha Representative",
        )

    def test_qr_code_places_supplied_logo_at_center(self):
        with NamedTemporaryFile(suffix=".png") as logo_file:
            Image.new("RGB", (80, 80), "#d71920").save(logo_file, format="PNG")
            logo_file.flush()
            qr_png = generate_qr_png(
                "https://example.test/certificate/verify/",
                logo_path=logo_file.name,
            )

        qr_image = Image.open(BytesIO(qr_png)).convert("RGB")
        center = qr_image.getpixel((qr_image.width // 2, qr_image.height // 2))
        self.assertGreater(center[0], 180)
        self.assertLess(center[1], 80)
        self.assertLess(center[2], 80)
