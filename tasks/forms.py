from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
from permits.models import UserProfile, Department, DepartmentUnit
from .models import Task, TaskAssignment, TaskUpdate
from .access import (
    EXECUTIVE_TASK_ROLES,
    executive_assignee_queryset,
    executive_department_codes,
    profile_role_code,
    task_approver_queryset,
)


class UserMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return full_name if full_name else obj.username


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return full_name if full_name else obj.username


class TaskProposalForm(forms.ModelForm):
    approver = UserChoiceField(
        queryset=User.objects.none(),
        label="Leader to approve this task",
        empty_label="Select Head of Unit, Assistant Director or Director",
    )

    class Meta:
        model = Task
        fields = [
            "title", "description", "priority", "start_date", "due_date",
            "attachment", "approver",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "start_date": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "due_date": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["due_date"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["approver"].queryset = task_approver_queryset(self.user)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        due = cleaned.get("due_date")
        approver = cleaned.get("approver")
        if start and due and due < start:
            self.add_error("due_date", "Due date cannot be before start date.")
        if approver and not task_approver_queryset(self.user).filter(pk=approver.pk).exists():
            self.add_error("approver", "Select a leader within your reporting hierarchy.")
        return cleaned


class TaskCreateForm(forms.ModelForm):
    ASSIGNEE_SCOPE_CHOICES = [
    ("UNIT", "Selected Department Unit Staff"),
    ("OTHER", "Other Eligible Staff within the Department"),
    ]

    assigned_users = UserMultipleChoiceField(
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Assign To"
    )

    group_leader = UserChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Group Leader",
        empty_label="Select the group leader",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    assignee_scope = forms.ChoiceField(
        choices=ASSIGNEE_SCOPE_CHOICES,
        required=False,
        initial="UNIT",
        label="Staff Source",
        widget=forms.Select(attrs={"class": "form-control"})
    )

    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "department",
            "department_unit",
            "priority",
            "start_date",
            "due_date",
            "attachment",
        ]

        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Enter task title"
            }),

            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Enter task description"
            }),

            "department": forms.Select(attrs={
                "class": "form-control",
                "id": "id_department",
            }),

            "department_unit": forms.Select(attrs={
                "class": "form-control",
                "id": "id_department_unit",
            }),

            "priority": forms.Select(attrs={
                "class": "form-control"
            }),

            "start_date": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "form-control",
                    "id": "id_start_date"
                },
                format="%Y-%m-%dT%H:%M"
            ),

            "due_date": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "form-control",
                    "id": "id_due_date"
                },
                format="%Y-%m-%dT%H:%M"
            ),

            "attachment": forms.ClearableFileInput(attrs={
                "class": "form-control"
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        kwargs.pop("selected_unit", None)
        assignee_scope = kwargs.pop("assignee_scope", None)
        super().__init__(*args, **kwargs)

        self.fields["start_date"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["due_date"].input_formats = ["%Y-%m-%dT%H:%M"]

        self.fields["department"].queryset = Department.objects.filter(
            is_active=True
        ).order_by("code")

        self.fields["department"].label = "Responsible Department"
        self.fields["department_unit"].label = "Responsible Department Unit"
        self.fields["department_unit"].required = False
        self.fields["department_unit"].queryset = DepartmentUnit.objects.none()

        selected_department_id = None
        selected_department_unit_id = None

        if self.data:
            selected_department_id = self.data.get("department")
            selected_department_unit_id = self.data.get("department_unit")
            assignee_scope = self.data.get("assignee_scope") or assignee_scope
        elif self.instance and self.instance.pk:
            selected_department_id = self.instance.department_id
            selected_department_unit_id = self.instance.department_unit_id

        if not assignee_scope:
            assignee_scope = "UNIT"

        self.initial["assignee_scope"] = assignee_scope

        if not self.user:
            if selected_department_id:
                try:
                    selected_department_id = int(selected_department_id)
                    self.fields["department_unit"].queryset = DepartmentUnit.objects.filter(
                        department_id=selected_department_id,
                        is_active=True
                    ).order_by("code")
                except (TypeError, ValueError):
                    pass
            return

        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        role = profile_role_code(profile)

        if role in EXECUTIVE_TASK_ROLES:
            allowed_codes = executive_department_codes(role)
            departments = Department.objects.filter(is_active=True)
            if allowed_codes is not None:
                departments = departments.filter(code__in=allowed_codes)
            self.fields["department"].queryset = departments.order_by("code")
            self.fields["department"].required = False

            if selected_department_id:
                try:
                    selected_department_id = int(selected_department_id)
                    if departments.filter(pk=selected_department_id).exists():
                        self.fields["department_unit"].queryset = DepartmentUnit.objects.filter(
                            department_id=selected_department_id, is_active=True
                        ).order_by("code")
                except (TypeError, ValueError):
                    selected_department_id = None

            users = executive_assignee_queryset(role).exclude(pk=self.user.pk)
            if selected_department_id:
                # Keep department-less deputies available to the PS while
                # narrowing organizational leaders to the chosen department.
                users = users.filter(
                    Q(profile__department_id=selected_department_id)
                    | Q(profile__department__isnull=True)
                )
            self.fields["assigned_users"].queryset = users

        elif self.user.is_superuser or role == "ADMIN":
            self.fields["department"].required = True

            if selected_department_id:
                try:
                    selected_department_id = int(selected_department_id)
                    self.initial["department"] = selected_department_id
                    self.fields["department_unit"].queryset = DepartmentUnit.objects.filter(
                        department_id=selected_department_id,
                        is_active=True
                    ).order_by("code")
                except (TypeError, ValueError):
                    selected_department_id = None

            if selected_department_unit_id:
                try:
                    selected_department_unit_id = int(selected_department_unit_id)
                    self.initial["department_unit"] = selected_department_unit_id
                except (TypeError, ValueError):
                    selected_department_unit_id = None

            if assignee_scope == "OTHER":
                if selected_department_id:
                    users = User.objects.filter(
                        is_active=True,
                        profile__department_id=selected_department_id
                    )
            else:
                users = User.objects.none()

            self.fields["assigned_users"].queryset = users.select_related(
                "profile",
                "profile__department",
                "profile__department_unit",
            ).order_by("first_name", "last_name", "username")

        elif role in ["DIRECTOR", "ADRD", "ADSTI"]:
            profile_department = profile.department

            self.fields["department"].initial = profile_department
            self.fields["department"].widget = forms.HiddenInput()
            self.fields["department"].required = False

            if profile_department and profile_department.has_units:
                self.fields["department_unit"].queryset = DepartmentUnit.objects.filter(
                    department=profile_department,
                    is_active=True
                ).order_by("code")
                self.fields["department_unit"].required = True

                if selected_department_unit_id:
                    try:
                        selected_department_unit_id = int(selected_department_unit_id)
                        self.initial["department_unit"] = selected_department_unit_id
                    except (TypeError, ValueError):
                        selected_department_unit_id = None
            else:
                self.fields["department_unit"].queryset = DepartmentUnit.objects.none()
                self.fields["department_unit"].required = False
                self.fields["department_unit"].widget = forms.HiddenInput()
                self.initial["department_unit"] = None

            users = User.objects.filter(
                is_active=True,
                profile__department=profile_department
            )

            if assignee_scope == "UNIT" and selected_department_unit_id:
                users = users.filter(
                    profile__department_unit_id=selected_department_unit_id
                )

            self.fields["assigned_users"].queryset = users.select_related(
                "profile",
                "profile__department",
                "profile__department_unit",
            ).order_by("first_name", "last_name", "username")

        elif role == "HEAD_OF_UNIT":
            self.fields["department"].initial = profile.department
            self.fields["department"].widget = forms.HiddenInput()
            self.fields["department"].required = False

            self.fields["department_unit"].initial = profile.department_unit
            self.fields["department_unit"].widget = forms.HiddenInput()
            self.fields["department_unit"].required = False

            self.fields["assignee_scope"].initial = "UNIT"
            self.fields["assignee_scope"].widget = forms.HiddenInput()

            users = User.objects.filter(
                is_active=True,
                profile__department=profile.department
            )

            if profile.department_unit:
                users = users.filter(
                    profile__department_unit=profile.department_unit
                )

            self.fields["assigned_users"].queryset = users.select_related(
                "profile",
                "profile__department",
                "profile__department_unit",
            ).order_by("first_name", "last_name", "username")

        else:
            self.fields["department"].initial = profile.department
            self.fields["department"].widget = forms.HiddenInput()
            self.fields["department"].required = False

            self.fields["department_unit"].initial = profile.department_unit
            self.fields["department_unit"].widget = forms.HiddenInput()
            self.fields["department_unit"].required = False

            self.fields["assignee_scope"].initial = "UNIT"
            self.fields["assignee_scope"].widget = forms.HiddenInput()

            self.fields["assigned_users"].queryset = User.objects.filter(
                pk=self.user.pk,
                is_active=True
            )

        self.fields["group_leader"].queryset = self.fields[
            "assigned_users"
        ].queryset

    def clean(self):
        cleaned_data = super().clean()

        start = cleaned_data.get("start_date")
        due = cleaned_data.get("due_date")
        department = cleaned_data.get("department")
        department_unit = cleaned_data.get("department_unit")
        assignee_scope = cleaned_data.get("assignee_scope") or "UNIT"
        assigned_users = cleaned_data.get("assigned_users")
        group_leader = cleaned_data.get("group_leader")

        if start and due and due < start:
            raise forms.ValidationError(
                "Due date cannot be before start date."
            )

        selected_user_ids = {user.pk for user in assigned_users or []}
        if len(selected_user_ids) > 1 and not group_leader:
            self.add_error(
                "group_leader",
                "Select one of the assignees as group leader for a shared task.",
            )
        elif group_leader and group_leader.pk not in selected_user_ids:
            self.add_error(
                "group_leader",
                "The group leader must also be selected as an assignee.",
            )
        elif len(selected_user_ids) <= 1:
            cleaned_data["group_leader"] = None

        if not self.user:
            return cleaned_data

        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        role = profile_role_code(profile)

        if role in EXECUTIVE_TASK_ROLES:
            allowed_codes = executive_department_codes(role)
            if department and allowed_codes is not None and department.code not in allowed_codes:
                raise forms.ValidationError(
                    "The selected department is outside your executive responsibility."
                )
            allowed_ids = set(
                executive_assignee_queryset(role).exclude(pk=self.user.pk)
                .values_list("pk", flat=True)
            )
            selected_ids = {user.pk for user in assigned_users or []}
            if not selected_ids.issubset(allowed_ids):
                raise forms.ValidationError(
                    "One or more selected officials are outside your task-assignment responsibility."
                )

        elif self.user.is_superuser or role == "ADMIN":
            if not department:
                raise forms.ValidationError(
                    "Please select the responsible department."
                )

        elif role in ["DIRECTOR", "ADRD", "ADSTI"]:
            department = profile.department
            cleaned_data["department"] = department

            if not department:
                raise forms.ValidationError(
                    "Your user profile is not linked to a department. Please contact the System Administrator."
                )

            if department.has_units:
                if not department_unit:
                    raise forms.ValidationError(
                        "Please select the responsible department unit."
                    )
            else:
                department_unit = None
                cleaned_data["department_unit"] = None

        elif role == "HEAD_OF_UNIT":
            department = profile.department
            department_unit = profile.department_unit
            cleaned_data["department"] = department
            cleaned_data["department_unit"] = department_unit

            if not department:
                raise forms.ValidationError(
                    "Your user profile is not linked to a department."
                )

        else:
            department = profile.department
            department_unit = profile.department_unit
            cleaned_data["department"] = department
            cleaned_data["department_unit"] = department_unit

            if not department:
                raise forms.ValidationError(
                    "Your user profile is not linked to a department."
                )

        if department_unit and (not department or department_unit.department_id != department.id):
            raise forms.ValidationError(
                "The selected department unit does not belong to the responsible department."
            )

        if role not in EXECUTIVE_TASK_ROLES and assignee_scope == "UNIT" and assigned_users:
            invalid_users = []

            for assigned_user in assigned_users:
                assigned_profile = getattr(assigned_user, "profile", None)

                if not assigned_profile:
                    invalid_users.append(assigned_user)
                    continue

                if assigned_profile.department_id != department.id:
                    invalid_users.append(assigned_user)
                    continue

                if department_unit and assigned_profile.department_unit_id != department_unit.id:
                    invalid_users.append(assigned_user)

            if invalid_users:
                raise forms.ValidationError(
                    "All selected staff must belong to the responsible department or selected department unit."
                )

        if (
            role in ["DIRECTOR", "ADRD", "ADSTI"]
            and assignee_scope == "OTHER"
            and assigned_users
        ):
            invalid_users = [
                user
                for user in assigned_users
                if getattr(getattr(user, "profile", None), "department_id", None)
                != department.id
            ]

            if invalid_users:
                raise forms.ValidationError(
                    "Director-level users can assign tasks only within their own department."
                )

        return cleaned_data


class TaskAssignmentForm(forms.ModelForm):
    assigned_to = UserChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("first_name", "last_name", "username"),
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Assigned To"
    )

    class Meta:
        model = TaskAssignment
        fields = ["assigned_to", "status", "progress_percent"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control"}),
            "progress_percent": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
                "max": 100
            }),
        }

    def clean_progress_percent(self):
        value = self.cleaned_data.get("progress_percent")

        if value is None:
            return 0

        if value < 0 or value > 100:
            raise forms.ValidationError("Progress must be between 0 and 100.")

        return value


