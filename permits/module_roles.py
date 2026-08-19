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


def module_roles(user, module):
    if not user or not getattr(user, "is_authenticated", False):
        return set()
    return set(
        ModuleRoleAssignment.objects.filter(
            user=user,
            module=module,
            is_active=True,
        )
        .values_list("role_code", flat=True)
    )


def module_role(user, module, priority=()):
    roles = module_roles(user, module)
    for role_code in priority:
        if role_code in roles:
            return role_code
    return sorted(roles)[0] if roles else ""


def set_module_roles(user, module, role_codes, department):
    normalized = {
        role_code.strip().upper()
        for role_code in (role_codes or [])
        if role_code and role_code.strip()
    }
    if normalized and department is None:
        raise ValueError("A department is required for additional module roles.")
    ModuleRoleAssignment.objects.filter(user=user, module=module).exclude(
        role_code__in=normalized
    ).delete()
    for role_code in normalized:
        ModuleRoleAssignment.objects.update_or_create(
            user=user,
            module=module,
            role_code=role_code,
            defaults={"department": department, "is_active": True},
        )
