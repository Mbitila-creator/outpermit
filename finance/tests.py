from django.contrib.auth.models import User
from django.test import TestCase

from permits.models import Department

from .models import BudgetLine
from .views import get_visible_budget_lines

class ExecutiveFinanceVisibilityTests(TestCase):
    def setUp(self):
        self.dsti = Department.objects.create(code="DSTI", name="Science and Technology")
        self.hed = Department.objects.create(code="HED", name="Higher Education")
        self.fau = Department.objects.create(code="FAU", name="Finance and Accounting")
        for index, department in enumerate((self.dsti, self.hed, self.fau), start=1):
            BudgetLine.objects.create(department=department, task_code=f"TASK-{index}")

    def _official(self, username, role):
        user = User.objects.create_user(username=username, password="safe-password")
        user.profile.role = role
        user.profile.save(update_fields=["role"])
        return user

    def test_ps_can_view_all_finance_departments(self):
        user = self._official("ps-finance", "PERMANENT_SECRETARY")
        self.assertEqual(get_visible_budget_lines(user).count(), 3)

    def test_dps_hes_finance_scope_excludes_direct_ps_units(self):
        user = self._official("dps-hes-finance", "DPS_HES")
        codes = set(
            get_visible_budget_lines(user).values_list("department__code", flat=True)
        )
        self.assertEqual(codes, {"DSTI", "HED"})

    def test_executive_finance_create_is_forbidden(self):
        user = self._official("ps-read-only", "PERMANENT_SECRETARY")
        self.client.force_login(user)
        response = self.client.get("/finance/minute-sheets/create/")
        self.assertEqual(response.status_code, 403)
