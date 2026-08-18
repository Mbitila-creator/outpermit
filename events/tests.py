from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from permits.models import Department

from .access import events_visible_to
from .models import Event, EventCategory
from forms_builder.models import EventForm
from conferences.views import _conference_registration_forms


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
