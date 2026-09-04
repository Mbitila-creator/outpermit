from django.core.exceptions import PermissionDenied

from permits.executive_scope import executive_department_codes, is_executive_viewer

from .models import Event


def user_department(user):
    """Return the active OutPermit department assigned to a staff account."""
    profile = getattr(user, "profile", None)
    department = getattr(profile, "department", None)
    if department and department.is_active:
        return department
    return None


def is_system_event_administrator(user):
    profile = getattr(user, "profile", None)
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or getattr(profile, "role", "") == "ADMIN")
    )


def events_visible_to(user):
    """Scope internal event records to the signed-in user's department."""
    queryset = Event.objects.all()
    if is_system_event_administrator(user):
        return queryset
    if is_executive_viewer(user):
        department_codes = executive_department_codes(user)
        if department_codes is None:
            return queryset
        return queryset.filter(owning_department__code__in=department_codes)
    department = user_department(user)
    if not department:
        return queryset.none()
    return queryset.filter(owning_department=department)


def require_event_access(user, event):
    if not events_visible_to(user).filter(pk=event.pk).exists():
        raise PermissionDenied
    return event
