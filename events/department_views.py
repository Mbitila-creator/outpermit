from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from forms_builder.models import EventForm

from .access import events_visible_to, is_system_event_administrator, user_department
from .auth import EventRole, has_event_role
from .management_forms import DepartmentEventForm


EVENT_CREATOR_ROLES = {
    "ADMIN",
    "DIRECTOR",
    "ASSISTANT_DIRECTOR",
    "HEAD_OF_UNIT",
    "EVENT_ADMIN",
}


def can_create_department_event(user):
    profile = getattr(user, "profile", None)
    return bool(
        user.is_authenticated
        and user.is_active
        and (
            is_system_event_administrator(user)
            or (
                getattr(profile, "role", "") in EVENT_CREATOR_ROLES
                and user_department(user)
            )
        )
    )


@login_required
def department_event_list(request):
    department = user_department(request.user)
    events = (
        events_visible_to(request.user)
        .select_related("owning_department", "category", "venue")
        .order_by("-starts_at", "code")
    )
    return render(request, "events/department_event_list.html", {
        "events": events,
        "department": department,
        "is_system_event_administrator": is_system_event_administrator(request.user),
        "can_create_event": can_create_department_event(request.user),
    })


@login_required
def department_event_detail(request, event_slug):
    event = get_object_or_404(
        events_visible_to(request.user).select_related(
            "owning_department", "category", "venue"
        ),
        slug=event_slug,
    )
    can_manage = request.user.is_superuser or has_event_role(request.user, {
        EventRole.SYSTEM_ADMIN,
        EventRole.EVENT_ADMIN,
        EventRole.DIRECTOR,
        EventRole.ASSISTANT_DIRECTOR,
    })
    registration_form = event.forms.filter(
        form_type__in={
            EventForm.FormType.REGISTRATION,
            EventForm.FormType.EXHIBITOR,
        },
        is_active=True,
    ).order_by("form_type", "pk").first()
    evaluation_form = event.forms.filter(
        form_type=EventForm.FormType.EVALUATION,
        is_active=True,
    ).order_by("pk").first()
    return render(request, "events/department_event_detail.html", {
        "event": event,
        "registration_form": registration_form,
        "evaluation_form": evaluation_form,
        "can_manage": can_manage,
        "can_manage_registrations": can_manage or has_event_role(
            request.user, {EventRole.REGISTRATION_OFFICER}
        ),
        "can_check_in": can_manage or has_event_role(request.user, {
            EventRole.REGISTRATION_OFFICER,
            EventRole.ATTENDANCE_OFFICER,
        }),
        "can_view_reports": can_manage or has_event_role(
            request.user, {EventRole.REPORT_OFFICER}
        ),
        "can_view_meetings": can_manage or has_event_role(request.user, {
            EventRole.ATTENDANCE_OFFICER,
            EventRole.REPORT_OFFICER,
        }),
    })


@login_required
def department_event_create(request):
    if not can_create_department_event(request.user):
        raise PermissionDenied
    form = DepartmentEventForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.created_by = request.user
        event.updated_by = request.user
        event.save()
        messages.success(request, f"{event.code} was created successfully.")
        return redirect("events:department_event_list")
    return render(request, "events/department_event_form.html", {"form": form})
