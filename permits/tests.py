from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from events.auth import EventRole, event_role, has_event_role
from finance.views import get_user_role as get_finance_role
from tasks.views import _get_user_role as get_task_role

from .forms import AdminUserUpdateForm
from .models import Department, ModuleRoleAssignment
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
