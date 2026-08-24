from datetime import timedelta
import shutil
import tempfile
from uuid import uuid4

from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from core.models import Council, Country, Region
from permits.models import Department

from .access import events_visible_to
from .auth import EventRole
from .models import Event, EventCategory, EventTimetable, Venue
from forms_builder.models import CertificateRecord, EventForm, FormSubmission
from checkin.models import ParticipantCheckIn
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

    def test_event_administrator_can_create_event_with_manually_entered_venue(self):
        user = self._staff("manual-venue-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)
        now = timezone.now()
        country = Country.objects.create(
            name_sw="Tanzania",
            name_en="Tanzania",
            code="TZA",
        )
        region = Region.objects.create(
            country=country,
            name_sw="Dodoma",
            name_en="Dodoma",
            code="DOM",
        )
        council = Council.objects.create(
            region=region,
            name_sw="Jiji la Dodoma",
            name_en="Dodoma City",
            code="DODOMA-CITY",
            council_type=Council.CouncilType.CITY,
        )

        response = self.client.post(
            reverse("events:department_event_create"),
            {
                "category": self.category.pk,
                "venue_mode": "NEW",
                "new_venue_name": "  Ministry   Conference Hall  ",
                "new_venue_country": country.pk,
                "new_venue_region": region.pk,
                "new_venue_council": council.pk,
                "code": "DSTI-HALL-2027",
                "title_sw": "Tukio la DSTI",
                "title_en": "DSTI Hall Event",
                "starts_at": now.strftime("%Y-%m-%dT%H:%M"),
                "ends_at": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "status": Event.Status.DRAFT,
                "payment_currency": "TZS",
            },
        )

        self.assertRedirects(response, reverse("events:department_event_list"))
        created = Event.objects.get(code="DSTI-HALL-2027")
        self.assertEqual(created.venue.name, "Ministry Conference Hall")
        self.assertEqual(created.venue.council, council)
        self.assertEqual(created.venue.council.region, region)
        self.assertEqual(created.venue.council.region.country, country)
        self.assertEqual(created.venue.created_by, user)

    def test_event_creation_rejects_existing_and_manual_venue_together(self):
        venue = Venue.objects.create(name="Existing Hall")
        user = self._staff("ambiguous-venue-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)
        now = timezone.now()

        response = self.client.post(
            reverse("events:department_event_create"),
            {
                "category": self.category.pk,
                "venue_mode": "NEW",
                "venue": venue.pk,
                "new_venue_name": "Another Hall",
                "code": "DSTI-AMBIGUOUS-2027",
                "title_sw": "Tukio la DSTI",
                "title_en": "DSTI Ambiguous Event",
                "starts_at": now.strftime("%Y-%m-%dT%H:%M"),
                "ends_at": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "status": Event.Status.DRAFT,
                "payment_currency": "TZS",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Clear the saved venue when creating a new one.",
        )
        self.assertFalse(Event.objects.filter(code="DSTI-AMBIGUOUS-2027").exists())

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

    def test_registration_remains_available_while_event_is_ongoing(self):
        now = timezone.now()
        self.dsti_event.starts_at = now - timedelta(hours=1)
        self.dsti_event.ends_at = now + timedelta(hours=2)
        self.dsti_event.status = Event.Status.ONGOING
        self.dsti_event.is_public = True
        self.dsti_event.registration_enabled = True
        self.dsti_event.save()
        registration_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili unaoendelea",
            name_en="Ongoing registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_active=True,
            is_published=True,
        )

        response = self.client.get(reverse(
            "events:event_detail",
            kwargs={"event_slug": self.dsti_event.slug},
        ))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["registration_available"])
        self.assertContains(
            response,
            reverse(
                "forms_builder:public_event_form",
                kwargs={
                    "event_slug": self.dsti_event.slug,
                    "form_slug": registration_form.slug,
                },
            ),
        )

    def test_registration_closes_when_event_ends(self):
        now = timezone.now()
        self.dsti_event.starts_at = now - timedelta(hours=2)
        self.dsti_event.ends_at = now - timedelta(minutes=1)
        self.dsti_event.status = Event.Status.ONGOING
        self.dsti_event.is_public = True
        self.dsti_event.registration_enabled = True
        self.dsti_event.save()
        registration_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili uliofungwa",
            name_en="Ended registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_active=True,
            is_published=True,
        )

        detail_response = self.client.get(reverse(
            "events:event_detail",
            kwargs={"event_slug": self.dsti_event.slug},
        ))
        form_response = self.client.post(reverse(
            "forms_builder:public_event_form",
            kwargs={
                "event_slug": self.dsti_event.slug,
                "form_slug": registration_form.slug,
            },
        ))

        self.assertFalse(detail_response.context["registration_available"])
        self.assertTrue(detail_response.context["registration_closed"])
        self.assertEqual(form_response.status_code, 400)
        self.assertEqual(
            form_response.json()["message"],
            "The submission period for this form has ended.",
        )

    def test_registration_can_be_configured_to_close_after_event_starts(self):
        now = timezone.now()
        self.dsti_event.starts_at = now
        self.dsti_event.ends_at = now + timedelta(hours=3)
        self.dsti_event.registration_closes_at = now + timedelta(hours=2)

        self.dsti_event.full_clean()

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

    def test_event_admin_uploads_and_shares_stable_public_timetable(self):
        user = self._staff("timetable-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        self.dsti_event.is_public = True
        self.dsti_event.save(update_fields=["is_public", "updated_at"])
        self.client.force_login(user)
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, True)

        with override_settings(MEDIA_ROOT=media_root, PUBLIC_BASE_URL="https://events.test"):
            upload_response = self.client.post(
                reverse("events:department_event_timetable", kwargs={
                    "event_slug": self.dsti_event.slug,
                }),
                {
                    "title_sw": "Ratiba ya kilele",
                    "title_en": "Climax timetable",
                    "pdf_file": SimpleUploadedFile(
                        "ratiba.pdf", b"%PDF-1.4\n%%EOF", "application/pdf"
                    ),
                    "is_published": "on",
                },
            )
            timetable = EventTimetable.objects.get(event=self.dsti_event)
            public_url = reverse("events:public_event_timetable", kwargs={
                "event_slug": self.dsti_event.slug,
                "public_token": timetable.public_token,
            })
            download_url = reverse("events:public_event_timetable_download", kwargs={
                "event_slug": self.dsti_event.slug,
                "public_token": timetable.public_token,
            })

            self.assertRedirects(
                upload_response,
                reverse("events:department_event_timetable", kwargs={
                    "event_slug": self.dsti_event.slug,
                }),
            )
            public_response = self.client.get(public_url)
            self.assertContains(public_response, "Climax timetable")
            self.assertContains(public_response, "View timetable")
            self.assertContains(public_response, "Download timetable")
            self.assertNotContains(public_response, "Registration Status")
            self.assertNotContains(public_response, "Event information")
            self.assertEqual(self.client.get(download_url).status_code, 200)
            qr_response = self.client.get(reverse(
                "events:public_event_timetable_qr",
                kwargs={
                    "event_slug": self.dsti_event.slug,
                    "public_token": timetable.public_token,
                },
            ))
            self.assertEqual(qr_response.status_code, 200)
            self.assertEqual(qr_response["Content-Type"], "image/png")

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

    def test_event_administrator_can_open_safe_elimu_certificate_preview(self):
        self.dsti_event.code = "WEUUTz-2026"
        self.dsti_event.title_en = "Education and Innovation Week"
        self.dsti_event.save()
        self.assertEqual(self.dsti_event.code, "WEUUTz-2026")
        user = self._staff("elimu-preview-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)

        detail_response = self.client.get(reverse(
            "events:department_event_detail",
            kwargs={"event_slug": self.dsti_event.slug},
        ))
        preview_url = reverse(
            "events:department_certificate_preview",
            kwargs={"event_slug": self.dsti_event.slug},
        )
        preview_response = self.client.get(preview_url)

        self.assertContains(detail_response, preview_url)
        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, "SAMPLE · NOT VALID")
        self.assertContains(preview_response, "Sample Participating Institution")
        self.assertContains(preview_response, "Prof. Carolyne I. Nombo")
        self.assertContains(
            preview_response,
            "images/weuutz-permanent-secretary-signature.png",
        )
        self.assertContains(preview_response, "CERTIFICATION OF PARTICIPATION")
        self.assertContains(preview_response, "SAMPLE QR - NOT VALID")
        self.assertContains(preview_response, "data:image/png;base64,")
        self.assertNotContains(preview_response, "Download PDF certificate")

    def test_exhibition_workspace_links_participants_and_certificate_review(self):
        self.category.code = "EXHIBITION"
        self.category.name_en = "Exhibition"
        self.category.name_sw = "Maonesho"
        self.category.slug = "exhibition"
        self.category.save(update_fields=[
            "code", "name_en", "name_sw", "slug", "updated_at",
        ])
        self.dsti_event.certificate_enabled = True
        self.dsti_event.badge_enabled = True
        self.dsti_event.save(update_fields=[
            "certificate_enabled", "badge_enabled", "updated_at",
        ])
        EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili wa Waoneshaji",
            name_en="Exhibitor registration",
            form_type=EventForm.FormType.EXHIBITOR,
            is_active=True,
        )
        user = self._staff("exhibition-event-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)

        response = self.client.get(reverse(
            "events:department_event_detail",
            kwargs={"event_slug": self.dsti_event.slug},
        ))

        reports_url = reverse("checkin:reports")
        self.assertContains(response, "Registration and Certificate approval")
        self.assertContains(
            response,
            f"{reports_url}?event={self.dsti_event.pk}&amp;filter=registration_certificates",
        )
        self.assertContains(response, "Certificate list")
        self.assertContains(
            response,
            f"{reports_url}?event={self.dsti_event.pk}&amp;filter=certificate_list",
        )

    def test_event_administrator_can_authorize_checked_in_certificate(self):
        self.dsti_event.certificate_enabled = True
        self.dsti_event.badge_enabled = True
        self.dsti_event.save(update_fields=[
            "certificate_enabled", "badge_enabled", "updated_at",
        ])
        registration_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili",
            name_en="Registration",
            form_type=EventForm.FormType.EXHIBITOR,
            is_active=True,
        )
        submission = FormSubmission.objects.create(
            event_form=registration_form,
            is_complete=True,
            review_status=FormSubmission.ReviewStatus.APPROVED,
        )
        user = self._staff("certificate-event-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        ParticipantCheckIn.objects.create(
            submission=submission,
            checked_in_by=user,
            method=ParticipantCheckIn.Method.MANUAL,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("checkin:reports"),
            {
                "event": self.dsti_event.pk,
                "filter": "certificate_review",
                "submission": [submission.pk],
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('checkin:reports')}?event={self.dsti_event.pk}"
            "&filter=certificate_review",
        )
        record = CertificateRecord.objects.get(submission=submission)
        self.assertEqual(record.status, CertificateRecord.Status.AUTHORIZED)
        self.assertEqual(record.authorized_by, user)

        list_response = self.client.get(
            reverse("checkin:reports"),
            {"event": self.dsti_event.pk, "filter": "all"},
        )
        self.assertContains(list_response, "Registered participants")
        self.assertContains(list_response, "Details")
        self.assertContains(
            list_response,
            reverse(
                "checkin:participant_staff_detail",
                kwargs={"submission_id": submission.pk},
            ),
        )
        self.assertContains(list_response, "Badge / QR")
        self.assertContains(list_response, "Print A4 list")
        self.assertContains(list_response, "Download Excel")

        print_response = self.client.get(
            reverse("checkin:participant_list_print"),
            {"event": self.dsti_event.pk},
        )
        self.assertEqual(print_response.status_code, 200)
        self.assertContains(print_response, submission.reference_number)
        self.assertContains(print_response, "Certificate number")
        self.assertContains(print_response, record.certificate_number)
        self.assertNotContains(print_response, ">Attendance</th>")

        excel_response = self.client.get(
            reverse("checkin:participant_list_excel"),
            {"event": self.dsti_event.pk},
        )
        self.assertEqual(excel_response.status_code, 200)
        self.assertEqual(
            excel_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        detail_url = reverse(
            "checkin:participant_staff_detail",
            kwargs={"submission_id": submission.pk},
        )
        detail_response = self.client.get(detail_url)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Participant details")
        self.assertContains(detail_response, "Revoke certificate")

        revoke_response = self.client.post(detail_url, {
            "action": "revoke",
            "reason": "Certificate issued in error",
        })
        self.assertRedirects(revoke_response, detail_url)
        record.refresh_from_db()
        self.assertEqual(record.status, CertificateRecord.Status.REVOKED)
        self.assertEqual(record.revocation_reason, "Certificate issued in error")

    def test_certificate_authorization_waits_for_check_in(self):
        self.dsti_event.certificate_enabled = True
        self.dsti_event.save(update_fields=["certificate_enabled", "updated_at"])
        registration_form = EventForm.objects.create(
            event=self.dsti_event,
            name_sw="Usajili",
            name_en="Registration",
            form_type=EventForm.FormType.EXHIBITOR,
            is_active=True,
        )
        submission = FormSubmission.objects.create(
            event_form=registration_form,
            is_complete=True,
            review_status=FormSubmission.ReviewStatus.APPROVED,
        )
        user = self._staff("pre-checkin-certificate-admin", self.dsti)
        user.profile.role = "EVENT_ADMIN"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)
        detail_url = reverse(
            "checkin:participant_staff_detail",
            kwargs={"submission_id": submission.pk},
        )

        detail_response = self.client.get(detail_url)
        self.assertContains(
            detail_response,
            "Certificate approval will become available after this participant checks in.",
        )
        authorize_response = self.client.post(detail_url, {"action": "authorize"})
        self.assertRedirects(authorize_response, detail_url)
        self.assertFalse(
            CertificateRecord.objects.filter(submission=submission).exists()
        )

    def test_registration_officer_cannot_open_certificate_preview(self):
        self.dsti_event.code = "WEUUTz-2026"
        self.dsti_event.save()
        user = self._staff("elimu-preview-registration", self.dsti)
        user.profile.role = "REGISTRATION_OFFICER"
        user.profile.save(update_fields=["role"])
        self.client.force_login(user)

        response = self.client.get(reverse(
            "events:department_certificate_preview",
            kwargs={"event_slug": self.dsti_event.slug},
        ))

        self.assertEqual(response.status_code, 403)

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
