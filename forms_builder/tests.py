from types import SimpleNamespace
from io import BytesIO
from io import StringIO
from tempfile import NamedTemporaryFile
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib import admin
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from events.models import Event, EventCategory
from .models import EventForm, FormQuestion, FormSubmission
from .admin import EventFormAdmin

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
        self.assertTrue(self.form.requires_participant_registration)
        self.assertEqual(self.form.name_en, "Commemoration Evaluation Questionnaire")
        self.assertEqual(questions.filter(is_active=True).count(), 38)
        self.assertFalse(self.original_question.is_active)
        self.assertEqual(
            self.form.sections.filter(is_active=True).count(),
            5,
        )
        self.assertFalse(
            self.form.sections.filter(
                is_active=True,
                title_en="SECTION A: PARTICIPANT/INSTITUTION INFORMATION",
            ).exists()
        )
        self.assertFalse(
            questions.filter(
                is_active=True,
                label_en="Institution/organization name",
            ).exists()
        )
        other_fields = questions.filter(is_active=True, condition_value="OTHER")
        self.assertEqual(other_fields.count(), 2)
        self.assertTrue(all(question.is_required for question in other_fields))
        self.assertTrue(all(question.condition_question_id for question in other_fields))

    def test_evaluation_is_available_only_through_linked_participant_portal(self):
        call_command("setup_weuutz_evaluation", "--confirm")
        self.event.refresh_from_db()
        evaluation_form = self.event.forms.get(
            form_type=EventForm.FormType.EVALUATION,
        )
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Usajili",
            name_en="Registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_published=True,
        )
        registration = FormSubmission.objects.create(
            event_form=registration_form,
            submitter_email="representative@example.com",
            submitter_phone="0712345678",
            is_complete=True,
        )
        evaluation_url = reverse(
            "forms_builder:public_event_form",
            kwargs={
                "event_slug": self.event.slug,
                "form_slug": evaluation_form.slug,
            },
        )

        direct_response = self.client.get(evaluation_url)
        self.assertRedirects(
            direct_response,
            reverse("forms_builder:registration_status"),
        )
        response = self.client.get(
            evaluation_url,
            {"participant": registration.participant_token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["participant_registration"], registration)

        portal_url = reverse(
            "forms_builder:participant_portal",
            kwargs={"participant_token": registration.participant_token},
        )
        portal_response = self.client.get(portal_url)
        self.assertContains(
            portal_response,
            f"?participant={registration.participant_token}",
        )
        self.assertContains(
            response,
            f"?participant={registration.participant_token}",
            count=2,
        )

        public_event_response = self.client.get(
            reverse(
                "events:event_detail",
                kwargs={"event_slug": self.event.slug},
            )
        )
        self.assertNotContains(public_event_response, evaluation_url)

        admin_tools = str(
            EventFormAdmin(EventForm, admin.site).registration_tools(
                evaluation_form
            )
        )
        self.assertIn(f"{evaluation_url}?preview=1", admin_tools)
        self.assertIn("Preview form", admin_tools)
        self.assertNotIn("View QR", admin_tools)

    def test_pending_registration_can_access_badge_but_not_certificate(self):
        self.event.badge_enabled = True
        self.event.certificate_enabled = True
        self.event.save(update_fields=[
            "badge_enabled", "certificate_enabled", "updated_at",
        ])
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Usajili",
            name_en="Registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_published=True,
        )
        registration = FormSubmission.objects.create(
            event_form=registration_form,
            review_status=FormSubmission.ReviewStatus.PENDING,
            is_complete=True,
        )

        badge_url = reverse(
            "forms_builder:participant_badge",
            kwargs={"participant_token": registration.participant_token},
        )
        self.assertEqual(self.client.get(badge_url).status_code, 200)

        portal_url = reverse(
            "forms_builder:participant_portal",
            kwargs={"participant_token": registration.participant_token},
        )
        portal_response = self.client.get(portal_url)
        certificate_url = reverse(
            "forms_builder:participant_certificate",
            kwargs={"participant_token": registration.participant_token},
        )
        self.assertNotContains(portal_response, certificate_url)
