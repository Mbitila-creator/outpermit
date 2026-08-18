from django import forms
from django.forms import inlineformset_factory
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from .models import (
    Department,
    DepartmentUnit,
    ExternalWorkRequest,
    GroupMember,
    UserProfile,
)


def _blocking_statuses():
    return [
        "PENDING_HOU",
        "PENDING_DIRECTOR",
        "RETURNED_HOU",
        "RETURNED_DIRECTOR",
        "APPROVED",
    ]


def _get_blocking_request_for_user(user, exclude_pk=None):
    blocking = _blocking_statuses()

    qs = ExternalWorkRequest.objects.filter(
        Q(requester=user, status__in=blocking) |
        Q(group_leader=user, status__in=blocking) |
        Q(members__member_user=user, status__in=blocking)
    ).distinct()

    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    return qs.order_by("-updated_at", "-created_at").first()


def _get_blocking_request_for_member(member_user, exclude_pk=None):
    blocking = _blocking_statuses()

    qs = ExternalWorkRequest.objects.filter(
        Q(requester=member_user, status__in=blocking) |
        Q(group_leader=member_user, status__in=blocking) |
        Q(members__member_user=member_user, status__in=blocking)
    ).distinct()

    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    return qs.order_by("-updated_at", "-created_at").first()


def _build_blocking_message_for_person(person_name, blocking_request):
    status_messages = {
        "PENDING_HOU": "still under Head of Unit review",
        "PENDING_DIRECTOR": "still under Director review",
        "RETURNED_HOU": "returned by Head of Unit and still needs action",
        "RETURNED_DIRECTOR": "returned by Director and still needs action",
        "APPROVED": "approved but not yet closed",
    }

    message = status_messages.get(blocking_request.status, "still open")
    ref = blocking_request.reference_no or "Unknown"

    return (
        f"{person_name} cannot be included because request "
        f"{ref} is {message}. "
        f"That request must be resolved or closed first."
    )


def _staff_queryset(user=None):
    qs = User.objects.filter(
        is_active=True
    ).exclude(
        profile__role__in=["ADMIN", "DIRECTOR"]
    ).select_related("profile")

    if user and hasattr(user, "profile") and user.profile.department:
        qs = qs.filter(profile__department=user.profile.department)

    return qs.order_by("first_name", "last_name", "username")


def _staff_label(obj):
    full_name = obj.get_full_name().strip() if obj.get_full_name() else ""
    employee_id = getattr(getattr(obj, "profile", None), "employee_id", "") or ""

    if full_name and employee_id:
        return f"{full_name} - {employee_id}"
    if full_name:
        return full_name
    if employee_id:
        return f"{obj.username} - {employee_id}"
    return obj.username


