from types import SimpleNamespace
from io import BytesIO
from io import StringIO
from tempfile import NamedTemporaryFile
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from PIL import Image

from events.models import Event, EventCategory
from .models import EventForm, FormQuestion

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


class WEUUTzEvaluationSetupTests(TestCase):
    def setUp(self):
        category = EventCategory.objects.create(
            name_sw="Maonesho",
            name_en="Exhibition",
            code="EXHIBITION",
        )
        starts_at = timezone.now() + timedelta(days=1)
        self.event = Event.objects.create(
            category=category,
            code="WEUUTz-2026",
            title_sw="Wiki ya Elimu na Ubunifu",
            title_en="Education and Innovation Week",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(days=3),
        )
        self.form = EventForm.objects.create(
            event=self.event,
            name_sw="Tathmini",
            name_en="Exhibition Evaluation",
            form_type=EventForm.FormType.EVALUATION,
            is_published=True,
        )
        section = self.form.sections.create(
            title_sw="Maoni ya Washiriki",
            title_en="Participants Views",
        )
        self.original_question = section.questions.create(
            label_sw="Ni bidhaa gani iliyokuvutia?",
            label_en="Which product, technology, or exhibitor interested you most?",
            question_type=FormQuestion.QuestionType.SHORT_TEXT,
            is_required=True,
        )

    def test_command_requires_confirmation(self):
        with self.assertRaises(CommandError):
            call_command("setup_weuutz_evaluation")

    def test_command_improves_only_weuutz_form_and_is_idempotent(self):
        output = StringIO()
        call_command("setup_weuutz_evaluation", "--confirm", stdout=output)
        call_command("setup_weuutz_evaluation", "--confirm", stdout=output)

        self.event.refresh_from_db()
        self.form.refresh_from_db()
        self.original_question.refresh_from_db()
        questions = FormQuestion.objects.filter(section__event_form=self.form)

        self.assertTrue(self.event.evaluation_enabled)
        self.assertTrue(self.form.is_published)
        self.assertEqual(self.form.name_en, "Commemoration Evaluation Questionnaire")
        self.assertEqual(questions.filter(is_active=True).count(), 9)
        self.assertFalse(self.original_question.is_active)
        self.assertEqual(
            set(questions.filter(is_active=True).values_list("label_sw", flat=True)),
            {
                "Jina la taasisi",
                "Anuani",
                "Aina ya huduma unayotoa kwa jamii: Tafadhali, chagua kati ya zifuatazo.",
                "Tafadhali, taja huduma nyinginezo",
                "Idadi ya mabanda ya taasisi yako katika Maadhimisho ya Wiki ya Kitaifa ya Elimu, Ujuzi na Ubunifu, mwaka 2026",
                "Tafadhali, taja idadi ya wananchi waliotembelea banda lako katika maadhimisho ya mwaka huu, 2026.",
                "Tafadhali, taja mafanikio uliyoyapata katika maadhimisho ya mwaka huu, 2026.",
                "Tafadhali, taja changamoto ulizozipata katika Maadhimisho ya mwaka huu, 2026 hapa Jijini Tanga.",
                "Tafadhali, toa maoni ya kuboresha Maadhimisho haya kwa mwaka ujao, 2027.",
            },
        )
        service_question = questions.get(
            label_en="What type of service does your institution provide to the community? Select all that apply."
        )
        self.assertEqual(service_question.options.filter(is_active=True).count(), 10)
        self.assertEqual(
            list(service_question.options.filter(is_active=True).values_list("value", flat=True)),
            [
                "RESEARCH", "TRAINING", "AGENCY", "EDUCATION", "CONSULTANCY",
                "RESCUE", "COORDINATION", "SECURITY", "MARKETING", "OTHER",
            ],
        )
