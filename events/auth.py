from django.contrib.auth.models import User


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
    "REQUESTER": EventRole.PARTICIPANT,
}


def event_role(user):
    if user.is_superuser:
        return EventRole.SYSTEM_ADMIN
    profile = getattr(user, "profile", None)
    return OUTPERMIT_EVENT_ROLE_MAP.get(
        getattr(profile, "role", ""), EventRole.PARTICIPANT
    )


# The imported views use User.Role constants and request.user.role. Expose a
# read-only compatibility surface while OutPermit remains the single account
# and department authority.
User.Role = EventRole
User.role = property(event_role)
User.preferred_language = property(lambda user: "en")