class TaskUpdateForm(forms.ModelForm):
    class Meta:
        model = TaskUpdate
        fields = [
            "comment",
            "progress_percent",
            "attachment",
        ]
        widgets = {
            "comment": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Write update or progress..."
            }),
            "progress_percent": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
                "max": 100,
                "placeholder": "Enter progress percentage"
            }),
            "attachment": forms.ClearableFileInput(attrs={
                "class": "form-control"
            }),
        }

    def clean_progress_percent(self):
        value = self.cleaned_data.get("progress_percent")

        if value is None:
            return 0

        if value < 0 or value > 100:
            raise forms.ValidationError("Progress must be between 0 and 100.")

        return value

    def clean(self):
        cleaned_data = super().clean()
        comment = cleaned_data.get("comment")
        progress_percent = cleaned_data.get("progress_percent")
        attachment = cleaned_data.get("attachment")

        if not comment and progress_percent in [None, 0] and not attachment:
            raise forms.ValidationError(
                "Please provide at least a comment, progress update, or attachment."
            )

        return cleaned_data


class TaskManagementNoteForm(forms.Form):
    management_note = forms.CharField(
        required=True,
        label="Reason / Comment",
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "placeholder": "Enter reason for putting this task on hold or cancelling it..."
        })
    )

    def clean_management_note(self):
        value = self.cleaned_data.get("management_note", "").strip()

        if not value:
            raise forms.ValidationError("Reason / comment is required.")

        return value


