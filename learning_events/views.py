from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from events.access import events_visible_to
from events.department_views import can_manage_department_event
from events.models import Event

from .forms import (
    LearningAssessmentForm, LearningAssessmentResultForm, LearningAttendanceForm,
    LearningEnrollmentForm, LearningEventProfileForm, LearningFacilitatorForm,
    LearningSessionForm, SeminarQuestionForm, WorkshopActivityForm,
    WorkshopActivitySubmissionForm,
)
from .models import (
    LEARNING_CATEGORY_CODES, LearningEnrollment, LearningEventProfile,
    normalized_category_code,
)


def _learning_event_for_user(user, event_slug):
    event = get_object_or_404(
        events_visible_to(user).select_related("category", "owning_department", "venue"),
        slug=event_slug,
    )
    if normalized_category_code(event) not in LEARNING_CATEGORY_CODES:
        raise PermissionDenied("This tool is available only for Seminar, Workshop and Training events.")
    return event


def _dashboard_context(profile, forms=None):
    forms = forms or {}
    category_code = normalized_category_code(profile.event)
    enrollments = profile.enrollments.filter(is_active=True).annotate(
        attended_sessions=Count("attendance_records", filter=Q(attendance_records__session__is_active=True), distinct=True),
    )
    return {
        "event": profile.event,
        "profile": profile,
        "category_code": category_code,
        "is_seminar": category_code == "SEMINAR",
        "is_workshop": category_code == "WORKSHOP",
        "is_training": category_code == "TRAINING",
        "facilitators": profile.facilitators.filter(is_active=True),
        "sessions": profile.sessions.filter(is_active=True).prefetch_related("facilitators"),
        "enrollments": enrollments,
        "assessments": profile.assessments.filter(is_active=True),
        "activities": profile.sessions.filter(is_active=True).prefetch_related("activities"),
        "seminar_questions": profile.seminar_questions.filter(is_active=True).select_related("session"),
        "profile_form": forms.get("profile") or LearningEventProfileForm(instance=profile),
        "facilitator_form": forms.get("facilitator") or LearningFacilitatorForm(),
        "session_form": forms.get("session") or LearningSessionForm(profile=profile),
        "enrollment_form": forms.get("enrollment") or LearningEnrollmentForm(profile=profile),
        "attendance_form": forms.get("attendance") or LearningAttendanceForm(profile=profile),
        "assessment_form": forms.get("assessment") or LearningAssessmentForm(),
        "result_form": forms.get("result") or LearningAssessmentResultForm(profile=profile),
        "activity_form": forms.get("activity") or WorkshopActivityForm(profile=profile),
        "activity_submission_form": forms.get("activity_submission") or WorkshopActivitySubmissionForm(profile=profile),
        "question_form": forms.get("question") or SeminarQuestionForm(profile=profile),
    }


@login_required
def dashboard(request, event_slug):
    event = _learning_event_for_user(request.user, event_slug)
    if not can_manage_department_event(request.user):
        raise PermissionDenied
    profile, _ = LearningEventProfile.objects.get_or_create(event=event)
    if request.method == "POST":
        action = request.POST.get("action", "")
        specifications = {
            "profile": (LearningEventProfileForm, {"instance": profile}),
            "facilitator": (LearningFacilitatorForm, {}),
            "session": (LearningSessionForm, {"profile": profile}),
            "enrollment": (LearningEnrollmentForm, {"profile": profile}),
            "attendance": (LearningAttendanceForm, {"profile": profile}),
            "assessment": (LearningAssessmentForm, {}),
            "result": (LearningAssessmentResultForm, {"profile": profile}),
            "activity": (WorkshopActivityForm, {"profile": profile}),
            "activity_submission": (WorkshopActivitySubmissionForm, {"profile": profile}),
            "question": (SeminarQuestionForm, {"profile": profile}),
        }
        if action not in specifications:
            raise PermissionDenied
        if action in {"assessment", "result"} and normalized_category_code(event) != "TRAINING":
            raise PermissionDenied
        if action in {"activity", "activity_submission"} and normalized_category_code(event) != "WORKSHOP":
            raise PermissionDenied
        if action == "question" and normalized_category_code(event) != "SEMINAR":
            raise PermissionDenied
        form_class, kwargs = specifications[action]
        form = form_class(request.POST, request.FILES, **kwargs)
        if form.is_valid():
            obj = form.save(commit=False)
            if action != "profile" and hasattr(obj, "profile_id"):
                obj.profile = profile
            if action in {"attendance", "result"}:
                if action == "attendance":
                    obj.checked_in_by = request.user
                else:
                    obj.recorded_by = request.user
            obj.save()
            if hasattr(form, "save_m2m"):
                form.save_m2m()
            messages.success(request, "The learning-event record was saved successfully.")
            return redirect("learning_events:dashboard", event_slug=event.slug)
        return render(request, "learning_events/dashboard.html", _dashboard_context(profile, {action: form}))
    return render(request, "learning_events/dashboard.html", _dashboard_context(profile))


@login_required
def approve_certificate(request, event_slug, enrollment_id):
    if request.method != "POST":
        raise PermissionDenied
    event = _learning_event_for_user(request.user, event_slug)
    if not can_manage_department_event(request.user):
        raise PermissionDenied
    enrollment = get_object_or_404(
        LearningEnrollment.objects.select_related("profile", "profile__event"),
        pk=enrollment_id, profile__event=event,
    )
    try:
        enrollment.approve_certificate(request.user)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, f"Certificate approved for {enrollment.full_name}.")
    return redirect("learning_events:dashboard", event_slug=event.slug)


def public_programme(request, event_slug):
    event = get_object_or_404(
        Event.objects.select_related("category", "owning_department", "venue"),
        slug=event_slug, is_active=True, is_public=True,
    )
    if normalized_category_code(event) not in LEARNING_CATEGORY_CODES:
        raise PermissionDenied
    profile = LearningEventProfile.objects.filter(event=event, is_active=True).first()
    return render(request, "learning_events/public_programme.html", {
        "event": event,
        "profile": profile,
        "sessions": profile.sessions.filter(is_active=True, is_published=True).prefetch_related("facilitators") if profile else [],
        "facilitators": profile.facilitators.filter(is_active=True) if profile else [],
    })