class ExternalWorkRequestForm(forms.ModelForm):
    REQUEST_TYPE_CHOICES = [
        ("INDIVIDUAL", "Individual"),
        ("GROUP", "Group"),
    ]

    request_type = forms.ChoiceField(
        choices=REQUEST_TYPE_CHOICES,
        initial="INDIVIDUAL"
    )

    group_leader = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Select Group Leader",
        label="Group Leader",
        widget=forms.Select(attrs={"id": "id_group_leader"})
    )

    acting_officer = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Select Acting Officer",
        label="Acting Officer",
        widget=forms.Select(attrs={"id": "id_acting_officer"})
    )

    class Meta:
        model = ExternalWorkRequest
        fields = [
            "requester_name",
            "requester_employee_id",
            "purpose",
            "destination",
            "start_time",
            "end_time",
            "group_leader",
            "group_leader_name",
            "group_leader_employee_id",
            "acting_officer",
            "acting_officer_name",
            "acting_officer_employee_id",
            "acting_officer_phone",
            "task_approval_file",
        ]

        widgets = {
            "requester_name": forms.TextInput(
                attrs={
                    "placeholder": "Enter requester full name",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
            "requester_employee_id": forms.TextInput(
                attrs={
                    "placeholder": "Enter requester employee ID",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
            "purpose": forms.TextInput(attrs={"placeholder": "Enter purpose"}),
            "destination": forms.TextInput(attrs={"placeholder": "Enter destination"}),
            "group_leader_name": forms.TextInput(
                attrs={
                    "placeholder": "Group leader name will auto-fill",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
            "group_leader_employee_id": forms.TextInput(
                attrs={
                    "placeholder": "Group leader employee ID will auto-fill",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
            "acting_officer_name": forms.TextInput(
                attrs={
                    "placeholder": "Acting officer full name will auto-fill",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
            "acting_officer_employee_id": forms.TextInput(
                attrs={
                    "placeholder": "Acting officer employee ID will auto-fill",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
            "acting_officer_phone": forms.TextInput(
                attrs={
                    "placeholder": "Acting officer phone number will auto-fill",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
            "start_time": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M"
            ),
            "end_time": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.fields["start_time"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["end_time"].input_formats = ["%Y-%m-%dT%H:%M"]

        staff_qs = _staff_queryset(self.user)

        self.fields["acting_officer"].queryset = staff_qs
        self.fields["group_leader"].queryset = staff_qs

        self.fields["acting_officer"].label_from_instance = _staff_label
        self.fields["group_leader"].label_from_instance = _staff_label

        if self.instance and self.instance.pk:
            self.fields["request_type"].initial = (
                "GROUP" if self.instance.is_group_request else "INDIVIDUAL"
            )

    def clean(self):
        cleaned = super().clean()

        rt = cleaned.get("request_type")
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        acting_officer = cleaned.get("acting_officer")
        group_leader = cleaned.get("group_leader")

        cleaned["is_group_request"] = (rt == "GROUP")

        if rt == "GROUP":
            cleaned["requester_name"] = ""
            cleaned["requester_employee_id"] = ""
        else:
            cleaned["group_leader"] = None
            cleaned["group_leader_name"] = ""
            cleaned["group_leader_employee_id"] = ""

        if start_time and end_time and end_time <= start_time:
            self.add_error("end_time", "End time must be later than start time.")

        if rt == "GROUP":
            if group_leader:
                leader_name = group_leader.get_full_name().strip() or group_leader.username
                leader_profile = getattr(group_leader, "profile", None)
                leader_employee_id = getattr(leader_profile, "employee_id", "") if leader_profile else ""

                cleaned["group_leader_name"] = leader_name
                cleaned["group_leader_employee_id"] = leader_employee_id or ""

                current_pk = self.instance.pk if self.instance and self.instance.pk else None
                leader_blocking = _get_blocking_request_for_member(group_leader, exclude_pk=current_pk)

                if leader_blocking:
                    self.add_error(
                        "group_leader",
                        _build_blocking_message_for_person(
                            f"Group leader '{leader_name}'",
                            leader_blocking
                        )
                    )
            else:
                cleaned["group_leader_name"] = ""
                cleaned["group_leader_employee_id"] = ""
        else:
            cleaned["group_leader_name"] = ""
            cleaned["group_leader_employee_id"] = ""

        if acting_officer:
            full_name = acting_officer.get_full_name().strip() or acting_officer.username
            profile = getattr(acting_officer, "profile", None)
            employee_id = getattr(profile, "employee_id", "") if profile else ""
            phone_number = getattr(profile, "phone_number", "") if profile else ""

            cleaned["acting_officer_name"] = full_name
            cleaned["acting_officer_employee_id"] = employee_id or ""
            cleaned["acting_officer_phone"] = phone_number or ""
        else:
            cleaned["acting_officer_name"] = ""
            cleaned["acting_officer_employee_id"] = ""
            cleaned["acting_officer_phone"] = ""

        if self.user:
            current_pk = self.instance.pk if self.instance and self.instance.pk else None
            blocking_request = _get_blocking_request_for_user(self.user, exclude_pk=current_pk)

            if blocking_request:
                status_messages = {
                    "PENDING_HOU": "still under Head of Unit review",
                    "PENDING_DIRECTOR": "still under Director review",
                    "RETURNED_HOU": "returned by Head of Unit and still needs action",
                    "RETURNED_DIRECTOR": "returned by Director and still needs action",
                    "APPROVED": "approved but not yet closed",
                }

                message = status_messages.get(blocking_request.status, "still open")

                raise forms.ValidationError(
                    f"You cannot submit this request because request "
                    f"{blocking_request.reference_no} is {message}. "
                    f"Please finish, re-submit, delete, or close that request first."
                )

        return cleaned


class GroupMemberForm(forms.ModelForm):
    member_user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Select Staff Member",
        label="Staff Member"
    )

    class Meta:
        model = GroupMember
        fields = ["member_user", "full_name", "employee_id"]
        widgets = {
            "full_name": forms.TextInput(
                attrs={
                    "placeholder": "Member full name will auto-fill",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
            "employee_id": forms.TextInput(
                attrs={
                    "placeholder": "Member employee ID will auto-fill",
                    "readonly": True,
                    "style": "background:#f8f9fa"
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["member_user"].queryset = _staff_queryset()
        self.fields["member_user"].label_from_instance = _staff_label

        self.fields["member_user"].required = False
        self.fields["full_name"].required = False
        self.fields["employee_id"].required = False

    def clean(self):
        cleaned_data = super().clean()

        if cleaned_data.get("DELETE"):
            return cleaned_data

        member_user = cleaned_data.get("member_user")
        full_name = (cleaned_data.get("full_name") or "").strip()
        employee_id = (cleaned_data.get("employee_id") or "").strip()

        if not member_user and not full_name and not employee_id:
            cleaned_data["member_user"] = None
            cleaned_data["full_name"] = ""
            cleaned_data["employee_id"] = ""
            return cleaned_data

        if member_user:
            profile = getattr(member_user, "profile", None)
            resolved_name = member_user.get_full_name().strip() or member_user.username
            cleaned_data["full_name"] = resolved_name
            cleaned_data["employee_id"] = getattr(profile, "employee_id", "") or ""

            parent_pk = None
            if self.instance and self.instance.pk and self.instance.request_id:
                parent_pk = self.instance.request_id
            elif hasattr(self, "_parent_instance") and self._parent_instance:
                parent_pk = self._parent_instance.pk

            member_blocking = _get_blocking_request_for_member(member_user, exclude_pk=parent_pk)

            if member_blocking:
                self.add_error(
                    "member_user",
                    _build_blocking_message_for_person(
                        f"'{resolved_name}'",
                        member_blocking
                    )
                )

            return cleaned_data

        if not full_name:
            self.add_error("full_name", "This field is required.")

        return cleaned_data


GroupMemberFormSet = inlineformset_factory(
    ExternalWorkRequest,
    GroupMember,
    form=GroupMemberForm,
    fields=["member_user", "full_name", "employee_id"],
    extra=5,
    can_delete=True
)


class ReportUploadForm(forms.ModelForm):
    class Meta:
        model = ExternalWorkRequest
        fields = ["report_file"]


class DirectorDecisionForm(forms.ModelForm):
    class Meta:
        model = ExternalWorkRequest
        fields = ["status", "director_comment"]
        widgets = {
            "status": forms.Select(),
            "director_comment": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "Write review, approval note, rejection reason, or return comments"
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["status"].choices = [
            ("APPROVED", "Approve Request"),
            ("RETURNED_DIRECTOR", "Return for Correction"),
            ("REJECTED_DIRECTOR", "Reject Request"),
        ]
        self.fields["status"].label = "Director Decision"
        self.fields["director_comment"].label = "Director Comment"

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")
        comment = (cleaned_data.get("director_comment") or "").strip()

        if status == "RETURNED_DIRECTOR" and not comment:
            self.add_error(
                "director_comment",
                "Director comment is required when returning a request."
            )

        if status == "REJECTED_DIRECTOR" and not comment:
            self.add_error(
                "director_comment",
                "Director comment is required when rejecting a request."
            )

        return cleaned_data


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            "placeholder": "Enter username",
            "autofocus": True
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Enter password"
        })
    )


class AdminUserCreateForm(forms.Form):
    ROLE_CHOICES = UserProfile.ROLE_CHOICES

    UNIT_CHOICES = [
        ("", "Select Legacy DSTI Unit"),
        ("KTIU", "Knowledge Translation and Impact Unit"),
        ("IMCU", "Infrastructure Management and Coordination Unit"),
        ("LSU", "Linkage and Support Unit"),
        ("RICU", "Regional and International Cooperation Unit"),
        ("DTSU", "Digital Technologies and STEM Unit"),
        ("CCU", "Crosscutting Unit"),
    ]

    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    employee_id = forms.CharField(max_length=50, required=False)
    check_number = forms.CharField(max_length=50, required=False)
    phone_number = forms.CharField(max_length=20, required=False)

    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True).order_by("code"),
        required=False,
        empty_label="Select Department"
    )

    department_unit = forms.ModelChoiceField(
        queryset=DepartmentUnit.objects.filter(is_active=True).select_related("department").order_by("department__code", "code"),
        required=False,
        empty_label="Select Unit"
    )

    unit_name = forms.ChoiceField(choices=UNIT_CHOICES, required=False)

    head_of_unit = forms.ModelChoiceField(
        queryset=User.objects.filter(profile__role="HEAD_OF_UNIT").order_by("first_name", "last_name", "username"),
        required=False,
        empty_label="Select Head of Unit"
    )

    password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    role = forms.ChoiceField(choices=ROLE_CHOICES)
    is_staff = forms.BooleanField(required=False)

    def clean_username(self):
        username = self.cleaned_data["username"]

        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Username already exists.")

        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        role = cleaned_data.get("role")
        department = cleaned_data.get("department")
        department_unit = cleaned_data.get("department_unit")
        unit_name = cleaned_data.get("unit_name")

        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")

        if role == "HEAD_OF_UNIT" and not department_unit and not unit_name:
            self.add_error(
                "department_unit",
                "Head of Unit must have a department unit assigned."
            )

        if department and department_unit and department_unit.department_id != department.id:
            self.add_error(
                "department_unit",
                "Selected unit does not belong to the selected department."
            )

        return cleaned_data


class AdminUserUpdateForm(forms.Form):
    ROLE_CHOICES = UserProfile.ROLE_CHOICES

    UNIT_CHOICES = [
        ("", "Select Legacy DSTI Unit"),
        ("KTIU", "Knowledge Translation and Impact Unit"),
        ("IMCU", "Infrastructure Management and Coordination Unit"),
        ("LSU", "Linkage and Support Unit"),
        ("RICU", "Regional and International Cooperation Unit"),
        ("DTSU", "Digital Technologies and STEM Unit"),
        ("CCU", "Crosscutting Unit"),
    ]

    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    employee_id = forms.CharField(max_length=50, required=False)
    check_number = forms.CharField(max_length=50, required=False)
    phone_number = forms.CharField(max_length=20, required=False)

    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True).order_by("code"),
        required=False,
        empty_label="Select Department"
    )

    department_unit = forms.ModelChoiceField(
        queryset=DepartmentUnit.objects.filter(is_active=True).select_related("department").order_by("department__code", "code"),
        required=False,
        empty_label="Select Unit"
    )

    unit_name = forms.ChoiceField(choices=UNIT_CHOICES, required=False)

    head_of_unit = forms.ModelChoiceField(
        queryset=User.objects.filter(profile__role="HEAD_OF_UNIT").order_by("first_name", "last_name", "username"),
        required=False,
        empty_label="Select Head of Unit"
    )

    role = forms.ChoiceField(choices=ROLE_CHOICES)
    is_staff = forms.BooleanField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        department = cleaned_data.get("department")
        department_unit = cleaned_data.get("department_unit")
        unit_name = cleaned_data.get("unit_name")

        if role == "HEAD_OF_UNIT" and not department_unit and not unit_name:
            self.add_error(
                "department_unit",
                "Head of Unit must have a department unit assigned."
            )

        if department and department_unit and department_unit.department_id != department.id:
            self.add_error(
                "department_unit",
                "Selected unit does not belong to the selected department."
            )

        return cleaned_data


class AdminPasswordResetForm(forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("new_password")
        p2 = cleaned_data.get("confirm_password")

        if p1 and p2 and p1 != p2:
            self.add_error("confirm_password", "Passwords do not match.")

        return cleaned_data


class UserPasswordChangeForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput)
    new_password = forms.CharField(widget=forms.PasswordInput)
    confirm_new_password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self):
        current_password = self.cleaned_data.get("current_password")

        if not self.user.check_password(current_password):
            raise forms.ValidationError("Current password is incorrect.")

        return current_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_new_password = cleaned_data.get("confirm_new_password")

        if new_password and confirm_new_password and new_password != confirm_new_password:
            self.add_error("confirm_new_password", "New passwords do not match.")

        return cleaned_data