class TaskReturnForm(forms.Form):
    return_reason = forms.CharField(
        required=True,
        label="Reason for Returning Task",
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "placeholder": "Enter the reason for returning this task to the creator..."
        })
    )

    def clean_return_reason(self):
        value = self.cleaned_data.get("return_reason", "").strip()

        if not value:
            raise forms.ValidationError("Return reason is required.")

        return value


class TaskReassignForm(forms.Form):
    assigned_to = UserChoiceField(
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Re-Assign To"
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.task = kwargs.pop("task", None)
        super().__init__(*args, **kwargs)

        queryset = User.objects.filter(is_active=True)

        if self.user:
            profile, _ = UserProfile.objects.get_or_create(user=self.user)
            role = profile_role_code(profile)
            if role in EXECUTIVE_TASK_ROLES:
                queryset = executive_assignee_queryset(role).exclude(pk=self.user.pk)

            elif self.user.is_superuser or role in ["ADMIN", "DIRECTOR", "ADRD", "ADSTI"]:
                queryset = queryset.order_by("first_name", "last_name", "username")

            elif role == "HEAD_OF_UNIT":
                queryset = queryset.filter(
                    profile__department_unit_id=profile.department_unit_id
                ).order_by("first_name", "last_name", "username")

            else:
                queryset = User.objects.filter(pk=self.user.pk)

        if self.task:
            already_assigned_ids = self.task.assignments.values_list("assigned_to_id", flat=True)
            queryset = queryset.exclude(pk__in=already_assigned_ids)

        self.fields["assigned_to"].queryset = queryset

    def clean_assigned_to(self):
        user = self.cleaned_data.get("assigned_to")

        if not user:
            raise forms.ValidationError("Please select a staff member.")

        return user
