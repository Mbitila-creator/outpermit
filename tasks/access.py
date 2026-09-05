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


def task_approver_queryset(user):
    """Leaders in the staff member's actual reporting hierarchy."""
    profile = getattr(user, "profile", None)
    if not profile or not profile.department_id:
        return User.objects.none()

    department_id = profile.department_id
    department_unit_id = profile.department_unit_id
    requester_role = profile_role_code(profile)
    task_module_roles = set(user.module_role_assignments.filter(
        module="TASK", is_active=True
    ).values_list("role_code", flat=True))
    for candidate_role in ("DIRECTOR", "ASSISTANT_DIRECTOR", "HEAD_OF_UNIT"):
        if candidate_role in task_module_roles:
            requester_role = candidate_role
            break
    if requester_role in EXECUTIVE_TASK_ROLES or requester_role == "DIRECTOR":
        return User.objects.none()
    leaders = User.objects.filter(is_active=True).exclude(pk=user.pk).filter(
        _leadership_query(), profile__department_id=department_id
    )

    head_filter = Q(pk=getattr(profile, "head_of_unit_id", None))
    if department_unit_id:
        head_filter |= Q(
            profile__department_unit_id=department_unit_id,
            profile__role="HEAD_OF_UNIT",
        ) | Q(
            profile__department_unit_id=department_unit_id,
            profile__approval_role__code="HEAD_OF_UNIT",
        )

    assistant_filter = Q(profile__role="ASSISTANT_DIRECTOR") | Q(
        profile__approval_role__code="ASSISTANT_DIRECTOR"
    ) | Q(
        module_role_assignments__module="TASK",
        module_role_assignments__role_code="ASSISTANT_DIRECTOR",
        module_role_assignments__is_active=True,
    )
    if department_unit_id:
        assistant_filter &= (
            Q(profile__department_unit_id=department_unit_id)
            | Q(
                profile__department__code="DSTI",
                username__in=DSTI_LEGACY_ASSISTANT_USERNAMES,
            )
        )

    director_filter = Q(profile__role="DIRECTOR") | Q(
        profile__approval_role__code="DIRECTOR"
    ) | Q(
        module_role_assignments__module="TASK",
        module_role_assignments__role_code="DIRECTOR",
        module_role_assignments__is_active=True,
    )

    allowed_filter = director_filter
    if requester_role != "ASSISTANT_DIRECTOR":
        allowed_filter |= assistant_filter
    if requester_role not in {"HEAD_OF_UNIT", "ASSISTANT_DIRECTOR"}:
        allowed_filter |= head_filter

    return leaders.filter(
        allowed_filter
    ).select_related(
        "profile", "profile__approval_role", "profile__department_unit"
    ).distinct().order_by("first_name", "last_name", "username")


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

    users = users.select_related(
        "profile", "profile__approval_role", "profile__department",
        "profile__department_unit",
    ).distinct().order_by("first_name", "last_name", "username")

    # A staff member can have an older account for one office and a newer
    # account for another role.  When those accounts use the same verified
    # email address, show the person only once in the task recipient picker.
    # Do not deduplicate by name: two different staff members may share one.
    preferred_by_identity = {}
    for user in users:
        email = (user.email or "").strip().casefold()
        identity = ("email", email) if email else ("user", user.pk)
        current = preferred_by_identity.get(identity)
        if (
            current is None
            or _assignee_account_priority(user)
            > _assignee_account_priority(current)
        ):
            preferred_by_identity[identity] = user

    preferred_ids = [user.pk for user in preferred_by_identity.values()]
    return User.objects.filter(pk__in=preferred_ids).select_related(
        "profile", "profile__approval_role", "profile__department",
        "profile__department_unit",
    ).order_by("first_name", "last_name", "username")


def _assignee_account_priority(user):
    """Prefer established leadership accounts without modifying user data."""
    return (
        user.username.strip().casefold() in DSTI_LEGACY_ASSISTANT_USERNAMES,
        user.last_login is not None,
        user.last_login or user.date_joined,
        -user.pk,
    )
