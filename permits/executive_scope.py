"""Shared organizational visibility rules for Ministry top officials."""


EXECUTIVE_ROLES = {
    "PERMANENT_SECRETARY",
    "DPS_HES",
    "DPS_BE",
    "COMMISSIONER_EDUCATION",
}

EXECUTIVE_DEPARTMENT_CODES = {
    "DPS_HES": {"HED", "DSTI", "DTVET"},
    "DPS_BE": {"COE", "SQAD"},
    "COMMISSIONER_EDUCATION": {"COE"},
}


def user_primary_role(user):
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    profile = getattr(user, "profile", None)
    approval_role = getattr(profile, "approval_role", None)
    code = getattr(approval_role, "code", "") or getattr(profile, "role", "")
    return (code or "").strip().upper()


def is_executive_viewer(user):
    return user_primary_role(user) in EXECUTIVE_ROLES


def executive_department_codes(user):
    """Return None for PS/all-Ministry, or the official scoped codes."""
    role = user_primary_role(user)
    if role == "PERMANENT_SECRETARY":
        return None
    return EXECUTIVE_DEPARTMENT_CODES.get(role, set())

