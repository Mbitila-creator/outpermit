from django.contrib.auth.models import User
from django.db.models import Q


EXECUTIVE_TASK_ROLES = {
    "PERMANENT_SECRETARY",
    "DPS_HES",
    "DPS_BE",
    "COMMISSIONER_EDUCATION",
}

EXECUTIVE_DEPARTMENT_SCOPES = {
    "DPS_HES": {"HED", "DSTI", "DTVET"},
    "DPS_BE": {"COE", "SQAD"},
    "COMMISSIONER_EDUCATION": {"COE"},
}

MANAGED_LEADERSHIP_ROLES = {
    "DIRECTOR",
    "ASSISTANT_DIRECTOR",
    "HEAD_OF_UNIT",
}

DSTI_LEGACY_ASSISTANT_USERNAMES = {"adsti", "adrd"}


def _leadership_query():
    """Recognize primary, approval and Task-module leadership roles."""
    return (
        Q(profile__approval_role__code__in=MANAGED_LEADERSHIP_ROLES)
        | Q(profile__role__in=MANAGED_LEADERSHIP_ROLES)
        | Q(
            module_role_assignments__module="TASK",
            module_role_assignments__role_code__in=MANAGED_LEADERSHIP_ROLES,
            module_role_assignments__is_active=True,
        )
        # Compatibility for the established DSTI-wide Assistant Director
        # accounts; their existing organizational structure is untouched.
        | Q(
            profile__department__code="DSTI",
            username__in=DSTI_LEGACY_ASSISTANT_USERNAMES,
        )
    )


def profile_role_code(profile):
    approval_role = getattr(profile, "approval_role", None)
    code = getattr(approval_role, "code", None) or getattr(profile, "role", "")
    return str(code or "").strip().upper()


def executive_department_codes(role_code):
    """None means ministry-wide access; an empty set means no executive scope."""
    role_code = str(role_code or "").strip().upper()
    if role_code == "PERMANENT_SECRETARY":
        return None
    return EXECUTIVE_DEPARTMENT_SCOPES.get(role_code, set())


def executive_assignee_queryset(role_code):
    role_code = str(role_code or "").strip().upper()
    users = User.objects.filter(is_active=True).filter(_leadership_query())

    if role_code == "PERMANENT_SECRETARY":
        users = User.objects.filter(is_active=True).filter(
            _leadership_query()
            | Q(profile__approval_role__code__in=(
                MANAGED_LEADERSHIP_ROLES
                | {"DPS_HES", "DPS_BE", "COMMISSIONER_EDUCATION"}
            ))
            | Q(profile__role__in=(
                MANAGED_LEADERSHIP_ROLES
                | {"DPS_HES", "DPS_BE", "COMMISSIONER_EDUCATION"}
            ))
        )
    else:
        department_codes = executive_department_codes(role_code)
        users = users.filter(
            Q(profile__department__code__in=department_codes)
            | Q(
                module_role_assignments__module="TASK",
                module_role_assignments__department__code__in=department_codes,
                module_role_assignments__is_active=True,
            )
        )
        if role_code == "DPS_BE":
            users = users | User.objects.filter(
                is_active=True,
                profile__approval_role__code="COMMISSIONER_EDUCATION",
            )

    return users.select_related(
        "profile", "profile__approval_role", "profile__department",
        "profile__department_unit",
    ).distinct().order_by("first_name", "last_name", "username")
