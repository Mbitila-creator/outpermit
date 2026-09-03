from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from io import BytesIO
from pypdf import PdfReader

from events.auth import EventRole, event_role, has_event_role
from finance.views import get_user_role as get_finance_role
from tasks.views import _get_user_role as get_task_role

from .forms import AdminUserUpdateForm
from .models import Department, ExternalWorkRequest, GroupMember, ModuleRoleAssignment
from .module_roles import set_module_roles


class ModuleRoleAssignmentTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(code="DSTI", name="DSTI")
        self.user = User.objects.create_user(username="multi-role-user")
        self.user.profile.role = "REQUESTER"
        self.user.profile.department = self.department
        self.user.profile.save()

    def test_each_module_uses_its_assigned_role_without_changing_primary_role(self):
        set_module_roles(
            self.user,
            ModuleRoleAssignment.Module.EVENT,
            ["EVENT_ADMIN"],
            self.department,
        )
        set_module_roles(
            self.user,
            ModuleRoleAssignment.Module.FINANCE,
            ["ACCOUNTANT"],
            self.department,
        )
        set_module_roles(
            self.user,
            ModuleRoleAssignment.Module.TASK,
            ["HEAD_OF_UNIT"],
            self.department,
        )

        self.assertEqual(event_role(self.user), EventRole.EVENT_ADMIN)
        self.assertEqual(get_finance_role(self.user), "ACCOUNTANT")
        self.assertEqual(get_task_role(self.user), "HEAD_OF_UNIT")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, "REQUESTER")

    def test_multiple_roles_are_kept_in_the_same_module(self):
        set_module_roles(
            self.user,
            ModuleRoleAssignment.Module.EVENT,
            ["REPORT_OFFICER", "ATTENDANCE_OFFICER"],
            self.department,
        )

        assignments = ModuleRoleAssignment.objects.filter(
            user=self.user,
            module=ModuleRoleAssignment.Module.EVENT,
        )
        self.assertEqual(assignments.count(), 2)
        self.assertEqual(
            set(assignments.values_list("role_code", flat=True)),
            {"REPORT_OFFICER", "ATTENDANCE_OFFICER"},
        )
        self.assertTrue(
            has_event_role(self.user, {EventRole.ATTENDANCE_OFFICER})
        )
        self.assertTrue(has_event_role(self.user, {EventRole.REPORT_OFFICER}))
        self.assertFalse(
            has_event_role(self.user, {EventRole.REGISTRATION_OFFICER})
        )

    def test_module_role_requires_a_department(self):
        form = AdminUserUpdateForm(
            data={
                "first_name": "Multi",
                "last_name": "Role",
                "email": "multi@example.com",
                "employee_id": "",
                "check_number": "",
                "phone_number": "",
                "department": "",
                "department_unit": "",
                "unit_name": "",
                "head_of_unit": "",
                "role": "REQUESTER",
                "event_role": ["EVENT_ADMIN"],
                "finance_role": [],
                "task_role": [],
                "is_staff": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("department", form.errors)


class AdministrationCentreTests(TestCase):
    def test_operations_are_grouped_by_department_and_role_dashboard(self):
        department = Department.objects.create(
            code="DTVET", name="Technical and Vocational Education and Training"
        )
        admin = User.objects.create_superuser(
            username="platform-admin", email="admin@example.test", password="safe"
        )
        officers = {}
        for role in ("DIRECTOR", "ASSISTANT_DIRECTOR", "HEAD_OF_UNIT"):
            officer = User.objects.create_user(
                username=role.lower(), first_name=role.title()
            )
            officer.profile.role = role
            officer.profile.department = department
            officer.profile.save(update_fields=["role", "department"])
            officers[role] = officer

        self.client.force_login(admin)
        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin Page")
        self.assertNotContains(response, "Ministry Enterprise Management Platform")
        self.assertContains(response, f'href="{reverse("system_home")}">Home</a>')
        self.assertContains(response, f'href="{reverse("logout")}" class="logout">Logout</a>')
        self.assertNotContains(response, ">Requester Dashboard</a>")
        self.assertNotContains(response, ">Create New Request</a>")
        self.assertContains(response, "Operations &amp; Dashboards", html=False)
        self.assertContains(response, department.code)
        self.assertContains(response, "Directors")
        self.assertContains(response, "Assistant Directors")
        self.assertContains(response, "Heads of Units")
        self.assertNotContains(response, "Recent Requests")
        self.assertNotContains(response, 'class="stats"')
        self.assertContains(
            response,
            f'{reverse("director_requests")}?department={department.pk}',
        )
        self.assertContains(
            response,
            f'{reverse("director_requests")}?officer='
            f'{officers["ASSISTANT_DIRECTOR"].pk}',
        )
        self.assertContains(
            response,
            f'{reverse("head_of_unit_requests")}?officer='
            f'{officers["HEAD_OF_UNIT"].pk}',
        )

        self.assertEqual(
            self.client.get(
                reverse("director_requests"), {"department": department.pk}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("director_requests"),
                {"officer": officers["ASSISTANT_DIRECTOR"].pk},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("head_of_unit_requests"),
                {"officer": officers["HEAD_OF_UNIT"].pk},
            ).status_code,
            200,
        )

    def test_admin_view_of_director_reports_keeps_department_unit_scope(self):
        selected_department = Department.objects.create(
            code="DTVET", name="Technical and Vocational Education and Training"
        )
        other_department = Department.objects.create(
            code="DSTI", name="Science Technology and Innovation"
        )
        admin = User.objects.create_superuser(
            username="report-admin", email="report-admin@example.test", password="safe"
        )
        director = User.objects.create_user(username="dtvet-director")
        director.profile.role = "DIRECTOR"
        director.profile.department = selected_department
        director.profile.save(update_fields=["role", "department"])
        own_unit_user = User.objects.create_user(username="dtvet-unit-user")
        own_unit_user.profile.department = selected_department
        own_unit_user.profile.unit_name = "DTVET_ONLY_UNIT"
        own_unit_user.profile.save(update_fields=["department", "unit_name"])
        other_unit_user = User.objects.create_user(username="dsti-unit-user")
        other_unit_user.profile.department = other_department
        other_unit_user.profile.unit_name = "DSTI_OTHER_UNIT"
        other_unit_user.profile.save(update_fields=["department", "unit_name"])

        self.client.force_login(admin)
        director_page = self.client.get(
            reverse("director_requests"),
            {"department": selected_department.pk},
        )
        self.assertContains(
            director_page,
            f'{reverse("permit_reports")}?department={selected_department.pk}',
        )

        report = self.client.get(
            reverse("permit_reports"),
            {"department": selected_department.pk},
        )
        self.assertEqual(report.status_code, 200)
        self.assertContains(report, "DTVET_ONLY_UNIT")
        self.assertNotContains(report, "DSTI_OTHER_UNIT")
        self.assertContains(
            report,
            f'name="department" value="{selected_department.pk}"',
        )

    def test_workforce_reports_separate_at_work_and_active_permission(self):
        department = Department.objects.create(code="DTVET", name="DTVET")
        admin = User.objects.create_superuser(
            username="workforce-admin", email="workforce@example.test", password="safe"
        )
        at_work = User.objects.create_user(
            username="at-work", first_name="At", last_name="Work"
        )
        permitted = User.objects.create_user(
            username="permitted", first_name="Active", last_name="Permit"
        )
        expired = User.objects.create_user(
            username="expired", first_name="Expired", last_name="Permit"
        )
        group_member = User.objects.create_user(
            username="group-member", first_name="Group", last_name="Member"
        )
        for worker in (at_work, permitted, expired, group_member):
            worker.profile.department = department
            worker.profile.save(update_fields=["department"])
        now = timezone.now()
        active_permit = ExternalWorkRequest.objects.create(
            requester=permitted,
            purpose="Official duty",
            destination="Dodoma",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(days=1),
            status="APPROVED",
            is_group_request=True,
        )
        GroupMember.objects.create(
            request=active_permit,
            member_user=group_member,
            full_name="Group Member",
        )
        ExternalWorkRequest.objects.create(
            requester=expired,
            purpose="Completed duty",
            destination="Arusha",
            start_time=now - timedelta(days=3),
            end_time=now - timedelta(days=1),
            status="APPROVED",
        )

        self.client.force_login(admin)
        response = self.client.get(
            reverse("permit_reports"),
            {"department": department.pk, "report": "active_permissions"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_report"], "active_permissions")
        self.assertContains(
            response,
            'name="report" id="selectedReport" value="active_permissions"',
            html=False,
        )
        self.assertContains(response, "Workers at Work")
        self.assertContains(response, "Workers with Active Permission")
        self.assertEqual(
            [row["worker"] for row in response.context["workforce_at_work_rows"]],
            [at_work, expired],
        )
        self.assertEqual(
            {row["worker"] for row in response.context["workforce_active_permission_rows"]},
            {permitted, group_member},
        )
        excel_response = self.client.get(
            reverse("export_permit_reports_excel"),
            {"department": department.pk, "report": "active_permissions"},
        )
        self.assertEqual(excel_response.status_code, 200)
        self.assertEqual(
            excel_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        at_work_pdf_response = self.client.get(
            reverse("export_permit_reports_pdf"),
            {"department": department.pk, "report": "workers_at_work"},
        )
        at_work_pdf = PdfReader(BytesIO(at_work_pdf_response.content))
        at_work_page = at_work_pdf.pages[0]
        self.assertLess(
            float(at_work_page.mediabox.width), float(at_work_page.mediabox.height)
        )
        at_work_text = "\n".join(page.extract_text() for page in at_work_pdf.pages)
        self.assertIn("Workers at Work Report", at_work_text)
        self.assertNotIn("Permit Reference", at_work_text)

        active_pdf_response = self.client.get(
            reverse("export_permit_reports_pdf"),
            {"department": department.pk, "report": "active_permissions"},
        )
        active_pdf = PdfReader(BytesIO(active_pdf_response.content))
        active_page = active_pdf.pages[0]
        self.assertGreater(
            float(active_page.mediabox.width), float(active_page.mediabox.height)
        )
        active_text = "\n".join(page.extract_text() for page in active_pdf.pages)
        self.assertIn("Workers with Active Permission Report", active_text)
        self.assertIn("Permission Starts", active_text)
        self.assertIn("Permission Ends", active_text)
