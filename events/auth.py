from django.contrib.auth.models import User

from permits.models import ModuleRoleAssignment
from permits.module_roles import module_role, module_roles


class EventRole:
    """Compatibility role names used by the imported Event Management apps."""

    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    EVENT_ADMIN = "EVENT_ADMIN"
    REGISTRATION_OFFICER = "REGISTRATION_OFFICER"
    ATTENDANCE_OFFICER = "ATTENDANCE_OFFICER"
    REPORT_OFFICER = "REPORT_OFFICER"
    DIRECTOR = "DIRECTOR"
    ASSISTANT_DIRECTOR = "ASSISTANT_DIRECTOR"
    PARTICIPANT = "PARTICIPANT"


OUTPERMIT_EVENT_ROLE_MAP = {
    "ADMIN": EventRole.SYSTEM_ADMIN,
    "DIRECTOR": EventRole.DIRECTOR,
    "ASSISTANT_DIRECTOR": EventRole.ASSISTANT_DIRECTOR,
    "HEAD_OF_UNIT": EventRole.EVENT_ADMIN,
    "EVENT_ADMIN": EventRole.EVENT_ADMIN,
    "REGISTRATION_OFFICER": EventRole.REGISTRATION_OFFICER,
    "ATTENDANCE_OFFICER": EventRole.ATTENDANCE_OFFICER,
    "REPORT_OFFICER": EventRole.REPORT_OFFICER,
    "REQUESTER": EventRole.PARTICIPANT,
}


def event_role(user):
    if user.is_superuser:
        return EventRole.SYSTEM_ADMIN
    profile = getattr(user, "profile", None)
    assigned_role = module_role(
        user,
        ModuleRoleAssignment.Module.EVENT,
        priority=(
            EventRole.EVENT_ADMIN,
            EventRole.REGISTRATION_OFFICER,
            EventRole.ATTENDANCE_OFFICER,
            EventRole.REPORT_OFFICER,
        ),
    )
    if assigned_role:
        return assigned_role
    return OUTPERMIT_EVENT_ROLE_MAP.get(
        getattr(profile, "role", ""), EventRole.PARTICIPANT
    )


def event_roles(user):
    if user.is_superuser:
        return {EventRole.SYSTEM_ADMIN}
    profile = getattr(user, "profile", None)
    roles = module_roles(user, ModuleRoleAssignment.Module.EVENT)
    roles.add(
        OUTPERMIT_EVENT_ROLE_MAP.get(
            getattr(profile, "role", ""), EventRole.PARTICIPANT
        )
    )
    return roles


def has_event_role(user, allowed_roles):
    return bool(event_roles(user).intersection(set(allowed_roles)))


# The imported views use User.Role constants and request.user.role. Expose a
# read-only compatibility surface while OutPermit remains the single account
# and department authority.
User.Role = EventRole
User.role = property(event_role)
User.preferred_language = property(lambda user: "en")
