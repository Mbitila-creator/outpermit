from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from permits.models import (
    ApprovalRole,
    Department,
    DepartmentUnit,
    ModuleRoleAssignment,
)

from .forms import TaskCreateForm
from .models import Task, TaskAssignment
from .views import _get_visible_task_scope


class ExecutiveTaskAccessTests(TestCase):
    def setUp(self):
        self.roles = {}
        for code, name in (
            ("PERMANENT_SECRETARY", "Permanent Secretary"),
            ("DPS_HES", "DPS HES"),
            ("DPS_BE", "DPS BE"),
            ("COMMISSIONER_EDUCATION", "Commissioner for Education"),
            ("DIRECTOR", "Director"),
            ("HEAD_OF_UNIT", "Head of Unit"),
            ("REQUESTER", "Requester"),
        ):
            self.roles[code], _ = ApprovalRole.objects.update_or_create(
                code=code, defaults={"name": name, "is_active": True}
            )

        self.hed, _ = Department.objects.update_or_create(
            code="HED", defaults={"name": "Higher Education"}
        )
        self.sqad, _ = Department.objects.update_or_create(
            code="SQAD", defaults={"name": "Quality Assurance"}
        )
        self.coe, _ = Department.objects.update_or_create(
            code="COE", defaults={"name": "Office for Commissioner of Education"}
        )
        self.fau, _ = Department.objects.update_or_create(
            code="FAU", defaults={"name": "Finance and Accounting Unit"}
        )
        self.dsti, _ = Department.objects.update_or_create(
            code="DSTI", defaults={"name": "Science Technology and Innovation"}
        )
        self.bed, _ = DepartmentUnit.objects.update_or_create(
            department=self.coe,
            code="BED",
            defaults={"name": "Basic Education Division"},
        )

        self.ps = self._user("ps-task", "PERMANENT_SECRETARY")
        self.dpss = self._user("dpss-task", "DPS_HES")
        self.dpse = self._user("dpse-task", "DPS_BE")
        self.commissioner = self._user(
            "commissioner-task", "COMMISSIONER_EDUCATION", self.coe
        )
        self.hed_director = self._user(
            "hed-director-task", "DIRECTOR", self.hed
        )
        self.sqad_director = self._user(
            "sqad-director-task", "DIRECTOR", self.sqad
        )
        self.fau_director = self._user(
            "fau-director-task", "DIRECTOR", self.fau
        )
        self.bed_director = self._user(
            "bed-director-task", "DIRECTOR", self.coe, self.bed
        )
        self.ordinary_staff = self._user(
            "ordinary-task", "REQUESTER", self.hed
        )

    def _user(self, username, role_code, department=None, unit=None):
        user = User.objects.create_user(username=username, password="safe-pass")
        user.profile.role = role_code
        user.profile.approval_role = self.roles[role_code]
        user.profile.department = department
        user.profile.department_unit = unit
        user.profile.save()
        return user

    def _assignee_ids(self, executive):
        form = TaskCreateForm(user=executive, assignee_scope="OTHER")
        return set(form.fields["assigned_users"].queryset.values_list("pk", flat=True))

    def test_ps_can_assign_deputies_directors_and_heads_not_ordinary_staff(self):
        ids = self._assignee_ids(self.ps)
        self.assertTrue({self.dpss.pk, self.dpse.pk, self.hed_director.pk}.issubset(ids))
        self.assertNotIn(self.ordinary_staff.pk, ids)

    def test_deputy_scopes_follow_the_confirmed_ministry_hierarchy(self):
        dpss_ids = self._assignee_ids(self.dpss)
        self.assertIn(self.hed_director.pk, dpss_ids)
        self.assertNotIn(self.fau_director.pk, dpss_ids)
        self.assertNotIn(self.sqad_director.pk, dpss_ids)

        dpse_ids = self._assignee_ids(self.dpse)
        self.assertIn(self.commissioner.pk, dpse_ids)
        self.assertIn(self.sqad_director.pk, dpse_ids)
        self.assertNotIn(self.hed_director.pk, dpse_ids)

    def test_dps_hes_recognizes_existing_dsti_task_leadership_roles(self):
        dsti_director = self._user(
            "dsti-special-director", "REQUESTER", self.dsti
        )
        dsti_assistant = self._user("adsti", "REQUESTER", self.dsti)
        ModuleRoleAssignment.objects.create(
            user=dsti_director,
            module=ModuleRoleAssignment.Module.TASK,
            role_code="DIRECTOR",
            department=self.dsti,
        )
        ModuleRoleAssignment.objects.create(
            user=dsti_assistant,
            module=ModuleRoleAssignment.Module.TASK,
            role_code="ASSISTANT_DIRECTOR",
            department=self.dsti,
        )

        ids = self._assignee_ids(self.dpss)

        self.assertIn(dsti_director.pk, ids)
        self.assertIn(dsti_assistant.pk, ids)

    def test_duplicate_accounts_with_same_email_appear_as_one_assignee(self):
        assistant = self._user("adrd", "REQUESTER", self.dsti)
        assistant.first_name = "Edgar"
        assistant.last_name = "Kasuga"
        assistant.email = "edgar@example.go.tz"
        assistant.save()
        ModuleRoleAssignment.objects.create(
            user=assistant,
            module=ModuleRoleAssignment.Module.TASK,
            role_code="ASSISTANT_DIRECTOR",
            department=self.dsti,
        )

        head = self._user("edgar", "HEAD_OF_UNIT", self.dsti)
        head.first_name = "Edgar"
        head.last_name = "Kasuga"
        head.email = "EDGAR@example.go.tz"
        head.save()

        queryset = TaskCreateForm(
            user=self.dpss, assignee_scope="OTHER"
        ).fields["assigned_users"].queryset

        self.assertIn(assistant.pk, queryset.values_list("pk", flat=True))
        self.assertNotIn(head.pk, queryset.values_list("pk", flat=True))

    def test_commissioner_can_assign_only_coe_leadership(self):
        ids = self._assignee_ids(self.commissioner)
        self.assertIn(self.bed_director.pk, ids)
        self.assertNotIn(self.sqad_director.pk, ids)
        self.assertNotIn(self.hed_director.pk, ids)

    def test_executive_dashboards_and_analytics_use_hierarchical_scope(self):
        now = timezone.now()
        hed_task = Task.objects.create(
            title="HED task", created_by=self.dpss, department=self.hed,
            start_date=now, due_date=now + timedelta(days=2),
        )
        TaskAssignment.objects.create(
            task=hed_task, assigned_to=self.hed_director, assigned_by=self.dpss
        )
        fau_task = Task.objects.create(
            title="FAU task", created_by=self.ps, department=self.fau,
            start_date=now, due_date=now + timedelta(days=2),
        )
        TaskAssignment.objects.create(
            task=fau_task, assigned_to=self.fau_director, assigned_by=self.ps
        )

        dpss_tasks, _ = _get_visible_task_scope(self.dpss, strict_department=True)
        self.assertIn(hed_task, dpss_tasks)
        self.assertNotIn(fau_task, dpss_tasks)
        ps_tasks, _ = _get_visible_task_scope(self.ps, strict_department=True)
        self.assertEqual(set(ps_tasks), {hed_task, fau_task})

        self.client.force_login(self.ps)
        self.assertEqual(self.client.get(reverse("task_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("task_analytics")).status_code, 200)
