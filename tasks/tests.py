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

from .forms import (
    TaskCreateForm, TaskProposalForm, CrossDepartmentTaskRequestForm,
)
from .models import Task, TaskAssignment, CrossDepartmentTaskRequest
from .views import _get_visible_task_scope


class ExecutiveTaskAccessTests(TestCase):
    def setUp(self):
        self.roles = {}
        for code, name in (
            ("PERMANENT_SECRETARY", "Permanent Secretary"),
            ("DPS_HES", "DPS HES"),
            ("DPS_BE", "DPS BE"),
            ("COMMISSIONER_EDUCATION", "Commissioner of Education"),
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

    def _shared_task_form(self, group_leader=""):
        now = timezone.localtime().replace(second=0, microsecond=0)
        return TaskCreateForm(
            data={
                "title": "Executive shared task",
                "description": "Complete this task as a group.",
                "department": self.hed.pk,
                "priority": "MEDIUM",
                "start_date": now.strftime("%Y-%m-%dT%H:%M"),
                "due_date": (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
                "assigned_users": [self.dpss.pk, self.dpse.pk],
                "group_leader": group_leader,
                "assignee_scope": "OTHER",
            },
            user=self.ps,
        )

    def test_shared_task_requires_selected_assignee_as_group_leader(self):
        form = self._shared_task_form()
        self.assertFalse(form.is_valid())
        self.assertIn("group_leader", form.errors)

        form = self._shared_task_form(group_leader=self.hed_director.pk)
        self.assertFalse(form.is_valid())
        self.assertIn("group_leader", form.errors)

    def test_shared_task_accepts_one_selected_group_leader(self):
        form = self._shared_task_form(group_leader=self.dpss.pk)
        self.assertTrue(form.is_valid(), form.errors)

    def test_shared_task_creation_marks_exactly_one_group_leader(self):
        form = self._shared_task_form(group_leader=self.dpss.pk)
        self.client.force_login(self.ps)
        response = self.client.post(reverse("create_task"), form.data)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Executive shared task")
        self.assertEqual(task.assignments.count(), 2)
        self.assertEqual(
            task.assignments.get(is_group_leader=True).assigned_to,
            self.dpss,
        )

    def test_reassignment_transfers_group_leadership(self):
        now = timezone.now()
        task = Task.objects.create(
            title="Returned shared task",
            created_by=self.ps,
            department=self.hed,
            status="RETURNED",
            start_date=now,
            due_date=now + timedelta(days=2),
        )
        TaskAssignment.objects.create(
            task=task,
            assigned_to=self.dpse,
            assigned_by=self.ps,
            status="RETURNED",
        )
        returned_leader = TaskAssignment.objects.create(
            task=task,
            assigned_to=self.dpss,
            assigned_by=self.ps,
            status="RETURNED",
            is_group_leader=True,
        )

        self.client.force_login(self.ps)
        response = self.client.post(
            reverse("reassign_returned_task", args=[task.pk]),
            {"assigned_to": self.hed_director.pk},
        )
        self.assertEqual(response.status_code, 302)
        returned_leader.refresh_from_db()
        self.assertFalse(returned_leader.is_group_leader)
        self.assertTrue(
            task.assignments.get(assigned_to=self.hed_director).is_group_leader
        )

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


class StaffTaskProposalTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            code="TEST", name="Test Division"
        )
        self.unit = DepartmentUnit.objects.create(
            department=self.department, code="TESTU", name="Test Unit"
        )
        self.staff = self._user("task-proposer", "REQUESTER")
        self.head = self._user("task-head", "HEAD_OF_UNIT")
        self.director = self._user("task-director", "DIRECTOR", unit=None)
        self.outside_department = Department.objects.create(
            code="OTHER", name="Other Division"
        )
        self.outside_director = self._user(
            "outside-director", "DIRECTOR", department=self.outside_department,
            unit=None,
        )
        self.staff.profile.head_of_unit = self.head
        self.staff.profile.save(update_fields=["head_of_unit"])

    def _user(self, username, role, department=None, unit="default"):
        user = User.objects.create_user(username=username, password="safe-pass")
        user.profile.role = role
        user.profile.department = department or self.department
        user.profile.department_unit = self.unit if unit == "default" else unit
        user.profile.save()
        return user

    def _proposal_data(self, approver):
        now = timezone.localtime().replace(second=0, microsecond=0)
        return {
            "title": "Prepare monthly technical note",
            "description": "Compile and submit the unit technical note.",
            "priority": "MEDIUM",
            "start_date": now.strftime("%Y-%m-%dT%H:%M"),
            "due_date": (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
            "approver": approver.pk,
        }

    def test_approver_choices_are_limited_to_reporting_hierarchy(self):
        ids = set(
            TaskProposalForm(user=self.staff).fields["approver"].queryset
            .values_list("pk", flat=True)
        )
        self.assertIn(self.head.pk, ids)
        self.assertIn(self.director.pk, ids)
        self.assertNotIn(self.outside_director.pk, ids)

    def test_staff_proposal_approval_transfers_ownership_and_assigns_creator(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("create_task"), self._proposal_data(self.head))
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Prepare monthly technical note")
        self.assertEqual(task.created_by, self.staff)
        self.assertEqual(task.proposed_by, self.staff)
        self.assertEqual(task.approver, self.head)
        self.assertEqual(task.approval_status, "PENDING")
        self.assertFalse(task.assignments.exists())

        self.client.force_login(self.head)
        response = self.client.post(
            reverse("decide_task_proposal", args=[task.pk]),
            {"action": "approve", "decision_note": "Approved for implementation."},
        )
        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.created_by, self.head)
        self.assertEqual(task.approval_status, "APPROVED")
        assignment = task.assignments.get()
        self.assertEqual(assignment.assigned_to, self.staff)
        self.assertEqual(assignment.assigned_by, self.head)

    def test_unselected_leader_cannot_approve_proposal(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("create_task"), self._proposal_data(self.head))
        task = Task.objects.get(title="Prepare monthly technical note")
        self.client.force_login(self.director)
        response = self.client.post(
            reverse("decide_task_proposal", args=[task.pk]), {"action": "approve"}
        )
        self.assertEqual(response.status_code, 403)
        task.refresh_from_db()
        self.assertEqual(task.approval_status, "PENDING")
        self.assertFalse(task.assignments.exists())


class CrossDepartmentTaskRequestTests(TestCase):
    def setUp(self):
        self.department_a = Department.objects.create(code="DEPA", name="Department A")
        self.department_b = Department.objects.create(code="DEPB", name="Department B")
        self.unit_b = DepartmentUnit.objects.create(
            department=self.department_b, code="UNITB", name="Unit B"
        )
        self.director_a = self._user("director-a", "DIRECTOR", self.department_a)
        self.director_b = self._user("director-b", "DIRECTOR", self.department_b)
        self.staff_b1 = self._user("staff-b1", "REQUESTER", self.department_b, self.unit_b)
        self.staff_b2 = self._user("staff-b2", "REQUESTER", self.department_b, self.unit_b)
        self.staff_a = self._user("staff-a", "REQUESTER", self.department_a)
        self.fau = Department.objects.create(
            code="FAU", name="Finance and Accounting Unit"
        )
        self.fau_head = self._user(
            "fau-head", "HEAD_OF_UNIT", self.fau
        )
        self.other_department = Department.objects.create(
            code="OTHER", name="Other Department"
        )
        self.other_head = self._user(
            "other-head", "HEAD_OF_UNIT", self.other_department
        )

    def _user(self, username, role, department, unit=None):
        user = User.objects.create_user(username=username, password="safe-pass")
        user.profile.role = role
        user.profile.department = department
        user.profile.department_unit = unit
        user.profile.save()
        return user

    def _create_request(self):
        now = timezone.localtime().replace(second=0, microsecond=0)
        self.client.force_login(self.director_a)
        response = self.client.post(reverse("create_cross_department_request"), {
            "title": "Joint technical review",
            "description": "Provide two technical officers.",
            "priority": "HIGH",
            "start_date": now.strftime("%Y-%m-%dT%H:%M"),
            "due_date": (now + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M"),
            "providing_director": self.director_b.pk,
            "requesting_staff": [self.staff_a.pk],
            "group_leader": self.staff_a.pk,
        })
        self.assertEqual(response.status_code, 302)
        return CrossDepartmentTaskRequest.objects.get()

    def test_request_routes_to_selected_other_department_director(self):
        cross_request = self._create_request()
        self.assertEqual(cross_request.requesting_department, self.department_a)
        self.assertEqual(cross_request.providing_department, self.department_b)
        self.assertEqual(cross_request.providing_director, self.director_b)
        self.assertEqual(cross_request.status, "PENDING")
        self.assertIsNone(cross_request.task)

    def test_ps_direct_head_is_available_but_other_department_head_is_not(self):
        queryset = CrossDepartmentTaskRequestForm(
            user=self.director_a
        ).fields["providing_director"].queryset
        ids = set(queryset.values_list("pk", flat=True))
        self.assertIn(self.director_b.pk, ids)
        self.assertIn(self.fau_head.pk, ids)
        self.assertNotIn(self.other_head.pk, ids)

    def test_team_leader_choices_include_only_checked_requesting_staff(self):
        second_staff = self._user(
            "staff-a-2", "REQUESTER", self.department_a
        )
        unbound_form = CrossDepartmentTaskRequestForm(user=self.director_a)
        self.assertFalse(unbound_form.fields["group_leader"].queryset.exists())

        bound_form = CrossDepartmentTaskRequestForm(
            data={
                "requesting_staff": [self.staff_a.pk],
                "group_leader": self.staff_a.pk,
            },
            user=self.director_a,
        )
        leader_ids = set(
            bound_form.fields["group_leader"].queryset.values_list(
                "pk", flat=True
            )
        )
        self.assertEqual(leader_ids, {self.staff_a.pk})
        self.assertNotIn(second_staff.pk, leader_ids)

    def test_cross_department_request_page_filters_leader_choices_live(self):
        self.client.force_login(self.director_a)
        response = self.client.get(reverse("create_cross_department_request"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "syncTeamLeaderChoices")
        self.assertContains(response, 'input[name="requesting_staff"]')
        self.assertContains(response, "datePickerDismissTarget")
        self.assertContains(response, "closeDateTimePicker")
        self.assertContains(response, 'field.addEventListener("input"')

    def test_task_datetime_widgets_close_after_selection(self):
        forms = [
            TaskCreateForm(user=self.director_a),
            CrossDepartmentTaskRequestForm(user=self.director_a),
        ]
        for form in forms:
            self.assertEqual(
                form.fields["start_date"].widget.attrs["onchange"],
                "this.blur()",
            )
            self.assertEqual(
                form.fields["due_date"].widget.attrs["onchange"],
                "this.blur()",
            )

    def test_providing_director_selects_only_own_staff_and_approves(self):
        cross_request = self._create_request()
        self.client.force_login(self.director_b)
        response = self.client.post(
            reverse("decide_cross_department_request", args=[cross_request.pk]),
            {
                "action": "approve",
                "assigned_users": [self.staff_b1.pk, self.staff_b2.pk],
                "decision_note": "Staff are available.",
            },
        )
        self.assertEqual(response.status_code, 302)
        cross_request.refresh_from_db()
        self.assertEqual(cross_request.status, "APPROVED")
        self.assertIsNotNone(cross_request.task)
        self.assertEqual(cross_request.task.created_by, self.director_a)
        self.assertEqual(cross_request.task.department, self.department_a)
        self.assertEqual(
            set(cross_request.task.assignments.values_list("assigned_to_id", flat=True)),
            {self.staff_a.pk, self.staff_b1.pk, self.staff_b2.pk},
        )
        self.assertEqual(
            cross_request.task.assignments.get(is_group_leader=True).assigned_to,
            self.staff_a,
        )

        director_a_tasks, _ = _get_visible_task_scope(self.director_a)
        director_b_tasks, _ = _get_visible_task_scope(self.director_b)
        self.assertIn(cross_request.task, director_a_tasks)
        self.assertIn(cross_request.task, director_b_tasks)

        self.client.force_login(self.director_a)
        response_a = self.client.get(reverse("task_dashboard"))
        performers_a = {
            row["user_id"] for row in response_a.context["top_performers"]
        }
        self.assertIn(self.staff_a.pk, performers_a)
        self.assertNotIn(self.staff_b1.pk, performers_a)

        self.client.force_login(self.director_b)
        response_b = self.client.get(reverse("task_dashboard"))
        performers_b = {
            row["user_id"] for row in response_b.context["top_performers"]
        }
        self.assertIn(self.staff_b1.pk, performers_b)
        self.assertNotIn(self.staff_a.pk, performers_b)

    def test_providing_director_cannot_assign_requesting_department_staff(self):
        cross_request = self._create_request()
        self.client.force_login(self.director_b)
        response = self.client.post(
            reverse("decide_cross_department_request", args=[cross_request.pk]),
            {"action": "approve", "assigned_users": [self.staff_a.pk]},
        )
        self.assertEqual(response.status_code, 200)
        cross_request.refresh_from_db()
        self.assertEqual(cross_request.status, "PENDING")
        self.assertIsNone(cross_request.task)

    def test_requesting_director_cannot_approve_own_request(self):
        cross_request = self._create_request()
        self.client.force_login(self.director_a)
        response = self.client.post(
            reverse("decide_cross_department_request", args=[cross_request.pk]),
            {"action": "reject"},
        )
        self.assertEqual(response.status_code, 403)
