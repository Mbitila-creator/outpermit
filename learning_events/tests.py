from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventCategory
from checkin.models import ParticipantCheckIn
from forms_builder.models import CertificateRecord, EventForm, FormSubmission
from permits.models import Department

from .models import (
    LearningAssessment, LearningAssessmentResult, LearningAttendance,
    LearningEnrollment, LearningEventProfile, LearningSession, SeminarQuestion,
    WorkshopActivity,
)


class LearningEventTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(code="DHE", name="Higher Education")
        self.user = User.objects.create_user("learning-admin", password="safe-password")
        self.user.profile.department = self.department
        self.user.profile.role = "EVENT_ADMIN"
        self.user.profile.save(update_fields=("department", "role"))
        self.categories = {
            code: EventCategory.objects.create(code=code, name_sw=code.title(), name_en=code.title())
            for code in ("SEMINAR", "WORKSHOP", "TRAINING")
        }
        now = timezone.now()
        self.events = {
            code: Event.objects.create(
                category=category, owning_department=self.department,
                code=f"{code}-2026", title_sw=code.title(), title_en=code.title(),
                starts_at=now, ends_at=now + timedelta(days=2), is_public=True,
            )
            for code, category in self.categories.items()
        }

    def test_all_remaining_categories_open_shared_operations(self):
        self.client.force_login(self.user)
        for event in self.events.values():
            response = self.client.get(reverse("learning_events:dashboard", args=(event.slug,)))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["category_code"], event.category.code)

    def test_training_certificate_requires_attendance_and_passing_post_assessment(self):
        event = self.events["TRAINING"]
        profile = LearningEventProfile.objects.create(
            event=event, minimum_attendance_percentage=Decimal("75"),
            post_assessment_pass_percentage=Decimal("60"),
        )
        sessions = [LearningSession.objects.create(
            profile=profile, code=f"S{i}", title=f"Lesson {i}",
            session_type=LearningSession.SessionType.LESSON,
            starts_at=event.starts_at + timedelta(hours=i),
            ends_at=event.starts_at + timedelta(hours=i + 1),
        ) for i in range(4)]
        participant = LearningEnrollment.objects.create(profile=profile, full_name="Asha Juma")
        assessment = LearningAssessment.objects.create(
            profile=profile, title="Final test",
            assessment_type=LearningAssessment.AssessmentType.POST, maximum_score=100,
        )
        for session in sessions[:3]:
            LearningAttendance.objects.create(session=session, enrollment=participant, checked_in_by=self.user)
        LearningAssessmentResult.objects.create(
            assessment=assessment, enrollment=participant, score=59, recorded_by=self.user,
        )
        self.assertEqual(participant.attendance_percentage, Decimal("75.00"))
        self.assertFalse(participant.certificate_eligible)

        result = participant.assessment_results.get()
        result.score = 60
        result.save()
        self.assertTrue(participant.certificate_eligible)

    def test_generic_certificate_authorization_cannot_bypass_training_rule(self):
        event = self.events["TRAINING"]
        profile = LearningEventProfile.objects.create(
            event=event, minimum_attendance_percentage=100,
            post_assessment_pass_percentage=60,
        )
        session = LearningSession.objects.create(
            profile=profile, code="LESSON", title="Lesson",
            starts_at=event.starts_at, ends_at=event.starts_at + timedelta(hours=1),
        )
        registration_form = EventForm.objects.create(
            event=event, name_sw="Usajili", name_en="Registration",
            form_type=EventForm.FormType.REGISTRATION,
        )
        submission = FormSubmission.objects.create(
            event_form=registration_form, review_status=FormSubmission.ReviewStatus.APPROVED,
            badge_name="Trainee One",
        )
        ParticipantCheckIn.objects.create(submission=submission, checked_in_by=self.user)
        enrollment = LearningEnrollment.objects.create(
            profile=profile, registration=submission, full_name="Trainee One",
        )
        assessment = LearningAssessment.objects.create(
            profile=profile, title="Post test", assessment_type="POST", maximum_score=100,
        )
        certificate = CertificateRecord(
            submission=submission, certificate_number="TEST-CERT-1",
            status=CertificateRecord.Status.AUTHORIZED,
            authorized_by=self.user, authorized_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            certificate.save()

        LearningAttendance.objects.create(
            session=session, enrollment=enrollment, checked_in_by=self.user,
        )
        LearningAssessmentResult.objects.create(
            assessment=assessment, enrollment=enrollment, score=60, recorded_by=self.user,
        )
        certificate.save()
        self.assertTrue(CertificateRecord.objects.filter(pk=certificate.pk).exists())

    def test_training_certificate_fails_when_score_passes_but_attendance_is_low(self):
        event = self.events["TRAINING"]
        profile = LearningEventProfile.objects.create(event=event)
        sessions = [LearningSession.objects.create(
            profile=profile, code=f"L{i}", title=f"Lesson {i}",
            starts_at=event.starts_at + timedelta(hours=i),
            ends_at=event.starts_at + timedelta(hours=i + 1),
        ) for i in range(2)]
        participant = LearningEnrollment.objects.create(profile=profile, full_name="John Doe")
        assessment = LearningAssessment.objects.create(
            profile=profile, title="Post test", assessment_type="POST", maximum_score=100,
        )
        LearningAttendance.objects.create(session=sessions[0], enrollment=participant, checked_in_by=self.user)
        LearningAssessmentResult.objects.create(
            assessment=assessment, enrollment=participant, score=90, recorded_by=self.user,
        )
        self.assertFalse(participant.certificate_eligible)

    def test_category_specific_records_are_protected(self):
        seminar_profile = LearningEventProfile.objects.create(event=self.events["SEMINAR"])
        workshop_profile = LearningEventProfile.objects.create(event=self.events["WORKSHOP"])
        session = LearningSession.objects.create(
            profile=workshop_profile, code="P1", title="Practical",
            starts_at=self.events["WORKSHOP"].starts_at,
            ends_at=self.events["WORKSHOP"].starts_at + timedelta(hours=1),
        )
        WorkshopActivity.objects.create(session=session, title="Group exercise", instructions="Prepare an output")
        SeminarQuestion.objects.create(profile=seminar_profile, question="What is the next step?")
        with self.assertRaises(ValidationError):
            LearningAssessment.objects.create(
                profile=seminar_profile, title="Not allowed", assessment_type="POST", maximum_score=100,
            )

    def test_public_programme_contains_only_published_sessions(self):
        event = self.events["SEMINAR"]
        profile = LearningEventProfile.objects.create(event=event)
        LearningSession.objects.create(
            profile=profile, code="PUB", title="Published talk",
            starts_at=event.starts_at, ends_at=event.starts_at + timedelta(hours=1),
            is_published=True,
        )
        LearningSession.objects.create(
            profile=profile, code="DRAFT", title="Draft talk",
            starts_at=event.starts_at + timedelta(hours=1), ends_at=event.starts_at + timedelta(hours=2),
            is_published=False,
        )
        response = self.client.get(reverse("learning_events:public_programme", args=(event.slug,)))
        self.assertContains(response, "Published talk")
        self.assertNotContains(response, "Draft talk")
