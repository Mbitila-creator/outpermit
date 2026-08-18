from .models import ModuleRoleAssignment


EVENT_ROLE_CHOICES = (
    ("", "No additional Event Management role"),
    ("EVENT_ADMIN", "Event Administrator"),
    ("REGISTRATION_OFFICER", "Event Registration Officer"),
    ("ATTENDANCE_OFFICER", "Event Attendance Officer"),
    ("REPORT_OFFICER", "Event Reports Officer"),
)

FINANCE_ROLE_CHOICES = (
    ("", "No additional Financial Management role"),
    ("DIVISION_BUDGET_OFFICER", "Division Budget Officer"),
    ("ACCOUNTANT", "Accountant"),
)

TASK_ROLE_CHOICES = (
    ("", "No additional Task Management role"),
    ("DIRECTOR", "Task Director"),
    ("ASSISTANT_DIRECTOR", "Task Assistant Director"),
    ("HEAD_OF_UNIT", "Task Head of Unit"),
)


def module_role(user, module):
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    return (
        ModuleRoleAssignment.objects.filter(
            user=user,
            module=module,
            is_active=True,
        )
        .values_list("role_code", flat=True)
        .first()
        or ""
    )


def set_module_role(user, module, role_code, department):
    role_code = (role_code or "").strip().upper()
    if not role_code:
        ModuleRoleAssignment.objects.filter(user=user, module=module).delete()
        return
    if department is None:
        raise ValueError("A department is required for additional module roles.")
    ModuleRoleAssignment.objects.update_or_create(
        user=user,
        module=module,
        defaults={
            "role_code": role_code,
            "department": department,
            "is_active": True,
        },
    )
