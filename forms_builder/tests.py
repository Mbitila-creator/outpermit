from types import SimpleNamespace
from io import BytesIO
from io import StringIO
from tempfile import NamedTemporaryFile
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from events.models import Event, EventCategory
from .models import (
    EventForm,
    FormAnswer,
    FormQuestion,
    FormSubmission,
    QuestionOption,
)
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

    def test_registration_routing_is_removed_without_deleting_history(self):
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Fomu ya Usajili wa Waoneshaji",
            name_en="Exhibition Participant Registration Form",
            slug="exhibition-participant-registration-form",
            form_type=EventForm.FormType.EXHIBITOR,
            is_published=True,
        )
        institution = registration_form.sections.create(
            title_sw="Taarifa za Taasisi",
            title_en="Institution Information",
            display_order=1,
        )
        representative = registration_form.sections.create(
            title_sw="Taarifa za Mwakilishi",
            title_en="Representative Information",
            display_order=2,
        )
        participation = registration_form.sections.create(
            title_sw="Aina ya Ushiriki",
            title_en="Participation Type",
            display_order=3,
        )
        participation_question = participation.questions.create(
            label_sw="Unakusudia kushiriki sehemu ipi?",
            label_en="In which part(s) of the event do you intend to participate?",
            question_type=FormQuestion.QuestionType.MULTIPLE_CHOICE,
            is_required=True,
        )
        exhibition_option = QuestionOption.objects.create(
            question=participation_question,
            value="EXHIBITION",
            label_sw="Maonesho",
            label_en="Exhibition",
        )
        booth_section = registration_form.sections.create(
            title_sw="Mabanda",
            title_en="Booths",
            display_order=4,
            condition_question=participation_question,
            condition_value="EXHIBITION",
        )
        conference_section = registration_form.sections.create(
            title_sw="Maeneo ya Kongamano",
            title_en="Conference Areas",
            display_order=5,
            condition_question=participation_question,
            condition_value="CONFERENCE",
        )
        conference_section.questions.create(
            label_sw="Chagua eneo la kongamano",
            label_en="Choose a conference area",
            is_required=True,
        )
        other_section = registration_form.sections.create(
            title_sw="Ushiriki Mwingine",
            title_en="Other Participation",
            display_order=6,
            condition_question=participation_question,
            condition_value="OTHER",
        )
        other_section.questions.create(
            label_sw="Taja ushiriki mwingine",
            label_en="Specify other participation",
            is_required=True,
        )
        submission = FormSubmission.objects.create(
            event_form=registration_form,
            is_complete=True,
        )
        historical_answer = FormAnswer.objects.create(
            submission=submission,
            question=participation_question,
        )
        historical_answer.selected_options.add(exhibition_option)

        call_command("setup_weuutz_registration", "--confirm")
        call_command("setup_weuutz_registration", "--confirm")

        self.assertTrue(FormAnswer.objects.filter(pk=historical_answer.pk).exists())
        participation.refresh_from_db()
        conference_section.refresh_from_db()
        other_section.refresh_from_db()
        booth_section.refresh_from_db()
        participation_question.refresh_from_db()
        self.assertFalse(participation.is_active)
        self.assertFalse(participation_question.is_active)
        self.assertFalse(conference_section.is_active)
        self.assertFalse(other_section.is_active)
        self.assertIsNone(booth_section.condition_question_id)
        self.assertEqual(booth_section.condition_value, "")
        self.assertEqual(
            list(
                registration_form.sections.filter(is_active=True)
                .order_by("display_order")
                .values_list("title_en", "display_order")
            ),
            [
                (institution.title_en, 1),
                (representative.title_en, 2),
                (booth_section.title_en, 3),
            ],
        )

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
        self.assertFalse(self.form.show_event_summary)
        self.assertEqual(self.form.name_en, "Commemoration Evaluation Questionnaire")
        self.assertEqual(self.form.name_sw, "Dodoso la Tathmini ya Maadhimisho")
        self.assertEqual(questions.filter(is_active=True).count(), 38)
        self.assertFalse(self.original_question.is_active)
        self.assertEqual(
            self.form.sections.filter(is_active=True).count(),
            5,
        )
        self.assertEqual(
            list(
                self.form.sections.filter(is_active=True)
                .order_by("display_order")
                .values_list("title_en", flat=True)
            ),
            [
                "SECTION A: PARTICIPATION AND VISITOR RESPONSE",
                "SECTION B: EXHIBITION ORGANIZATION AND OPERATIONS",
                "SECTION C: PARTICIPATION BENEFITS AND OUTCOMES",
                "SECTION D: OVERALL EVALUATION",
                "SECTION E: ACHIEVEMENTS, CHALLENGES AND RECOMMENDATIONS",
            ],
        )
        section_b = self.form.sections.get(display_order=2, is_active=True)
        section_c = self.form.sections.get(display_order=3, is_active=True)
        self.assertEqual(
            section_b.description_en,
            "Please rate the following areas using the 1–5 scale, where "
            "1 = Very poor, 2 = Poor, 3 = Fair, 4 = Good, 5 = Very good.",
        )
        self.assertEqual(
            section_c.description_en,
            "To what extent did your institution's participation achieve the "
            "following outcomes? Where 1 = Not achieved, 2 = Slightly, "
            "3 = Moderate, 4 = Achieved, 5 = Highly achieved.",
        )
        expected_question_counts = {"A": 5, "B": 12, "C": 11, "D": 3, "E": 7}
        for section_letter, question_count in expected_question_counts.items():
            section = self.form.sections.get(
                display_order=ord(section_letter) - ord("A") + 1,
                is_active=True,
            )
            labels = list(
                section.questions.filter(is_active=True)
                .order_by("display_order", "pk")
                .values_list("label_en", flat=True)
            )
            self.assertEqual(len(labels), question_count)
            self.assertEqual(
                [label.split(".", 1)[0] for label in labels],
                [f"{section_letter}{number}" for number in range(1, question_count + 1)],
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
        self.assertContains(response, 'class="likert-table"', count=2)
        self.assertContains(response, 'class="likert-choice"', count=100)
        self.assertContains(response, 'class="questions-container likert-follow-up"')
        self.assertContains(
            response,
            "Were any important new collaborations, opportunities or contacts obtained?",
        )

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

        language_response = self.client.post(
            reverse("set_language"),
            {
                "language": "sw",
                "next": (
                    f"{evaluation_url}?participant="
                    f"{registration.participant_token}"
                ),
            },
            follow=True,
        )
        self.assertContains(
            language_response,
            "Tafadhali jaza dodoso hili kwa niaba ya taasisi yako.",
        )
        self.assertContains(
            language_response,
            "SEHEMU A: USHIRIKI NA MWITIKIO WA WATEMBELEAJI",
        )
        self.assertContains(language_response, "Inayofuata")
        self.assertContains(language_response, "Wasilisha tathmini")
        self.client.post(
            reverse("set_language"),
            {"language": "en", "next": evaluation_url},
        )

        public_event_response = self.client.get(
            reverse(
                "events:event_detail",
                kwargs={"event_slug": self.event.slug},
            )
        )
        self.assertContains(
            public_event_response,
            evaluation_form.name_en,
        )
        self.assertContains(
            public_event_response,
            reverse("forms_builder:registration_status"),
        )
        self.assertContains(
            public_event_response,
            "Open participant portal",
        )
        self.assertNotContains(public_event_response, f'href="{evaluation_url}"')

        administrator = get_user_model().objects.create_superuser(
            username="evaluation-admin",
            email="evaluation-admin@example.com",
            password="safe-test-password",
        )
        self.client.force_login(administrator)
        administrator_response = self.client.get(
            reverse(
                "events:event_detail",
                kwargs={"event_slug": self.event.slug},
            )
        )
        self.assertContains(administrator_response, "Preview questions")
        self.assertContains(
            administrator_response,
            f'{evaluation_url}?preview=1',
        )

        admin_tools = str(
            EventFormAdmin(EventForm, admin.site).registration_tools(
                evaluation_form
            )
        )
        self.assertIn(f"{evaluation_url}?preview=1", admin_tools)
        self.assertIn("Preview form", admin_tools)
        self.assertNotIn("View QR", admin_tools)

    def test_participant_evaluation_draft_is_saved_and_restored(self):
        call_command("setup_weuutz_evaluation", "--confirm")
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
            submitter_email="draft@example.com",
            is_complete=True,
        )
        first_question = (
            evaluation_form.sections.get(display_order=1)
            .questions.get(display_order=1, is_active=True)
        )
        selected_option = first_question.options.filter(is_active=True).first()
        evaluation_url = reverse(
            "forms_builder:public_event_form",
            kwargs={
                "event_slug": self.event.slug,
                "form_slug": evaluation_form.slug,
            },
        )
        participant_url = (
            f"{evaluation_url}?participant={registration.participant_token}"
        )

        save_response = self.client.post(
            participant_url,
            {
                "_save_draft": "1",
                f"question_{first_question.pk}": selected_option.value,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_response.json()["draft_saved"])
        draft = FormSubmission.objects.get(
            event_form=evaluation_form,
            registration_submission=registration,
            is_complete=False,
        )
        self.assertEqual(draft.answers.count(), 1)
        restored_response = self.client.get(participant_url)
        self.assertEqual(
            restored_response.context["draft_answer_values"],
            {str(first_question.pk): [selected_option.value]},
        )
        self.assertContains(restored_response, 'data-draft-autosave="true"')

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
