from django.contrib.auth.models import User
from django.test import TestCase

from events.auth import EventRole, event_role
from finance.views import get_user_role as get_finance_role
from tasks.views import _get_user_role as get_task_role

from .forms import AdminUserUpdateForm
from .models import Department, ModuleRoleAssignment
from .module_roles import set_module_role


class ModuleRoleAssignmentTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(code="DSTI", name="DSTI")
        self.user = User.objects.create_user(username="multi-role-user")
        self.user.profile.role = "REQUESTER"
        self.user.profile.department = self.department
        self.user.profile.save()

    def test_each_module_uses_its_assigned_role_without_changing_primary_role(self):
        set_module_role(
            self.user,
            ModuleRoleAssignment.Module.EVENT,
            "EVENT_ADMIN",
            self.department,
        )
        set_module_role(
            self.user,
            ModuleRoleAssignment.Module.FINANCE,
            "ACCOUNTANT",
            self.department,
        )
        set_module_role(
            self.user,
            ModuleRoleAssignment.Module.TASK,
            "HEAD_OF_UNIT",
            self.department,
        )

        self.assertEqual(event_role(self.user), EventRole.EVENT_ADMIN)
        self.assertEqual(get_finance_role(self.user), "ACCOUNTANT")
        self.assertEqual(get_task_role(self.user), "HEAD_OF_UNIT")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, "REQUESTER")

    def test_only_one_role_is_kept_per_module(self):
        set_module_role(
            self.user,
            ModuleRoleAssignment.Module.EVENT,
            "REPORT_OFFICER",
            self.department,
        )
        set_module_role(
            self.user,
            ModuleRoleAssignment.Module.EVENT,
            "EVENT_ADMIN",
            self.department,
        )

        assignments = ModuleRoleAssignment.objects.filter(
            user=self.user,
            module=ModuleRoleAssignment.Module.EVENT,
        )
        self.assertEqual(assignments.count(), 1)
        self.assertEqual(assignments.get().role_code, "EVENT_ADMIN")

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
                "event_role": "EVENT_ADMIN",
                "finance_role": "",
                "task_role": "",
                "is_staff": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("department", form.errors)
