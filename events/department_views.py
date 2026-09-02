import base64

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from forms_builder.models import EventForm
from forms_builder.services import (
    certificate_qr_logo_path,
    event_date_range,
    generate_qr_png,
    weuutz_event_sentence_html,
)

from .access import events_visible_to, is_system_event_administrator, user_department
from .auth import EventRole, has_event_role
from .management_forms import DepartmentEventForm, EventTimetableForm
from .models import EventTimetable


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


def can_manage_department_event(user):
    return user.is_superuser or has_event_role(user, {
        EventRole.SYSTEM_ADMIN,
        EventRole.EVENT_ADMIN,
        EventRole.DIRECTOR,
        EventRole.ASSISTANT_DIRECTOR,
    })


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
    can_manage = can_manage_department_event(request.user)
    can_manage_registrations = can_manage or has_event_role(
        request.user, {EventRole.REGISTRATION_OFFICER}
    )
    can_check_in = can_manage or has_event_role(request.user, {
        EventRole.REGISTRATION_OFFICER,
        EventRole.ATTENDANCE_OFFICER,
    })
    can_view_reports = can_manage or has_event_role(
        request.user, {EventRole.REPORT_OFFICER}
    )
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
        "show_dsti_researcher_records": (
            event.category.is_special_event
            and event.owning_department.code.strip().upper() == "DSTI"
        ),
        "can_manage": can_manage,
        "can_manage_registrations": can_manage_registrations,
        "can_check_in": can_check_in,
        "can_view_registration_records": can_manage_registrations or can_check_in,
        "can_view_attendance_records": can_check_in,
        "can_view_reports": can_view_reports,
        "can_view_meetings": can_manage or has_event_role(request.user, {
            EventRole.ATTENDANCE_OFFICER,
            EventRole.REPORT_OFFICER,
        }),
        "timetable": EventTimetable.objects.filter(event=event).first(),
    })


def _public_timetable(event_slug, public_token):
    return get_object_or_404(
        EventTimetable.objects.select_related("event"),
        event__slug=event_slug,
        event__is_active=True,
        event__is_public=True,
        public_token=public_token,
        is_active=True,
        is_published=True,
    )


@login_required
def department_event_timetable(request, event_slug):
    event = get_object_or_404(events_visible_to(request.user), slug=event_slug)
    if not can_manage_department_event(request.user):
        raise PermissionDenied
    timetable = EventTimetable.objects.filter(event=event).first()
    form = EventTimetableForm(
        request.POST or None,
        request.FILES or None,
        instance=timetable,
    )
    if request.method == "POST" and form.is_valid():
        timetable = form.save(commit=False)
        timetable.event = event
        timetable.created_by = timetable.created_by or request.user
        timetable.updated_by = request.user
        timetable.save()
        messages.success(request, "The event timetable was saved successfully.")
        return redirect("events:department_event_timetable", event_slug=event.slug)
    return render(request, "events/department_event_timetable.html", {
        "event": event,
        "form": form,
        "timetable": timetable,
    })


def public_event_timetable(request, event_slug, public_token):
    timetable = _public_timetable(event_slug, public_token)
    return render(request, "events/public_event_timetable.html", {
        "event": timetable.event,
        "timetable": timetable,
    })


def public_event_timetable_download(request, event_slug, public_token):
    timetable = _public_timetable(event_slug, public_token)
    filename = timetable.pdf_file.name.rsplit("/", 1)[-1]
    return FileResponse(
        timetable.pdf_file.open("rb"),
        as_attachment=True,
        filename=filename,
        content_type="application/pdf",
    )


def public_event_timetable_qr(request, event_slug, public_token):
    timetable = _public_timetable(event_slug, public_token)
    path = reverse("events:public_event_timetable", kwargs={
        "event_slug": timetable.event.slug,
        "public_token": timetable.public_token,
    })
    url = f"{settings.PUBLIC_BASE_URL}{path}" if settings.PUBLIC_BASE_URL else request.build_absolute_uri(path)
    return HttpResponse(
        generate_qr_png(url, logo_path=certificate_qr_logo_path(timetable.event)),
        content_type="image/png",
    )


@login_required
def department_certificate_preview(request, event_slug):
    event = get_object_or_404(
        events_visible_to(request.user).select_related(
            "owning_department", "category", "venue"
        ),
        slug=event_slug,
        code="WEUUTz-2026",
    )
    if not can_manage_department_event(request.user):
        raise PermissionDenied
    preview_qr = generate_qr_png(
        f"SAMPLE CERTIFICATE — {event.code} — NOT VALID",
        logo_path=certificate_qr_logo_path(event),
    )
    return render(request, "events/department_certificate_preview.html", {
        "event": event,
        "event_display_name": event.title_en,
        "event_date_range": event_date_range(event, language="en"),
        "weuutz_event_sentence_html": weuutz_event_sentence_html(event),
        "preview_qr_data": base64.b64encode(preview_qr).decode("ascii"),
        "sample_institution": "Sample Participating Institution",
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
