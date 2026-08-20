from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import TestCase
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from permits.models import Department

from .access import events_visible_to
from .auth import EventRole
from .models import Event, EventCategory
from forms_builder.models import EventForm, FormSubmission
from conferences.views import _conference_registration_forms
from permits.views import system_home


class DepartmentEventAccessTests(TestCase):
    def setUp(self):
        self.dsti = Department.objects.create(
            code="DSTI", name="Department of Science Technology and Innovation"
        )
        self.dhe = Department.objects.create(
            code="DHE", name="Department of Higher Education"
        )
        self.category = EventCategory.objects.create(
            code="CONFERENCE", name_sw="Kongamano", name_en="Conference"
        )
        now = timezone.now()
        self.dsti_event = Event.objects.create(
            owning_department=self.dsti,
            category=self.category,
            code="NESIF-2026",
            title_sw="NESIF",
            title_en="NESIF",
            starts_at=now,
            ends_at=now + timedelta(days=1),
        )
        self.dhe_event = Event.objects.create(
            owning_department=self.dhe,
            category=self.category,
            code="DHE-2026",
            title_sw="DHE Event",
            title_en="DHE Event",
            starts_at=now,
            ends_at=now + timedelta(days=1),
        )

    def _staff(self, username, department):
        user = User.objects.create_user(username=username, password="safe-password")
        user.profile.department = department
        user.profile.save(update_fields=["department"])
        return user

    def test_department_staff_only_see_their_department_events(self):
        dsti_user = self._staff("dsti-user", self.dsti)
        self.assertEqual(list(events_visible_to(dsti_user)), [self.dsti_event])

    def test_other_department_starts_with_empty_workspace(self):
        empty_department = Department.objects.create(code="DPP", name="Policy and Planning")
        user = self._staff("dpp-user", empty_department)
        self.client.force_login(user)
        response = self.client.get(reverse("events:department_event_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No events created")
        self.assertNotContains(response, "NESIF-2026")

    def test_system_administrator_can_see_all_departments(self):
        admin = User.objects.create_superuser(
            username="system-admin", email="admin@example.test", password="safe-password"
        )
        self.assertEqual(events_visible_to(admin).count(), 2)

    def test_conference_registration_workspace_is_department_scoped(self):
        dsti_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili wa DSTI",
            name_en="DSTI registration",
            form_type=EventForm.FormType.REGISTRATION,
        )
        EventForm.objects.create(
            event=self.dhe_event,
            name_sw="Usajili wa DHE",
            name_en="DHE registration",
            form_type=EventForm.FormType.REGISTRATION,
        )
        dsti_user = self._staff("dsti-conference-user", self.dsti)
        self.assertEqual(
            list(_conference_registration_forms(dsti_user)),
            [dsti_form],
        )

    def test_department_head_creates_event_for_own_department(self):
        user = self._staff("dhe-head", self.dhe)
        user.profile.role = "HEAD_OF_UNIT"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)
        now = timezone.now()
        response = self.client.post(
            reverse("events:department_event_create"),
            {
                "category": self.category.pk,
                "code": "DHE-FORUM-2027",
                "title_sw": "Jukwaa la DHE",
                "title_en": "DHE Forum",
                "starts_at": now.strftime("%Y-%m-%dT%H:%M"),
                "ends_at": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "status": Event.Status.DRAFT,
                "payment_currency": "TZS",
            },
        )
        self.assertRedirects(response, reverse("events:department_event_list"))
        created = Event.objects.get(code="DHE-FORUM-2027")
        self.assertEqual(created.owning_department, self.dhe)
        self.assertNotIn(created, events_visible_to(self._staff("dsti-other", self.dsti)))

    def test_direct_staff_url_cannot_bypass_department_ownership(self):
        dsti_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili wa DSTI",
            name_en="DSTI registration",
            form_type=EventForm.FormType.REGISTRATION,
        )
        dhe_user = self._staff("dhe-direct-url", self.dhe)
        dhe_user.profile.role = "DIRECTOR"
        dhe_user.profile.save(update_fields=["role"])
        self.client.force_login(dhe_user)

        response = self.client.get(
            reverse("conferences:conference_detail", kwargs={"form_id": dsti_form.pk})
        )

        self.assertEqual(response.status_code, 403)

    def test_event_management_roles_are_available_to_user_administration(self):
        role_codes = dict(self.dsti.user_profiles.model.ROLE_CHOICES)
        self.assertIn("EVENT_ADMIN", role_codes)
        self.assertIn("REGISTRATION_OFFICER", role_codes)
        self.assertIn("ATTENDANCE_OFFICER", role_codes)
        self.assertIn("REPORT_OFFICER", role_codes)

    def test_registration_officer_maps_to_event_registration_access(self):
        user = self._staff("registration-officer", self.dsti)
        user.profile.role = "REGISTRATION_OFFICER"
        user.profile.save(update_fields=["role"])
        self.assertEqual(user.role, EventRole.REGISTRATION_OFFICER)

    def test_system_home_discards_messages_from_unrelated_workflows(self):
        admin = User.objects.create_superuser(
            username="message-admin",
            email="messages@example.test",
            password="safe-password",
        )
        request = RequestFactory().get("/")
        SessionMiddleware(lambda response: response).process_request(request)
        request.session.save()
        MessageMiddleware(lambda response: response).process_request(request)
        request.user = admin
        messages.success(request, "User account updated successfully.")

        response = system_home(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(request._messages.used)
        self.assertNotIn(
            b"User account updated successfully.",
            response.content,
        )

    def test_old_badge_qr_url_redirects_to_integrated_check_in(self):
        participant_token = uuid4()

        response = self.client.get(
            f"/en/check-in/{participant_token}/?auto=1",
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            f"/event-management/check-in/{participant_token}/?auto=1",
        )

    def test_old_participant_portal_url_redirects_with_same_token(self):
        participant_token = uuid4()

        response = self.client.get(f"/sw/participants/{participant_token}/")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            f"/event-management/participants/{participant_token}/",
        )

    def test_conference_evaluation_is_available_in_participant_portal(self):
        registration_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili wa NESIF",
            name_en="NESIF registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_active=True,
        )
        submission = FormSubmission.objects.create(
            event_form=registration_form,
            submitter_email="participant@example.test",
            is_complete=True,
            is_active=True,
        )

        response = self.client.get(
            reverse(
                "forms_builder:participant_portal",
                kwargs={"participant_token": submission.participant_token},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "conferences:feedback_submit",
                kwargs={"event_slug": self.dsti_event.slug},
            ),
        )
        self.assertContains(response, "Conference feedback and evaluation")

    def test_event_operations_are_inside_selected_event_workspace(self):
        user = self._staff("event-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        registration_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili wa NESIF",
            name_en="NESIF registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_active=True,
        )
        evaluation_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Tathmini ya NESIF",
            name_en="NESIF evaluation",
            form_type=EventForm.FormType.EVALUATION,
            is_active=True,
        )
        self.client.force_login(user)

        list_response = self.client.get(reverse("events:department_event_list"))

        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, "Your event operations")
        self.assertNotContains(list_response, reverse("checkin:lookup"))
        self.assertContains(
            list_response,
            reverse(
                "events:department_event_detail",
                kwargs={"event_slug": self.dsti_event.slug},
            ),
        )

        response = self.client.get(reverse(
            "events:department_event_detail",
            kwargs={"event_slug": self.dsti_event.slug},
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.dsti_event.code)
        self.assertContains(
            response,
            reverse(
                "conferences:conference_detail",
                kwargs={"form_id": registration_form.pk},
            ),
        )
        self.assertContains(response, f"{reverse('checkin:lookup')}?event={self.dsti_event.pk}")
        self.assertContains(response, f"{reverse('checkin:reports')}?event={self.dsti_event.pk}")
        self.assertContains(
            response,
            f"{reverse('forms_builder:evaluation_reports')}?form={evaluation_form.pk}",
        )
        self.assertNotContains(response, reverse("meetings:meeting_list"))

    def test_event_workspace_cannot_bypass_department_ownership(self):
        user = self._staff("dsti-workspace-user", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)

        response = self.client.get(reverse(
            "events:department_event_detail",
            kwargs={"event_slug": self.dhe_event.slug},
        ))

        self.assertEqual(response.status_code, 404)

    def test_event_administrator_special_events_are_department_scoped(self):
        special_category = EventCategory.objects.create(
            code="SPECIAL_EVENT",
            name_sw="Tukio maalum",
            name_en="Special Event",
            slug="special-event",
        )
        dsti_special = Event.objects.create(
            owning_department=self.dsti,
            category=special_category,
            code="TUZO-TEST",
            title_sw="Tuzo",
            title_en="Awards",
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=1),
        )
        user = self._staff("dsti-event-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)

        response = self.client.get(
            reverse("events:special_event_participant_list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, dsti_special.code)
        self.assertNotContains(response, self.dhe_event.code)
