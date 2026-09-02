import base64
import calendar
import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Exists, Max, OuterRef, Prefetch, Q
from django.db.models.functions import TruncMonth
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from events.auth import User, has_event_role
from events.models import Event
from events.access import events_visible_to
from forms_builder.services import generate_qr_png

from .forms import (
    ActionCompletionReviewForm,
    ActionProgressForm,
    AttendanceOnlyForm,
    AttendeeProgressForm,
    InvitationResponseForm,
    MeetingActionItemForm,
    MeetingAgendaItemForm,
    MeetingAttendeeForm,
    MeetingDecisionForm,
    MeetingDocumentForm,
    MeetingFeedbackForm,
    MeetingMinutesForm,
    MeetingOccurrenceForm,
    MeetingResourceBookingForm,
    MeetingResourceForm,
    MeetingSeriesAgendaTemplateForm,
    MeetingSeriesForm,
    MeetingWorkflowForm,
    MeetingClosureForm,
    MinutesApprovalForm,
    MinutesReturnForm,
    PersonalActionProgressForm,
)
from .models import (
    Meeting,
    MeetingActionCompletionReview,
    MeetingActionItem,
    MeetingActionProgressUpdate,
    MeetingAttendee,
    MeetingCommunicationLog,
    MeetingDecision,
    MeetingDocument,
    MeetingDocumentAcknowledgement,
    MeetingFeedback,
    MeetingMinutesReview,
    MeetingResource,
    MeetingResourceBooking,
    MeetingSeries,
)
from .services import (
    send_action_escalation,
    send_action_reminder,
    send_action_review_result_notification,
    send_action_review_submission_notifications,
    send_meeting_invitation,
    send_rsvp_reminder,
    send_upcoming_meeting_reminder,
)


MEETING_VIEW_ROLES = {
    User.Role.SYSTEM_ADMIN,
    User.Role.EVENT_ADMIN,
    User.Role.ATTENDANCE_OFFICER,
    User.Role.REPORT_OFFICER,
    User.Role.DIRECTOR,
    User.Role.ASSISTANT_DIRECTOR,
}
MEETING_MANAGER_ROLES = {
    User.Role.SYSTEM_ADMIN,
    User.Role.EVENT_ADMIN,
}
MINUTES_APPROVER_ROLES = {
    User.Role.SYSTEM_ADMIN,
    User.Role.DIRECTOR,
    User.Role.ASSISTANT_DIRECTOR,
}


def _can_manage(user):
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or has_event_role(user, MEETING_MANAGER_ROLES))
    )


def _can_record_attendance(user):
    return bool(
        user.is_authenticated
        and user.is_active
        and (
            user.is_superuser
            or has_event_role(
                user,
                MEETING_MANAGER_ROLES | {User.Role.ATTENDANCE_OFFICER},
            )
        )
    )


def _can_approve_minutes(user):
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or has_event_role(user, MINUTES_APPROVER_ROLES))
    )


def _require_view_access(user):
    if not (
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or has_event_role(user, MEETING_VIEW_ROLES))
    ):
        raise PermissionDenied


def _require_manager(user):
    if not _can_manage(user):
        raise PermissionDenied


def _require_minutes_approver(user):
    if not _can_approve_minutes(user):
        raise PermissionDenied


def _meeting_checkin_state(meeting, moment=None):
    moment = moment or timezone.now()
    if not meeting.checkin_enabled:
        return False, _("QR check-in is not enabled for this meeting.")
    if meeting.event.status == Event.Status.CANCELLED:
        return False, _("Check-in is not available for a cancelled meeting.")
    if meeting.checkin_opens_at and moment < meeting.checkin_opens_at:
        return False, _("The meeting check-in window has not opened yet.")
    if meeting.checkin_closes_at and moment > meeting.checkin_closes_at:
        return False, _("The meeting check-in window is closed.")
    return True, ""


def _qr_data_uri(value):
    encoded = base64.b64encode(generate_qr_png(
        value,
        fill_color="#17365d",
    )).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _attendee_checkin_url(request, attendee):
    path = reverse(
        "meetings:attendee_checkin",
        kwargs={"response_token": attendee.response_token},
    )
    return request.build_absolute_uri(f"{path}?auto=1")


def _meeting_feedback_state(meeting, attendee=None, moment=None):
    moment = moment or timezone.now()
    if not meeting.evaluation_enabled:
        return False, _("Participant evaluation is not enabled for this meeting.")
    if meeting.event.status == Event.Status.CANCELLED:
        return False, _("Evaluation is not available for a cancelled meeting.")
    if moment < meeting.event.ends_at:
        return False, _("The evaluation form will open after the meeting ends.")
    if meeting.evaluation_deadline and moment > meeting.evaluation_deadline:
        return False, _("The evaluation period has closed.")
    if (
        attendee
        and attendee.attendance_status
        != MeetingAttendee.AttendanceStatus.PRESENT
    ):
        return False, _("Only participants marked present can submit feedback.")
    return True, ""


def _meeting_closure_blockers(meeting, moment=None):
    moment = moment or timezone.now()
    blockers = []
    if moment < meeting.event.ends_at:
        blockers.append(_("The meeting has not ended yet."))
    if meeting.minutes_status != Meeting.MinutesStatus.APPROVED:
        blockers.append(_("The meeting minutes have not been approved."))
    return blockers


def _meeting_queryset(user):
    return Meeting.objects.filter(event__in=events_visible_to(user)).select_related(
        "event", "event__category", "event__venue", "series",
        "minutes_approved_by",
    ).prefetch_related(
        "agenda_items", "attendees__user", "decisions__agenda_item",
        "action_items__decision", "action_items__responsible_user",
        "communications",
        "documents__agenda_item",
        "minutes_reviews__created_by",
        "resource_bookings__resource", "resource_bookings__confirmed_by",
    )


def _form_error_message(form):
    first_error = next(
        (
            str(error)
            for errors in form.errors.values()
            for error in errors
        ),
        _("Check the information entered and try again."),
    )
    return first_error


def _month_value(raw_value):
    try:
        return date.fromisoformat(f"{raw_value}-01")
    except (TypeError, ValueError):
        return timezone.localdate().replace(day=1)


def _next_month(month):
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def _report_actions(request):
    actions = MeetingActionItem.objects.select_related(
        "meeting", "meeting__event", "responsible_user",
    ).filter(
        is_active=True,
        meeting__is_active=True,
        meeting__event__in=events_visible_to(request.user),
    )
    selected_status = request.GET.get("status", "OPEN").strip().upper()
    selected_meeting = request.GET.get("meeting", "").strip()
    closed_statuses = {
        MeetingActionItem.Status.COMPLETED,
        MeetingActionItem.Status.CANCELLED,
    }
    overdue_excluded_statuses = closed_statuses | {
        MeetingActionItem.Status.AWAITING_REVIEW,
    }
    if selected_status == "OPEN":
        actions = actions.exclude(status__in=closed_statuses)
    elif selected_status == "OVERDUE":
        actions = actions.filter(
            Q(status=MeetingActionItem.Status.OVERDUE)
            | Q(due_date__lt=timezone.localdate()),
        ).exclude(status__in=overdue_excluded_statuses)
    elif selected_status in MeetingActionItem.Status.values:
        actions = actions.filter(status=selected_status)
    else:
        selected_status = "ALL"
    if selected_meeting.isdigit():
        actions = actions.filter(meeting_id=selected_meeting)
    else:
        selected_meeting = ""
    today = timezone.localdate()
    rows = list(actions.order_by("due_date", "meeting__event__starts_at"))
    for action in rows:
        action.is_report_overdue = bool(
            action.status == MeetingActionItem.Status.OVERDUE
            or (
                action.due_date
                and action.due_date < today
                and action.status not in overdue_excluded_statuses
            )
        )
    return rows, selected_status, selected_meeting


def _safe_csv_value(value):
    rendered = "" if value is None else str(value)
    if rendered.startswith(("=", "+", "-", "@")):
        return f"'{rendered}"
    return rendered


def _report_date(raw_value, fallback):
    try:
        return date.fromisoformat(raw_value)
    except (TypeError, ValueError):
        return fallback


def _decision_register_rows(request):
    decisions = MeetingDecision.objects.select_related(
        "meeting", "meeting__event", "agenda_item",
    ).filter(
        is_active=True,
        meeting__is_active=True,
        meeting__event__in=events_visible_to(request.user),
    ).annotate(
        action_total=Count(
            "action_items",
            filter=Q(action_items__is_active=True),
            distinct=True,
        ),
        action_completed=Count(
            "action_items",
            filter=Q(
                action_items__is_active=True,
                action_items__status=MeetingActionItem.Status.COMPLETED,
            ),
            distinct=True,
        ),
    )
    search_query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "").strip().upper()
    selected_meeting = request.GET.get("meeting", "").strip()
    date_from = _report_date(request.GET.get("date_from"), None)
    date_to = _report_date(request.GET.get("date_to"), None)
    if search_query:
        decisions = decisions.filter(
            Q(decision_sw__icontains=search_query)
            | Q(decision_en__icontains=search_query)
            | Q(meeting__reference_number__icontains=search_query)
            | Q(meeting__event__title_sw__icontains=search_query)
            | Q(meeting__event__title_en__icontains=search_query)
        )
    if selected_status in MeetingDecision.Status.values:
        decisions = decisions.filter(status=selected_status)
    else:
        selected_status = ""
    if selected_meeting.isdigit():
        decisions = decisions.filter(meeting_id=selected_meeting)
    else:
        selected_meeting = ""
    if date_from:
        decisions = decisions.filter(meeting__event__starts_at__date__gte=date_from)
    if date_to:
        decisions = decisions.filter(meeting__event__starts_at__date__lte=date_to)
    rows = list(decisions.order_by("-meeting__event__starts_at", "decision_number"))
    for decision in rows:
        if decision.action_total == 0:
            decision.implementation_code = "NO_ACTION"
            decision.implementation_label = _("No action assigned")
            decision.implementation_class = "neutral"
        elif decision.action_completed == decision.action_total:
            decision.implementation_code = "IMPLEMENTED"
            decision.implementation_label = _("Implemented")
            decision.implementation_class = "success"
        elif decision.action_completed:
            decision.implementation_code = "PARTIAL"
            decision.implementation_label = _("Partly implemented")
            decision.implementation_class = "warning"
        else:
            decision.implementation_code = "PENDING"
            decision.implementation_label = _("Implementation pending")
            decision.implementation_class = "warning"
    return {
        "rows": rows,
        "search_query": search_query,
        "selected_status": selected_status,
        "selected_meeting": selected_meeting,
        "date_from": date_from,
        "date_to": date_to,
    }


@login_required(login_url="login")
@require_GET
def executive_dashboard(request):
    _require_view_access(request.user)
    today = timezone.localdate()
    default_from = today.replace(month=1, day=1)
    date_from = _report_date(request.GET.get("date_from"), default_from)
    date_to = _report_date(request.GET.get("date_to"), today)
    meeting_type = request.GET.get("type", "").strip().upper()
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    meetings = Meeting.objects.filter(
        is_active=True,
        event__in=events_visible_to(request.user),
        event__starts_at__date__gte=date_from,
        event__starts_at__date__lte=date_to,
    )
    if meeting_type in Meeting.MeetingType.values:
        meetings = meetings.filter(meeting_type=meeting_type)
    else:
        meeting_type = ""
    meeting_ids = meetings.values_list("pk", flat=True)
    attendees = MeetingAttendee.objects.filter(
        is_active=True,
        meeting_id__in=meeting_ids,
    )
    actions = MeetingActionItem.objects.filter(
        is_active=True,
        meeting_id__in=meeting_ids,
    )
    decisions = MeetingDecision.objects.filter(
        is_active=True,
        meeting_id__in=meeting_ids,
    )
    feedbacks = MeetingFeedback.objects.filter(
        is_active=True,
        meeting_id__in=meeting_ids,
    )
    total_meetings = meetings.count()
    total_attendees = attendees.count()
    present_attendees = attendees.filter(
        attendance_status=MeetingAttendee.AttendanceStatus.PRESENT,
    ).count()
    total_actions = actions.count()
    completed_actions = actions.filter(
        status=MeetingActionItem.Status.COMPLETED,
    ).count()
    metrics = {
        "total_meetings": total_meetings,
        "closed_meetings": meetings.filter(
            closure_status=Meeting.ClosureStatus.CLOSED,
        ).count(),
        "approved_minutes": meetings.filter(
            minutes_status=Meeting.MinutesStatus.APPROVED,
        ).count(),
        "attendance_rate": round(
            (present_attendees / total_attendees) * 100, 1,
        ) if total_attendees else 0,
        "feedback_count": feedbacks.count(),
        "feedback_average": feedbacks.aggregate(
            value=Avg("overall_rating"),
        )["value"],
        "decision_count": decisions.count(),
        "approved_decisions": decisions.filter(
            status=MeetingDecision.Status.APPROVED,
        ).count(),
        "action_count": total_actions,
        "action_completion_rate": round(
            (completed_actions / total_actions) * 100, 1,
        ) if total_actions else 0,
    }
    metrics["closure_rate"] = round(
        (metrics["closed_meetings"] / total_meetings) * 100, 1,
    ) if total_meetings else 0
    metrics["minutes_approval_rate"] = round(
        (metrics["approved_minutes"] / total_meetings) * 100, 1,
    ) if total_meetings else 0
    monthly_rows = meetings.annotate(
        month=TruncMonth("event__starts_at"),
    ).values("month").annotate(
        total=Count("id", distinct=True),
        closed=Count(
            "id",
            filter=Q(closure_status=Meeting.ClosureStatus.CLOSED),
            distinct=True,
        ),
    ).order_by("month")
    performance_rows = meetings.select_related("event", "event__venue").annotate(
        participant_total=Count(
            "attendees", filter=Q(attendees__is_active=True), distinct=True,
        ),
        present_total=Count(
            "attendees",
            filter=Q(
                attendees__is_active=True,
                attendees__attendance_status=MeetingAttendee.AttendanceStatus.PRESENT,
            ),
            distinct=True,
        ),
        decision_total=Count(
            "decisions", filter=Q(decisions__is_active=True), distinct=True,
        ),
        action_total=Count(
            "action_items", filter=Q(action_items__is_active=True), distinct=True,
        ),
        completed_action_total=Count(
            "action_items",
            filter=Q(
                action_items__is_active=True,
                action_items__status=MeetingActionItem.Status.COMPLETED,
            ),
            distinct=True,
        ),
        feedback_total=Count(
            "feedback_responses",
            filter=Q(feedback_responses__is_active=True),
            distinct=True,
        ),
        feedback_average=Avg(
            "feedback_responses__overall_rating",
            filter=Q(feedback_responses__is_active=True),
        ),
    ).order_by("-event__starts_at")[:100]
    return render(request, "meetings/executive_dashboard.html", {
        "metrics": metrics,
        "monthly_rows": monthly_rows,
        "performance_rows": performance_rows,
        "date_from": date_from,
        "date_to": date_to,
        "selected_type": meeting_type,
        "meeting_type_choices": Meeting.MeetingType.choices,
        "can_manage": _can_manage(request.user),
    })


@login_required(login_url="login")
@require_GET
def decision_register(request):
    _require_view_access(request.user)
    report = _decision_register_rows(request)
    rows = report["rows"]
    report["summary"] = {
        "total": len(rows),
        "approved": sum(
            decision.status == MeetingDecision.Status.APPROVED
            for decision in rows
        ),
        "implemented": sum(
            decision.implementation_code == "IMPLEMENTED"
            for decision in rows
        ),
        "pending": sum(
            decision.action_total > decision.action_completed
            for decision in rows
        ),
    }
    report.update({
        "meetings": _meeting_queryset(request.user).filter(
            is_active=True,
        ).order_by("-event__starts_at"),
        "status_choices": MeetingDecision.Status.choices,
    })
    return render(request, "meetings/decision_register.html", report)


@login_required(login_url="login")
@require_GET
def decision_register_csv(request):
    _require_view_access(request.user)
    rows = _decision_register_rows(request)["rows"]
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")
    response["Content-Disposition"] = (
        'attachment; filename="institutional-meeting-decisions.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        _("Meeting reference"), _("Meeting date"), _("Meeting"),
        _("Decision number"), _("Decision"), _("Decision status"),
        _("Assigned actions"), _("Completed actions"),
        _("Implementation status"),
    ])
    language = request.LANGUAGE_CODE
    for decision in rows:
        decision_text = (
            decision.decision_en
            if language == "en" and decision.decision_en
            else decision.decision_sw
        )
        meeting_title = (
            decision.meeting.event.title_en
            if language == "en"
            else decision.meeting.event.title_sw
        )
        writer.writerow([_safe_csv_value(value) for value in (
            decision.meeting.reference_number,
            timezone.localdate(decision.meeting.event.starts_at).isoformat(),
            meeting_title,
            decision.decision_number,
            decision_text,
            decision.get_status_display(),
            decision.action_total,
            decision.action_completed,
            decision.implementation_label,
        )])
    return response


@login_required(login_url="login")
def meeting_list(request):
    _require_view_access(request.user)
    visible_meetings = Meeting.objects.filter(
        event__in=events_visible_to(request.user),
    )
    meetings = visible_meetings.select_related("event", "event__venue").annotate(
        participant_count=Count(
            "attendees",
            filter=Q(attendees__is_active=True),
            distinct=True,
        ),
        action_count=Count(
            "action_items",
            filter=Q(action_items__is_active=True),
            distinct=True,
        ),
    ).order_by("-event__starts_at")
    search_query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    meeting_type = request.GET.get("type", "").strip()
    selected_event_id = request.GET.get("event", "").strip()
    if selected_event_id:
        meetings = meetings.filter(event_id=selected_event_id)
    if search_query:
        meetings = meetings.filter(
            Q(reference_number__icontains=search_query)
            | Q(event__code__icontains=search_query)
            | Q(event__title_sw__icontains=search_query)
            | Q(event__title_en__icontains=search_query)
            | Q(chairperson_name__icontains=search_query)
        )
    if status:
        meetings = meetings.filter(event__status=status)
    if meeting_type:
        meetings = meetings.filter(meeting_type=meeting_type)
    context = {
        "meetings": meetings,
        "search_query": search_query,
        "selected_status": status,
        "selected_type": meeting_type,
        "event_status_choices": Event.Status.choices,
        "meeting_type_choices": Meeting.MeetingType.choices,
        "can_manage": _can_manage(request.user),
        "can_approve_minutes": _can_approve_minutes(request.user),
        "total_meetings": visible_meetings.filter(is_active=True).count(),
        "upcoming_meetings": visible_meetings.filter(
            is_active=True,
            event__starts_at__gte=timezone.now(),
        ).count(),
        "open_actions": MeetingActionItem.objects.filter(
            is_active=True,
            meeting__event__in=events_visible_to(request.user),
        ).exclude(
            status__in={
                MeetingActionItem.Status.COMPLETED,
                MeetingActionItem.Status.CANCELLED,
            },
        ).count(),
        "minutes_awaiting_approval": visible_meetings.filter(
            is_active=True,
            minutes_status=Meeting.MinutesStatus.SUBMITTED,
        ).count(),
    }
    return render(request, "meetings/meeting_list.html", context)


@login_required(login_url="login")
@require_GET
def personal_meeting_workspace(request):
    if not request.user.is_active:
        raise PermissionDenied
    now = timezone.now()
    today = timezone.localdate()
    acknowledgement_exists = MeetingDocumentAcknowledgement.objects.filter(
        document_id=OuterRef("pk"),
        attendee__user=request.user,
        attendee__is_active=True,
        is_active=True,
    )
    participant_documents = MeetingDocument.objects.filter(
        is_active=True,
        is_confidential=False,
    ).select_related("agenda_item").annotate(
        is_acknowledged=Exists(acknowledgement_exists),
    ).order_by("document_type", "title_sw", "-version")
    participations = MeetingAttendee.objects.select_related(
        "meeting", "meeting__event", "meeting__event__venue",
    ).prefetch_related(
        Prefetch(
            "meeting__documents",
            queryset=participant_documents,
            to_attr="participant_pack_documents",
        ),
    ).filter(
        is_active=True,
        user=request.user,
        meeting__is_active=True,
    ).exclude(
        meeting__event__status=Event.Status.CANCELLED,
    )
    upcoming_participations = participations.filter(
        meeting__event__ends_at__gte=now,
    ).order_by("meeting__event__starts_at")
    recent_participations = participations.filter(
        meeting__event__ends_at__lt=now,
    ).order_by("-meeting__event__starts_at")[:20]

    actions = MeetingActionItem.objects.select_related(
        "meeting", "meeting__event", "decision",
    ).prefetch_related(
        "progress_updates__created_by",
        "completion_reviews__created_by",
    ).filter(
        is_active=True,
        meeting__is_active=True,
        responsible_user=request.user,
    )
    selected_status = request.GET.get("status", "OPEN").strip().upper()
    closed_statuses = {
        MeetingActionItem.Status.COMPLETED,
        MeetingActionItem.Status.CANCELLED,
    }
    overdue_excluded_statuses = closed_statuses | {
        MeetingActionItem.Status.AWAITING_REVIEW,
    }
    all_actions = actions
    if selected_status == "OPEN":
        actions = actions.exclude(status__in=closed_statuses)
    elif selected_status == "OVERDUE":
        actions = actions.filter(
            Q(status=MeetingActionItem.Status.OVERDUE) | Q(due_date__lt=today),
        ).exclude(status__in=overdue_excluded_statuses)
    elif selected_status == MeetingActionItem.Status.COMPLETED:
        actions = actions.filter(status=MeetingActionItem.Status.COMPLETED)
    elif selected_status != "ALL":
        selected_status = "OPEN"
        actions = actions.exclude(status__in=closed_statuses)
    action_rows = list(actions.order_by("due_date", "meeting__event__starts_at"))
    for action in action_rows:
        action.is_personal_overdue = bool(
            action.status not in overdue_excluded_statuses
            and action.due_date
            and action.due_date < today
        )
        action.days_overdue = (
            (today - action.due_date).days if action.is_personal_overdue else 0
        )
        action.progress_form = PersonalActionProgressForm(initial={
            "status": (
                MeetingActionItem.Status.IN_PROGRESS
                if action.status in {
                    MeetingActionItem.Status.OVERDUE,
                    MeetingActionItem.Status.RETURNED,
                }
                else action.status
            ),
            "progress_notes": action.progress_notes,
            "completion_percentage": action.completion_percentage,
        })
        action.progress_history = [
            update
            for update in action.progress_updates.all()
            if update.is_active
        ][:10]
        action.completion_review_history = [
            review
            for review in action.completion_reviews.all()
            if review.is_active
        ][:10]
    return render(request, "meetings/personal_workspace.html", {
        "upcoming_participations": upcoming_participations,
        "recent_participations": recent_participations,
        "actions": action_rows,
        "selected_status": selected_status,
        "summary": {
            "upcoming": upcoming_participations.count(),
            "open_actions": all_actions.exclude(status__in=closed_statuses).count(),
            "overdue_actions": all_actions.filter(
                Q(status=MeetingActionItem.Status.OVERDUE) | Q(due_date__lt=today),
            ).exclude(status__in=overdue_excluded_statuses).count(),
            "completed_actions": all_actions.filter(
                status=MeetingActionItem.Status.COMPLETED,
            ).count(),
        },
    })


@login_required(login_url="login")
@require_POST
@transaction.atomic
def personal_action_update(request, action_id):
    if not request.user.is_active:
        raise PermissionDenied
    action = get_object_or_404(
        MeetingActionItem,
        pk=action_id,
        responsible_user=request.user,
        is_active=True,
        meeting__is_active=True,
    )
    if action.status in {
        MeetingActionItem.Status.AWAITING_REVIEW,
        MeetingActionItem.Status.COMPLETED,
        MeetingActionItem.Status.CANCELLED,
    }:
        messages.error(
            request,
            _("An action awaiting review or already closed cannot be changed."),
        )
        return redirect("meetings:personal_meeting_workspace")
    form = PersonalActionProgressForm(request.POST, request.FILES)
    if form.is_valid():
        action.status = form.cleaned_data["status"]
        action.progress_notes = form.cleaned_data["progress_notes"].strip()
        action.completion_percentage = form.cleaned_data["completion_percentage"]
        action.completed_at = None
        action.updated_by = request.user
        action.save()
        evidence = form.cleaned_data.get("evidence_file")
        MeetingActionProgressUpdate.objects.create(
            action=action,
            status=action.status,
            completion_percentage=action.completion_percentage,
            notes=action.progress_notes,
            evidence_file=evidence,
            original_filename=evidence.name[:255] if evidence else "",
            created_by=request.user,
            updated_by=request.user,
        )
        if action.status == MeetingActionItem.Status.AWAITING_REVIEW:
            _sent, failed = send_action_review_submission_notifications(
                action,
                request=request,
            )
            if failed:
                messages.warning(
                    request,
                    _("Progress was saved, but some manager notifications failed."),
                )
        messages.success(request, _("Your action progress was updated successfully."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect("meetings:personal_meeting_workspace")


@login_required(login_url="login")
@require_POST
@transaction.atomic
def action_completion_review(request, meeting_id, action_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    action = get_object_or_404(
        MeetingActionItem.objects.select_for_update(),
        pk=action_id,
        meeting=meeting,
        is_active=True,
        status=MeetingActionItem.Status.AWAITING_REVIEW,
    )
    form = ActionCompletionReviewForm(request.POST)
    if form.is_valid():
        outcome = form.cleaned_data["outcome"]
        comment = form.cleaned_data["comment"].strip()
        if outcome == MeetingActionCompletionReview.Outcome.VERIFIED:
            action.status = MeetingActionItem.Status.COMPLETED
            success_message = _("The action completion was verified and closed.")
        else:
            action.status = MeetingActionItem.Status.RETURNED
            success_message = _("The action was returned for correction.")
        action.progress_notes = comment or action.progress_notes
        action.updated_by = request.user
        action.save()
        review = MeetingActionCompletionReview.objects.create(
            action=action,
            outcome=outcome,
            comment=comment,
            created_by=request.user,
            updated_by=request.user,
        )
        MeetingActionProgressUpdate.objects.create(
            action=action,
            status=action.status,
            completion_percentage=action.completion_percentage,
            notes=comment,
            created_by=request.user,
            updated_by=request.user,
        )
        try:
            send_action_review_result_notification(
                action,
                review,
                request=request,
            )
        except Exception:
            messages.warning(
                request,
                _("The review was saved, but the responsible person notification failed."),
            )
        messages.success(request, success_message)
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#actions")


@login_required(login_url="login")
@require_GET
def action_progress_evidence_download(request, update_id):
    updates = MeetingActionProgressUpdate.objects.select_related(
        "action", "action__meeting",
    ).filter(
        pk=update_id,
        is_active=True,
        action__is_active=True,
        action__meeting__is_active=True,
    )
    if not (
        request.user.is_active
        and (
            request.user.is_superuser
            or has_event_role(request.user, MEETING_VIEW_ROLES)
        )
    ):
        updates = updates.filter(action__responsible_user=request.user)
    update = get_object_or_404(updates)
    if not update.evidence_file:
        raise Http404
    try:
        update.evidence_file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response = FileResponse(
        update.evidence_file,
        as_attachment=True,
        filename=update.original_filename or Path(update.evidence_file.name).name,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def _personal_document_access(request, document_id):
    if not request.user.is_active:
        raise PermissionDenied
    document = get_object_or_404(
        MeetingDocument.objects.select_related("meeting", "meeting__event"),
        pk=document_id,
        is_active=True,
        is_confidential=False,
        meeting__is_active=True,
        meeting__attendees__user=request.user,
        meeting__attendees__is_active=True,
    )
    attendee = get_object_or_404(
        MeetingAttendee,
        meeting=document.meeting,
        user=request.user,
        is_active=True,
    )
    return document, attendee


@login_required(login_url="login")
@require_GET
def personal_document_download(request, document_id):
    document, _attendee = _personal_document_access(request, document_id)
    try:
        document.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response = FileResponse(
        document.file,
        as_attachment=True,
        filename=document.original_filename,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required(login_url="login")
@require_POST
def personal_document_acknowledge(request, document_id):
    document, attendee = _personal_document_access(request, document_id)
    acknowledgement, created = MeetingDocumentAcknowledgement.objects.get_or_create(
        document=document,
        attendee=attendee,
        is_active=True,
        defaults={
            "created_by": request.user,
            "updated_by": request.user,
        },
    )
    if created:
        messages.success(request, _("Receipt of the meeting document was acknowledged."))
    else:
        messages.info(request, _("You have already acknowledged this meeting document."))
    return redirect("meetings:personal_meeting_workspace")


@login_required(login_url="login")
@require_GET
def meeting_calendar(request):
    _require_view_access(request.user)
    selected_month = _month_value(request.GET.get("month"))
    following_month = _next_month(selected_month)
    meetings = _meeting_queryset(request.user).filter(
        is_active=True,
        event__starts_at__date__gte=selected_month,
        event__starts_at__date__lt=following_month,
    ).order_by("event__starts_at")
    meetings_by_date = defaultdict(list)
    for meeting in meetings:
        meetings_by_date[timezone.localdate(meeting.event.starts_at)].append(meeting)
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(
        selected_month.year,
        selected_month.month,
    ):
        weeks.append([
            {
                "date": day,
                "in_month": day.month == selected_month.month,
                "meetings": meetings_by_date.get(day, []),
            }
            for day in week
        ])
    previous_month = (selected_month - timedelta(days=1)).replace(day=1)
    return render(request, "meetings/meeting_calendar.html", {
        "weeks": weeks,
        "selected_month": selected_month,
        "previous_month": previous_month,
        "next_month": following_month,
        "meeting_count": len(meetings),
    })


@login_required(login_url="login")
@require_GET
def resource_list(request):
    _require_view_access(request.user)
    resources = MeetingResource.objects.annotate(
        booking_count=Count(
            "bookings",
            filter=Q(bookings__is_active=True),
            distinct=True,
        ),
    ).order_by("name_sw", "code")
    return render(request, "meetings/resource_list.html", {
        "resources": resources,
        "can_manage": _can_manage(request.user),
    })


@login_required(login_url="login")
def resource_create(request):
    _require_manager(request.user)
    form = MeetingResourceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        resource = form.save(commit=False)
        resource.created_by = request.user
        resource.updated_by = request.user
        resource.save()
        messages.success(request, _("The meeting resource was created."))
        return redirect("meetings:resource_list")
    return render(request, "meetings/resource_form.html", {
        "form": form,
        "page_title": _("Create meeting resource"),
        "submit_label": _("Create resource"),
    })


@login_required(login_url="login")
def resource_edit(request, resource_id):
    _require_manager(request.user)
    resource = get_object_or_404(MeetingResource, pk=resource_id)
    form = MeetingResourceForm(request.POST or None, instance=resource)
    if request.method == "POST" and form.is_valid():
        resource = form.save(commit=False)
        resource.updated_by = request.user
        resource.save()
        messages.success(request, _("The meeting resource was updated."))
        return redirect("meetings:resource_list")
    return render(request, "meetings/resource_form.html", {
        "form": form,
        "resource": resource,
        "page_title": _("Edit meeting resource"),
        "submit_label": _("Save resource changes"),
    })


@login_required(login_url="login")
@require_GET
def series_list(request):
    _require_view_access(request.user)
    series = MeetingSeries.objects.select_related("venue").annotate(
        occurrence_count=Count("meetings", distinct=True),
    ).order_by("name_sw", "code")
    return render(request, "meetings/series_list.html", {
        "series_list": series,
        "can_manage": _can_manage(request.user),
    })


@login_required(login_url="login")
def series_create(request):
    _require_manager(request.user)
    form = MeetingSeriesForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        series = form.save(commit=False)
        series.created_by = request.user
        series.updated_by = request.user
        series.save()
        messages.success(request, _("The meeting series was created successfully."))
        return redirect("meetings:series_detail", series_id=series.pk)
    return render(request, "meetings/series_form.html", {
        "form": form,
        "page_title": _("Create meeting series"),
        "submit_label": _("Create series"),
    })


@login_required(login_url="login")
def series_edit(request, series_id):
    _require_manager(request.user)
    series = get_object_or_404(MeetingSeries, pk=series_id)
    form = MeetingSeriesForm(request.POST or None, instance=series)
    if request.method == "POST" and form.is_valid():
        series = form.save(commit=False)
        series.updated_by = request.user
        series.save()
        messages.success(request, _("The meeting series was updated successfully."))
        return redirect("meetings:series_detail", series_id=series.pk)
    return render(request, "meetings/series_form.html", {
        "form": form,
        "series": series,
        "page_title": _("Edit meeting series"),
        "submit_label": _("Save series changes"),
    })


@login_required(login_url="login")
@require_GET
def series_detail(request, series_id):
    _require_view_access(request.user)
    series = get_object_or_404(
        MeetingSeries.objects.select_related("venue").prefetch_related(
            "agenda_templates", "meetings__event",
        ),
        pk=series_id,
    )
    return render(request, "meetings/series_detail.html", {
        "series": series,
        "agenda_templates": series.agenda_templates.filter(is_active=True),
        "occurrences": series.meetings.filter(is_active=True).select_related(
            "event",
        ).order_by("-event__starts_at"),
        "agenda_form": MeetingSeriesAgendaTemplateForm(),
        "can_manage": _can_manage(request.user),
    })


@login_required(login_url="login")
@require_POST
def series_agenda_add(request, series_id):
    _require_manager(request.user)
    series = get_object_or_404(MeetingSeries, pk=series_id, is_active=True)
    form = MeetingSeriesAgendaTemplateForm(request.POST)
    if form.is_valid():
        template = form.save(commit=False)
        template.series = series
        template.created_by = request.user
        template.updated_by = request.user
        template.save()
        messages.success(request, _("The reusable agenda item was added."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{series.get_absolute_url()}#agenda-template")


@login_required(login_url="login")
def series_occurrence_create(request, series_id):
    _require_manager(request.user)
    series = get_object_or_404(MeetingSeries, pk=series_id, is_active=True)
    form = MeetingOccurrenceForm(request.POST or None, series=series)
    if request.method == "POST" and form.is_valid():
        meeting = form.save(request.user)
        messages.success(
            request,
            _("The next meeting occurrence was scheduled successfully."),
        )
        return redirect("meetings:meeting_detail", meeting_id=meeting.pk)
    return render(request, "meetings/series_occurrence_form.html", {
        "form": form,
        "series": series,
    })


@login_required(login_url="login")
@require_GET
def action_report(request):
    _require_view_access(request.user)
    actions, selected_status, selected_meeting = _report_actions(request)
    all_actions = MeetingActionItem.objects.filter(
        is_active=True,
        meeting__is_active=True,
        meeting__event__in=events_visible_to(request.user),
    )
    closed_statuses = {
        MeetingActionItem.Status.COMPLETED,
        MeetingActionItem.Status.CANCELLED,
    }
    overdue_excluded_statuses = closed_statuses | {
        MeetingActionItem.Status.AWAITING_REVIEW,
    }
    context = {
        "actions": actions,
        "selected_status": selected_status,
        "selected_meeting": selected_meeting,
        "meetings": _meeting_queryset(request.user).filter(
            is_active=True,
        ).order_by("-event__starts_at"),
        "status_choices": MeetingActionItem.Status.choices,
        "summary": {
            "total": all_actions.count(),
            "open": all_actions.exclude(status__in=closed_statuses).count(),
            "completed": all_actions.filter(
                status=MeetingActionItem.Status.COMPLETED,
            ).count(),
            "overdue": all_actions.filter(
                Q(status=MeetingActionItem.Status.OVERDUE)
                | Q(due_date__lt=timezone.localdate()),
            ).exclude(status__in=overdue_excluded_statuses).count(),
        },
    }
    return render(request, "meetings/action_report.html", context)


@login_required(login_url="login")
@require_GET
def action_review_center(request):
    _require_manager(request.user)
    pending_actions = MeetingActionItem.objects.select_related(
        "meeting", "meeting__event", "responsible_user",
    ).prefetch_related(
        Prefetch(
            "progress_updates",
            queryset=MeetingActionProgressUpdate.objects.filter(
                is_active=True,
                status=MeetingActionItem.Status.AWAITING_REVIEW,
            ).select_related("created_by"),
            to_attr="review_submissions",
        ),
    ).filter(
        is_active=True,
        meeting__is_active=True,
        meeting__event__in=events_visible_to(request.user),
        status=MeetingActionItem.Status.AWAITING_REVIEW,
    )
    search_query = request.GET.get("q", "").strip()
    selected_meeting = request.GET.get("meeting", "").strip()
    if search_query:
        pending_actions = pending_actions.filter(
            Q(meeting__reference_number__icontains=search_query)
            | Q(description_sw__icontains=search_query)
            | Q(description_en__icontains=search_query)
            | Q(responsible_name__icontains=search_query)
        )
    if selected_meeting.isdigit():
        pending_actions = pending_actions.filter(meeting_id=selected_meeting)
    else:
        selected_meeting = ""
    now = timezone.now()
    action_rows = list(pending_actions.order_by("updated_at", "due_date")[:200])
    for action in action_rows:
        action.latest_submission = (
            action.review_submissions[0] if action.review_submissions else None
        )
        submitted_at = (
            action.latest_submission.reported_at
            if action.latest_submission
            else action.updated_at
        )
        action.review_wait_days = max((now - submitted_at).days, 0)
    all_pending = MeetingActionItem.objects.filter(
        is_active=True,
        meeting__is_active=True,
        meeting__event__in=events_visible_to(request.user),
        status=MeetingActionItem.Status.AWAITING_REVIEW,
    )
    return render(request, "meetings/action_review_center.html", {
        "actions": action_rows,
        "search_query": search_query,
        "selected_meeting": selected_meeting,
        "meetings": Meeting.objects.filter(
            is_active=True,
            event__in=events_visible_to(request.user),
            action_items__status=MeetingActionItem.Status.AWAITING_REVIEW,
            action_items__is_active=True,
        ).select_related("event").distinct().order_by("reference_number"),
        "recent_reviews": MeetingActionCompletionReview.objects.filter(
            is_active=True,
            action__meeting__is_active=True,
            action__meeting__event__in=events_visible_to(request.user),
        ).select_related(
            "action", "action__meeting", "created_by",
        )[:30],
        "summary": {
            "pending": all_pending.count(),
            "returned": MeetingActionCompletionReview.objects.filter(
                is_active=True,
                action__meeting__event__in=events_visible_to(request.user),
                outcome=MeetingActionCompletionReview.Outcome.RETURNED,
            ).count(),
            "verified": MeetingActionCompletionReview.objects.filter(
                is_active=True,
                action__meeting__event__in=events_visible_to(request.user),
                outcome=MeetingActionCompletionReview.Outcome.VERIFIED,
            ).count(),
            "waiting_over_three_days": sum(
                action.review_wait_days > 3 for action in action_rows
            ),
        },
    })


@login_required(login_url="login")
@require_GET
def action_report_csv(request):
    _require_view_access(request.user)
    actions, _selected_status, _selected_meeting = _report_actions(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")
    response["Content-Disposition"] = (
        'attachment; filename="meeting-action-report.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        _("Meeting reference"), _("Meeting"), _("Action number"),
        _("Action"), _("Responsible person"), _("Due date"),
        _("Status"), _("Progress notes"),
    ])
    language = request.LANGUAGE_CODE
    for action in actions:
        description = (
            action.description_en
            if language == "en" and action.description_en
            else action.description_sw
        )
        status = _("Overdue") if action.is_report_overdue else action.get_status_display()
        writer.writerow([_safe_csv_value(value) for value in (
            action.meeting.reference_number,
            action.meeting.event.title_en if language == "en" else action.meeting.event.title_sw,
            action.action_number,
            description,
            action.responsible_name,
            action.due_date.isoformat() if action.due_date else "",
            status,
            action.progress_notes,
        )])
    return response


@login_required(login_url="login")
@require_GET
def follow_up_center(request):
    _require_view_access(request.user)
    today = timezone.localdate()
    now = timezone.now()
    next_week = today + timedelta(days=7)
    closed_statuses = {
        MeetingActionItem.Status.COMPLETED,
        MeetingActionItem.Status.CANCELLED,
        MeetingActionItem.Status.AWAITING_REVIEW,
    }
    open_actions = MeetingActionItem.objects.select_related(
        "meeting", "meeting__event", "responsible_user",
    ).filter(
        is_active=True,
        meeting__is_active=True,
        meeting__event__in=events_visible_to(request.user),
        due_date__isnull=False,
    ).exclude(status__in=closed_statuses).annotate(
        reminder_count=Count(
            "communications",
            filter=Q(
                communications__communication_type=MeetingCommunicationLog.CommunicationType.ACTION_REMINDER,
            ),
            distinct=True,
        ),
        escalation_count=Count(
            "communications",
            filter=Q(
                communications__communication_type=MeetingCommunicationLog.CommunicationType.ACTION_ESCALATION,
            ),
            distinct=True,
        ),
        last_contact_at=Max(
            "communications__sent_at",
            filter=Q(
                communications__communication_type__in={
                    MeetingCommunicationLog.CommunicationType.ACTION_REMINDER,
                    MeetingCommunicationLog.CommunicationType.ACTION_ESCALATION,
                },
            ),
        ),
    )
    overdue_queryset = open_actions.filter(due_date__lt=today).order_by("due_date")
    overdue_total = overdue_queryset.count()
    overdue_actions = list(overdue_queryset[:100])
    for action in overdue_actions:
        action.days_overdue = (today - action.due_date).days
    due_soon_queryset = open_actions.filter(
        due_date__gte=today,
        due_date__lte=next_week,
    ).order_by("due_date")
    due_soon_total = due_soon_queryset.count()
    due_soon_actions = list(due_soon_queryset[:100])
    for action in due_soon_actions:
        action.days_until_due = (action.due_date - today).days
    upcoming_queryset = Meeting.objects.select_related(
        "event", "event__venue",
    ).filter(
        is_active=True,
        event__in=events_visible_to(request.user),
        event__starts_at__gt=now,
        event__starts_at__lte=now + timedelta(days=7),
    ).exclude(event__status=Event.Status.CANCELLED).annotate(
        confirmed_total=Count(
            "attendees",
            filter=Q(
                attendees__is_active=True,
                attendees__response_status=MeetingAttendee.ResponseStatus.ACCEPTED,
            ),
            distinct=True,
        ),
        tentative_total=Count(
            "attendees",
            filter=Q(
                attendees__is_active=True,
                attendees__response_status=MeetingAttendee.ResponseStatus.TENTATIVE,
            ),
            distinct=True,
        ),
        pending_total=Count(
            "attendees",
            filter=Q(
                attendees__is_active=True,
                attendees__response_status=MeetingAttendee.ResponseStatus.INVITED,
            ),
            distinct=True,
        ),
        reminder_sent_total=Count(
            "communications",
            filter=Q(
                communications__communication_type=MeetingCommunicationLog.CommunicationType.MEETING_REMINDER,
                communications__delivery_status=MeetingCommunicationLog.DeliveryStatus.SENT,
            ),
            distinct=True,
        ),
    ).order_by("event__starts_at")
    upcoming_total = upcoming_queryset.count()
    upcoming_meetings = list(upcoming_queryset[:50])
    failed_queryset = MeetingCommunicationLog.objects.select_related(
        "meeting", "meeting__event",
    ).filter(
        is_active=True,
        delivery_status=MeetingCommunicationLog.DeliveryStatus.FAILED,
    ).order_by("-sent_at")
    failed_total = failed_queryset.count()
    failed_deliveries = failed_queryset[:25]
    return render(request, "meetings/follow_up_center.html", {
        "overdue_actions": overdue_actions,
        "due_soon_actions": due_soon_actions,
        "upcoming_meetings": upcoming_meetings,
        "failed_deliveries": failed_deliveries,
        "summary": {
            "overdue": overdue_total,
            "due_soon": due_soon_total,
            "upcoming": upcoming_total,
            "failed": failed_total,
        },
        "can_manage": _can_manage(request.user),
    })


def _meeting_readiness_checks(meeting):
    access_ready = bool(
        (
            meeting.attendance_mode == Meeting.AttendanceMode.ONLINE
            or meeting.event.venue_id
        )
        and (
            meeting.attendance_mode == Meeting.AttendanceMode.IN_PERSON
            or (meeting.online_platform and meeting.online_join_url)
        )
    )
    required_participants = meeting.quorum_required or 1
    participant_ready = meeting.readiness_participant_total >= required_participants
    confirmations_ready = meeting.readiness_accepted_total >= required_participants
    invitations_ready = bool(
        meeting.readiness_participant_total
        and meeting.readiness_invitation_total >= meeting.readiness_participant_total
    )
    resources_ready = bool(
        not meeting.readiness_resource_total
        or meeting.readiness_confirmed_resource_total
        >= meeting.readiness_resource_total
    )
    return [
        {
            "label": _("Meeting objectives"),
            "passed": bool(meeting.objectives_sw.strip() or meeting.objectives_en.strip()),
            "success": _("Meeting objectives are recorded."),
            "action": _("Add the purpose and objectives of the meeting."),
        },
        {
            "label": _("Venue and online access"),
            "passed": access_ready,
            "success": _("Venue and access details are complete."),
            "action": _("Complete the venue or online joining details."),
        },
        {
            "label": _("Agenda preparation"),
            "passed": meeting.readiness_agenda_total > 0,
            "success": _("The meeting agenda has been prepared."),
            "action": _("Add at least one agenda item."),
        },
        {
            "label": _("Invitation list"),
            "passed": participant_ready,
            "success": _("The required participants are on the invitation list."),
            "action": _("Add enough participants to meet the required quorum."),
        },
        {
            "label": _("Invitation delivery"),
            "passed": invitations_ready,
            "success": _("All participant invitations have been sent."),
            "action": _("Send all pending participant invitations."),
        },
        {
            "label": _("Attendance confirmations"),
            "passed": confirmations_ready,
            "success": _("The required attendance has been confirmed."),
            "action": _("Follow up pending responses until quorum is confirmed."),
        },
        {
            "label": _("Meeting resources"),
            "passed": resources_ready,
            "success": _("All requested resources are confirmed."),
            "action": _("Resolve all pending meeting resource requests."),
        },
        {
            "label": _("Participant meeting pack"),
            "passed": meeting.readiness_pack_total > 0,
            "success": _("Participant documents have been released."),
            "action": _("Release at least one non-confidential participant document."),
        },
    ]


@login_required(login_url="login")
@require_GET
def readiness_center(request):
    _require_view_access(request.user)
    selected_period = request.GET.get("period", "30").strip()
    if selected_period not in {"7", "30", "90", "ALL"}:
        selected_period = "30"
    selected_type = request.GET.get("type", "").strip().upper()
    now = timezone.now()
    meetings = Meeting.objects.select_related(
        "event", "event__venue",
    ).filter(
        is_active=True,
        event__in=events_visible_to(request.user),
        event__starts_at__gte=now,
    ).exclude(
        event__status__in={Event.Status.CANCELLED, Event.Status.COMPLETED},
    )
    if selected_period != "ALL":
        meetings = meetings.filter(
            event__starts_at__lte=now + timedelta(days=int(selected_period)),
        )
    if selected_type in Meeting.MeetingType.values:
        meetings = meetings.filter(meeting_type=selected_type)
    else:
        selected_type = ""
    meetings = meetings.annotate(
        readiness_agenda_total=Count(
            "agenda_items",
            filter=Q(agenda_items__is_active=True),
            distinct=True,
        ),
        readiness_participant_total=Count(
            "attendees",
            filter=Q(attendees__is_active=True),
            distinct=True,
        ),
        readiness_invitation_total=Count(
            "attendees",
            filter=Q(
                attendees__is_active=True,
                attendees__invitation_sent_at__isnull=False,
            ),
            distinct=True,
        ),
        readiness_accepted_total=Count(
            "attendees",
            filter=Q(
                attendees__is_active=True,
                attendees__response_status=MeetingAttendee.ResponseStatus.ACCEPTED,
            ),
            distinct=True,
        ),
        readiness_resource_total=Count(
            "resource_bookings",
            filter=Q(
                resource_bookings__is_active=True,
                resource_bookings__status__in={
                    MeetingResourceBooking.Status.REQUESTED,
                    MeetingResourceBooking.Status.CONFIRMED,
                },
            ),
            distinct=True,
        ),
        readiness_confirmed_resource_total=Count(
            "resource_bookings",
            filter=Q(
                resource_bookings__is_active=True,
                resource_bookings__status=MeetingResourceBooking.Status.CONFIRMED,
            ),
            distinct=True,
        ),
        readiness_pack_total=Count(
            "documents",
            filter=Q(
                documents__is_active=True,
                documents__is_confidential=False,
            ),
            distinct=True,
        ),
    ).order_by("event__starts_at")
    rows = list(meetings[:200])
    summary = {"total": len(rows), "ready": 0, "attention": 0, "critical": 0}
    for meeting in rows:
        meeting.readiness_checks = _meeting_readiness_checks(meeting)
        passed = sum(check["passed"] for check in meeting.readiness_checks)
        meeting.readiness_score = int((passed * 100) / len(meeting.readiness_checks))
        meeting.readiness_blockers = len(meeting.readiness_checks) - passed
        if meeting.readiness_score == 100:
            meeting.readiness_code = "ready"
            meeting.readiness_label = _("Ready")
            summary["ready"] += 1
        elif meeting.readiness_score >= 50:
            meeting.readiness_code = "attention"
            meeting.readiness_label = _("Needs attention")
            summary["attention"] += 1
        else:
            meeting.readiness_code = "critical"
            meeting.readiness_label = _("Critical gaps")
            summary["critical"] += 1
    return render(request, "meetings/readiness_center.html", {
        "meetings": rows,
        "summary": summary,
        "selected_period": selected_period,
        "selected_type": selected_type,
        "meeting_type_choices": Meeting.MeetingType.choices,
        "can_manage": _can_manage(request.user),
    })


@login_required(login_url="login")
@require_GET
def meeting_print(request, meeting_id):
    _require_view_access(request.user)
    meeting = get_object_or_404(_meeting_queryset(request.user), pk=meeting_id, is_active=True)
    attendees = meeting.attendees.filter(is_active=True).order_by("full_name")
    present_count = attendees.filter(
        attendance_status=MeetingAttendee.AttendanceStatus.PRESENT,
    ).count()
    feedback_summary = meeting.feedback_responses.filter(
        is_active=True,
    ).aggregate(count=Count("id"), overall_rating=Avg("overall_rating"))
    return render(request, "meetings/meeting_print.html", {
        "meeting": meeting,
        "agenda_items": meeting.agenda_items.filter(is_active=True),
        "attendees": attendees,
        "decisions": meeting.decisions.filter(is_active=True),
        "action_items": meeting.action_items.filter(is_active=True),
        "documents": meeting.documents.filter(is_active=True),
        "resource_bookings": meeting.resource_bookings.filter(
            is_active=True,
        ).select_related("resource"),
        "present_count": present_count,
        "feedback_summary": feedback_summary,
        "quorum_met": (
            present_count >= meeting.quorum_required
            if meeting.quorum_required
            else None
        ),
    })


@login_required(login_url="login")
def meeting_create(request):
    _require_manager(request.user)
    form = MeetingWorkflowForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        meeting = form.save(request.user)
        messages.success(request, _("The meeting was created successfully."))
        return redirect("meetings:meeting_detail", meeting_id=meeting.pk)
    return render(request, "meetings/meeting_form.html", {
        "form": form,
        "page_title": _("Create meeting"),
        "submit_label": _("Create meeting and continue"),
    })


@login_required(login_url="login")
def meeting_edit(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(_meeting_queryset(request.user), pk=meeting_id, is_active=True)
    form = MeetingWorkflowForm(request.POST or None, instance=meeting)
    if request.method == "POST" and form.is_valid():
        meeting = form.save(request.user)
        messages.success(request, _("The meeting details were updated successfully."))
        return redirect("meetings:meeting_detail", meeting_id=meeting.pk)
    return render(request, "meetings/meeting_form.html", {
        "form": form,
        "meeting": meeting,
        "page_title": _("Edit meeting"),
        "submit_label": _("Save meeting changes"),
    })


@login_required(login_url="login")
def meeting_detail(request, meeting_id):
    _require_view_access(request.user)
    meeting = get_object_or_404(_meeting_queryset(request.user), pk=meeting_id, is_active=True)
    attendees = meeting.attendees.filter(is_active=True).select_related(
        "checked_in_by",
    ).order_by("full_name")
    actions_queryset = meeting.action_items.filter(is_active=True).order_by(
        "action_number",
    )
    open_action_count = actions_queryset.exclude(
        status__in={
            MeetingActionItem.Status.COMPLETED,
            MeetingActionItem.Status.CANCELLED,
        },
    ).count()
    actions = list(actions_queryset)
    for action in actions:
        action.progress_history = list(
            action.progress_updates.filter(is_active=True).select_related(
                "created_by",
            )[:10]
        )
        action.completion_review_history = list(
            action.completion_reviews.filter(is_active=True).select_related(
                "created_by",
            )[:10]
        )
    present_count = attendees.filter(
        attendance_status=MeetingAttendee.AttendanceStatus.PRESENT,
    ).count()
    checkin_allowed, checkin_message = _meeting_checkin_state(meeting)
    feedbacks = meeting.feedback_responses.filter(is_active=True).select_related(
        "attendee",
    )
    feedback_summary = feedbacks.aggregate(
        count=Count("id"),
        overall_rating=Avg("overall_rating"),
        organization_rating=Avg("organization_rating"),
        content_rating=Avg("content_rating"),
        facilitation_rating=Avg("facilitation_rating"),
        venue_platform_rating=Avg("venue_platform_rating"),
    )
    feedback_rows = list(feedbacks)
    meeting_evaluation_statistics = []
    for field_name, label, average_key in (
        ("overall_rating", _("Overall meeting rating"), "overall_rating"),
        ("organization_rating", _("Organization and logistics"), "organization_rating"),
        ("content_rating", _("Agenda and content"), "content_rating"),
        ("facilitation_rating", _("Chairing and facilitation"), "facilitation_rating"),
        ("venue_platform_rating", _("Venue or online platform"), "venue_platform_rating"),
    ):
        counts = Counter(getattr(item, field_name) for item in feedback_rows)
        total = len(feedback_rows)
        meeting_evaluation_statistics.append({
            "label": label,
            "average": feedback_summary[average_key],
            "rows": [
                {
                    "label": f"{rating} / 5",
                    "count": counts[rating],
                    "percentage": round(counts[rating] * 100 / total, 1) if total else 0,
                    "color_index": rating,
                }
                for rating in range(1, 6)
            ],
        })
    closure_blockers = _meeting_closure_blockers(meeting)
    context = {
        "meeting": meeting,
        "agenda_items": meeting.agenda_items.filter(is_active=True),
        "attendees": attendees,
        "decisions": meeting.decisions.filter(is_active=True),
        "action_items": actions,
        "can_manage": _can_manage(request.user),
        "can_record_attendance": _can_record_attendance(request.user),
        "can_approve_minutes": _can_approve_minutes(request.user),
        "can_edit_minutes": (
            _can_manage(request.user)
            and meeting.minutes_status not in {
                Meeting.MinutesStatus.SUBMITTED,
                Meeting.MinutesStatus.APPROVED,
            }
        ),
        "participant_count": attendees.count(),
        "accepted_count": attendees.filter(
            response_status=MeetingAttendee.ResponseStatus.ACCEPTED,
        ).count(),
        "present_count": present_count,
        "checkin_allowed": checkin_allowed,
        "checkin_message": checkin_message,
        "quorum_met": (
            present_count >= meeting.quorum_required
            if meeting.quorum_required
            else None
        ),
        "open_action_count": open_action_count,
        "response_choices": MeetingAttendee.ResponseStatus.choices,
        "attendance_choices": MeetingAttendee.AttendanceStatus.choices,
        "action_status_choices": MeetingActionItem.Status.choices,
        "agenda_form": MeetingAgendaItemForm(),
        "attendee_form": MeetingAttendeeForm(),
        "minutes_form": MeetingMinutesForm(instance=meeting),
        "minutes_approval_form": MinutesApprovalForm(),
        "minutes_return_form": MinutesReturnForm(),
        "minutes_reviews": meeting.minutes_reviews.filter(is_active=True)[:20],
        "decision_form": MeetingDecisionForm(
            meeting=meeting,
            instance=MeetingDecision(meeting=meeting),
        ),
        "action_form": MeetingActionItemForm(
            meeting=meeting,
            instance=MeetingActionItem(meeting=meeting),
        ),
        "action_completion_review_form": ActionCompletionReviewForm(),
        "document_form": MeetingDocumentForm(
            meeting=meeting,
            instance=MeetingDocument(meeting=meeting),
        ),
        "documents": meeting.documents.filter(is_active=True).select_related(
            "agenda_item", "created_by",
        ).annotate(
            acknowledgement_count=Count(
                "acknowledgements",
                filter=Q(acknowledgements__is_active=True),
                distinct=True,
            ),
        ),
        "resource_booking_form": MeetingResourceBookingForm(
            meeting=meeting,
            instance=MeetingResourceBooking(meeting=meeting),
        ),
        "resource_bookings": meeting.resource_bookings.filter(
            is_active=True,
        ).select_related("resource", "confirmed_by"),
        "communications": meeting.communications.filter(is_active=True)[:50],
        "feedback_responses": feedback_rows[:30],
        "feedback_summary": feedback_summary,
        "meeting_evaluation_statistics": meeting_evaluation_statistics,
        "closure_blockers": closure_blockers,
        "can_close_meeting": bool(
            _can_manage(request.user)
            and not closure_blockers
            and meeting.closure_status != Meeting.ClosureStatus.CLOSED
        ),
        "closure_form": MeetingClosureForm(initial={
            "closure_summary_sw": meeting.closure_summary_sw,
            "closure_summary_en": meeting.closure_summary_en,
        }),
    }
    return render(request, "meetings/meeting_detail.html", context)


@login_required(login_url="login")
@require_POST
def resource_booking_add(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    form = MeetingResourceBookingForm(
        request.POST,
        meeting=meeting,
        instance=MeetingResourceBooking(meeting=meeting),
    )
    if form.is_valid():
        booking = form.save(commit=False)
        booking.meeting = meeting
        booking.created_by = request.user
        booking.updated_by = request.user
        booking.save()
        messages.success(request, _("The resource booking was requested."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#logistics")


@login_required(login_url="login")
@require_POST
@transaction.atomic
def resource_booking_update(request, meeting_id, booking_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    booking = get_object_or_404(
        MeetingResourceBooking.objects.select_for_update().select_related(
            "resource", "meeting__event",
        ),
        pk=booking_id,
        meeting=meeting,
        is_active=True,
    )
    action = request.POST.get("action", "").upper()
    if action == "CONFIRM":
        booking.status = MeetingResourceBooking.Status.CONFIRMED
        booking.confirmed_by = request.user
        booking.confirmed_at = timezone.now()
        success_message = _("The resource booking was confirmed.")
    elif action == "DECLINE":
        booking.status = MeetingResourceBooking.Status.DECLINED
        booking.confirmed_by = request.user
        booking.confirmed_at = timezone.now()
        success_message = _("The resource booking was marked unavailable.")
    elif action == "CANCEL":
        booking.status = MeetingResourceBooking.Status.CANCELLED
        booking.confirmed_by = None
        booking.confirmed_at = None
        success_message = _("The resource booking was cancelled.")
    else:
        raise PermissionDenied
    booking.updated_by = request.user
    try:
        booking.save()
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(request, success_message)
    return redirect(f"{meeting.get_absolute_url()}#logistics")


@login_required(login_url="login")
@require_POST
def document_add(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    form = MeetingDocumentForm(
        request.POST,
        request.FILES,
        meeting=meeting,
        instance=MeetingDocument(meeting=meeting),
    )
    if form.is_valid():
        document = form.save(commit=False)
        document.meeting = meeting
        document.original_filename = request.FILES["file"].name[:255]
        document.created_by = request.user
        document.updated_by = request.user
        document.save()
        messages.success(request, _("The meeting document was uploaded successfully."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#documents")


@login_required(login_url="login")
@require_GET
def document_download(request, meeting_id, document_id):
    _require_view_access(request.user)
    document = get_object_or_404(
        MeetingDocument.objects.select_related("meeting"),
        pk=document_id,
        meeting_id=meeting_id,
        meeting__is_active=True,
        is_active=True,
    )
    try:
        document.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response = FileResponse(
        document.file,
        as_attachment=True,
        filename=document.original_filename,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required(login_url="login")
@require_GET
def minutes_document_download(request, meeting_id):
    _require_view_access(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    if not meeting.minutes_document:
        raise Http404
    try:
        meeting.minutes_document.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response = FileResponse(
        meeting.minutes_document,
        as_attachment=True,
        filename=Path(meeting.minutes_document.name).name,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required(login_url="login")
@require_POST
def document_archive(request, meeting_id, document_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    document = get_object_or_404(
        MeetingDocument,
        pk=document_id,
        meeting=meeting,
        is_active=True,
    )
    document.is_active = False
    document.updated_by = request.user
    document.save(update_fields=["is_active", "updated_by", "updated_at"])
    messages.success(request, _("The meeting document was archived."))
    return redirect(f"{meeting.get_absolute_url()}#documents")


@login_required(login_url="login")
@require_POST
def agenda_add(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    form = MeetingAgendaItemForm(request.POST)
    if form.is_valid():
        agenda = form.save(commit=False)
        agenda.meeting = meeting
        agenda.created_by = request.user
        agenda.updated_by = request.user
        agenda.save()
        messages.success(request, _("The agenda item was added."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#agenda")


@login_required(login_url="login")
@require_POST
def attendee_add(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    form = MeetingAttendeeForm(request.POST)
    if form.is_valid():
        attendee = form.save(commit=False)
        attendee.meeting = meeting
        attendee.created_by = request.user
        attendee.updated_by = request.user
        attendee.save()
        messages.success(request, _("The participant was added to the invitation list."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#participants")


@login_required(login_url="login")
@require_POST
def attendee_update(request, meeting_id, attendee_id):
    if not _can_record_attendance(request.user):
        raise PermissionDenied
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    attendee = get_object_or_404(
        MeetingAttendee,
        pk=attendee_id,
        meeting=meeting,
        is_active=True,
    )
    manager = _can_manage(request.user)
    form_class = AttendeeProgressForm if manager else AttendanceOnlyForm
    form = form_class(request.POST)
    if form.is_valid():
        if manager:
            new_response = form.cleaned_data["response_status"]
            if new_response != attendee.response_status:
                attendee.response_status = new_response
                attendee.responded_at = timezone.now()
        new_attendance = form.cleaned_data["attendance_status"]
        attendee.attendance_status = new_attendance
        attendee.checked_in_at = (
            timezone.now()
            if new_attendance == MeetingAttendee.AttendanceStatus.PRESENT
            else None
        )
        attendee.checked_in_by = (
            request.user
            if new_attendance == MeetingAttendee.AttendanceStatus.PRESENT
            else None
        )
        attendee.checkin_method = (
            MeetingAttendee.CheckinMethod.MANUAL
            if new_attendance == MeetingAttendee.AttendanceStatus.PRESENT
            else ""
        )
        attendee.updated_by = request.user
        attendee.save()
        messages.success(request, _("The participant status was updated."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#participants")


@login_required(login_url="login")
@require_POST
def invitation_send(request, meeting_id, attendee_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    attendee = get_object_or_404(
        MeetingAttendee,
        pk=attendee_id,
        meeting=meeting,
        is_active=True,
    )
    try:
        delivered = send_meeting_invitation(attendee, request=request)
        if delivered:
            messages.success(request, _("The meeting invitation was sent."))
        else:
            messages.error(request, _("The email service did not confirm delivery."))
    except Exception as error:
        messages.error(
            request,
            _("The invitation could not be sent: %(error)s") % {"error": str(error)},
        )
    return redirect(f"{meeting.get_absolute_url()}#participants")


@login_required(login_url="login")
@require_POST
def invitation_bulk_send(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    attendees = meeting.attendees.filter(
        is_active=True,
        invitation_sent_at__isnull=True,
    ).exclude(email="")
    sent = 0
    failed = 0
    for attendee in attendees:
        try:
            sent += int(send_meeting_invitation(attendee, request=request))
        except Exception:
            failed += 1
    messages.success(
        request,
        _("Invitations sent: %(sent)s; failed: %(failed)s.") % {
            "sent": sent,
            "failed": failed,
        },
    )
    return redirect(f"{meeting.get_absolute_url()}#communications")


@login_required(login_url="login")
@require_POST
def rsvp_reminder_send(request, meeting_id, attendee_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    attendee = get_object_or_404(
        MeetingAttendee,
        pk=attendee_id,
        meeting=meeting,
        is_active=True,
    )
    try:
        delivered = send_rsvp_reminder(attendee, request=request)
        if delivered:
            messages.success(request, _("The attendance reminder was sent."))
        else:
            messages.error(request, _("The email service did not confirm delivery."))
    except Exception as error:
        messages.error(
            request,
            _("The reminder could not be sent: %(error)s") % {"error": str(error)},
        )
    return redirect(f"{meeting.get_absolute_url()}#participants")


@login_required(login_url="login")
@require_POST
def rsvp_reminder_bulk_send(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    attendees = meeting.attendees.filter(
        is_active=True,
        invitation_sent_at__isnull=False,
        response_status__in={
            MeetingAttendee.ResponseStatus.INVITED,
            MeetingAttendee.ResponseStatus.TENTATIVE,
        },
    ).exclude(email="")
    sent = 0
    failed = 0
    for attendee in attendees:
        try:
            sent += int(send_rsvp_reminder(attendee, request=request))
        except Exception:
            failed += 1
    messages.success(
        request,
        _("Attendance reminders sent: %(sent)s; failed: %(failed)s.") % {
            "sent": sent,
            "failed": failed,
        },
    )
    return redirect(f"{meeting.get_absolute_url()}#communications")


@login_required(login_url="login")
@require_POST
def meeting_reminder_bulk_send(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    attendees = meeting.attendees.filter(
        is_active=True,
        response_status__in={
            MeetingAttendee.ResponseStatus.ACCEPTED,
            MeetingAttendee.ResponseStatus.TENTATIVE,
        },
    ).exclude(email="")
    sent = 0
    failed = 0
    for attendee in attendees:
        try:
            sent += int(send_upcoming_meeting_reminder(attendee, request=request))
        except Exception:
            failed += 1
    messages.success(
        request,
        _("Upcoming meeting reminders sent: %(sent)s; failed: %(failed)s.") % {
            "sent": sent,
            "failed": failed,
        },
    )
    return redirect(f"{meeting.get_absolute_url()}#communications")


@login_required(login_url="login")
@require_POST
def action_reminder_send(request, meeting_id, action_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    action = get_object_or_404(
        MeetingActionItem.objects.select_related("responsible_user"),
        pk=action_id,
        meeting=meeting,
        is_active=True,
    )
    try:
        delivered = send_action_reminder(action, request=request)
        if delivered:
            messages.success(request, _("The action reminder was sent."))
        else:
            messages.error(request, _("The email service did not confirm delivery."))
    except Exception as error:
        messages.error(
            request,
            _("The reminder could not be sent: %(error)s") % {"error": str(error)},
        )
    return redirect(f"{meeting.get_absolute_url()}#actions")


@login_required(login_url="login")
@require_POST
def action_reminder_bulk_send(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    actions = meeting.action_items.select_related("responsible_user").filter(
        is_active=True,
        due_date__isnull=False,
        due_date__lte=timezone.localdate() + timedelta(days=7),
    ).exclude(
        status__in={
            MeetingActionItem.Status.AWAITING_REVIEW,
            MeetingActionItem.Status.COMPLETED,
            MeetingActionItem.Status.CANCELLED,
        },
    )
    sent = 0
    failed = 0
    for action in actions:
        if not action.responsible_email and not (
            action.responsible_user_id and action.responsible_user.email
        ):
            continue
        try:
            sent += int(send_action_reminder(action, request=request))
        except Exception:
            failed += 1
    messages.success(
        request,
        _("Action reminders sent: %(sent)s; failed: %(failed)s.") % {
            "sent": sent,
            "failed": failed,
        },
    )
    return redirect(f"{meeting.get_absolute_url()}#communications")


@login_required(login_url="login")
@require_POST
def action_escalation_send(request, meeting_id, action_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    action = get_object_or_404(
        MeetingActionItem.objects.select_related("responsible_user", "meeting__event"),
        pk=action_id,
        meeting=meeting,
        is_active=True,
    )
    try:
        delivered = send_action_escalation(action, request=request)
        if delivered:
            messages.success(request, _("The overdue action escalation was sent."))
        else:
            messages.error(request, _("The email service did not confirm delivery."))
    except Exception as error:
        messages.error(
            request,
            _("The escalation could not be sent: %(error)s") % {"error": str(error)},
        )
    return redirect("meetings:follow_up_center")


@login_required(login_url="login")
@require_POST
def action_escalation_bulk_send(request):
    _require_manager(request.user)
    actions = MeetingActionItem.objects.select_related(
        "responsible_user", "meeting", "meeting__event",
    ).filter(
        is_active=True,
        meeting__is_active=True,
        due_date__lt=timezone.localdate(),
    ).exclude(
        status__in={
            MeetingActionItem.Status.AWAITING_REVIEW,
            MeetingActionItem.Status.COMPLETED,
            MeetingActionItem.Status.CANCELLED,
        },
    )
    sent = 0
    failed = 0
    skipped = 0
    for action in actions:
        if not action.responsible_email and not (
            action.responsible_user_id and action.responsible_user.email
        ):
            skipped += 1
            continue
        try:
            sent += int(send_action_escalation(action, request=request))
        except Exception:
            failed += 1
    messages.success(
        request,
        _("Overdue escalations sent: %(sent)s; failed: %(failed)s; without email: %(skipped)s.") % {
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
        },
    )
    return redirect("meetings:follow_up_center")


@login_required(login_url="login")
@require_POST
def minutes_update(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    if meeting.minutes_status in {
        Meeting.MinutesStatus.SUBMITTED,
        Meeting.MinutesStatus.APPROVED,
    }:
        raise PermissionDenied
    form = MeetingMinutesForm(request.POST, request.FILES, instance=meeting)
    if form.is_valid():
        minutes = form.save(commit=False)
        minutes.minutes_status = Meeting.MinutesStatus.DRAFT
        minutes.minutes_approved_by = None
        minutes.minutes_approved_at = None
        minutes.updated_by = request.user
        minutes.save()
        messages.success(request, _("The draft meeting minutes were saved."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#minutes")


def _record_minutes_review(meeting, action, user, comment=""):
    return MeetingMinutesReview.objects.create(
        meeting=meeting,
        action=action,
        comment=comment.strip(),
        created_by=user,
        updated_by=user,
    )


@login_required(login_url="login")
@require_POST
@transaction.atomic
def minutes_submit(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(
        Meeting.objects.select_for_update(),
        pk=meeting_id,
        is_active=True,
    )
    if meeting.minutes_status != Meeting.MinutesStatus.DRAFT:
        messages.error(request, _("Only draft minutes can be submitted for approval."))
    elif not (
        meeting.minutes_sw.strip()
        or meeting.minutes_en.strip()
        or meeting.minutes_document
    ):
        messages.error(request, _("Record the meeting minutes before submitting them."))
    else:
        meeting.minutes_status = Meeting.MinutesStatus.SUBMITTED
        meeting.minutes_approved_by = None
        meeting.minutes_approved_at = None
        meeting.updated_by = request.user
        meeting.save(update_fields=[
            "minutes_status", "minutes_approved_by", "minutes_approved_at",
            "updated_by", "updated_at",
        ])
        _record_minutes_review(
            meeting,
            MeetingMinutesReview.Action.SUBMITTED,
            request.user,
        )
        messages.success(request, _("The minutes were submitted for approval."))
    return redirect(f"{meeting.get_absolute_url()}#minutes")


@login_required(login_url="login")
@require_POST
@transaction.atomic
def minutes_approve(request, meeting_id):
    _require_minutes_approver(request.user)
    meeting = get_object_or_404(
        Meeting.objects.select_for_update(),
        pk=meeting_id,
        is_active=True,
    )
    form = MinutesApprovalForm(request.POST)
    if meeting.minutes_status != Meeting.MinutesStatus.SUBMITTED:
        messages.error(request, _("Only submitted minutes can be approved."))
    elif form.is_valid():
        meeting.minutes_status = Meeting.MinutesStatus.APPROVED
        meeting.minutes_approved_by = request.user
        meeting.minutes_approved_at = timezone.now()
        meeting.updated_by = request.user
        meeting.save(update_fields=[
            "minutes_status", "minutes_approved_by", "minutes_approved_at",
            "updated_by", "updated_at",
        ])
        _record_minutes_review(
            meeting,
            MeetingMinutesReview.Action.APPROVED,
            request.user,
            form.cleaned_data["comment"],
        )
        messages.success(request, _("The meeting minutes were approved and locked."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#minutes")


@login_required(login_url="login")
@require_POST
@transaction.atomic
def minutes_return(request, meeting_id):
    _require_minutes_approver(request.user)
    meeting = get_object_or_404(
        Meeting.objects.select_for_update(),
        pk=meeting_id,
        is_active=True,
    )
    form = MinutesReturnForm(request.POST)
    if meeting.minutes_status != Meeting.MinutesStatus.SUBMITTED:
        messages.error(request, _("Only submitted minutes can be returned."))
    elif form.is_valid():
        meeting.minutes_status = Meeting.MinutesStatus.RETURNED
        meeting.minutes_approved_by = None
        meeting.minutes_approved_at = None
        meeting.updated_by = request.user
        meeting.save(update_fields=[
            "minutes_status", "minutes_approved_by", "minutes_approved_at",
            "updated_by", "updated_at",
        ])
        _record_minutes_review(
            meeting,
            MeetingMinutesReview.Action.RETURNED,
            request.user,
            form.cleaned_data["comment"],
        )
        messages.success(request, _("The minutes were returned for correction."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#minutes")


@login_required(login_url="login")
@require_POST
@transaction.atomic
def minutes_reopen(request, meeting_id):
    _require_minutes_approver(request.user)
    meeting = get_object_or_404(
        Meeting.objects.select_for_update(),
        pk=meeting_id,
        is_active=True,
    )
    form = MinutesReturnForm(request.POST)
    if meeting.minutes_status != Meeting.MinutesStatus.APPROVED:
        messages.error(request, _("Only approved minutes can be reopened."))
    elif form.is_valid():
        meeting.minutes_status = Meeting.MinutesStatus.RETURNED
        meeting.minutes_approved_by = None
        meeting.minutes_approved_at = None
        meeting.updated_by = request.user
        meeting.save(update_fields=[
            "minutes_status", "minutes_approved_by", "minutes_approved_at",
            "updated_by", "updated_at",
        ])
        _record_minutes_review(
            meeting,
            MeetingMinutesReview.Action.REOPENED,
            request.user,
            form.cleaned_data["comment"],
        )
        messages.success(request, _("The approved minutes were reopened for correction."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#minutes")


@login_required(login_url="login")
@require_POST
def decision_add(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    form = MeetingDecisionForm(
        request.POST,
        meeting=meeting,
        instance=MeetingDecision(meeting=meeting),
    )
    if form.is_valid():
        decision = form.save(commit=False)
        decision.meeting = meeting
        decision.created_by = request.user
        decision.updated_by = request.user
        decision.save()
        messages.success(request, _("The meeting decision was recorded."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#decisions")


@login_required(login_url="login")
@require_POST
def action_add(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    form = MeetingActionItemForm(
        request.POST,
        meeting=meeting,
        instance=MeetingActionItem(meeting=meeting),
    )
    if form.is_valid():
        action = form.save(commit=False)
        action.meeting = meeting
        action.created_by = request.user
        action.updated_by = request.user
        action.save()
        messages.success(request, _("The action item was assigned."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#actions")


@login_required(login_url="login")
@require_POST
@transaction.atomic
def action_update(request, meeting_id, action_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    action = get_object_or_404(
        MeetingActionItem,
        pk=action_id,
        meeting=meeting,
        is_active=True,
    )
    if action.status == MeetingActionItem.Status.AWAITING_REVIEW:
        messages.error(
            request,
            _("Use the completion review controls for an action awaiting verification."),
        )
        return redirect(f"{meeting.get_absolute_url()}#actions")
    form = ActionProgressForm(request.POST)
    if form.is_valid():
        action.status = form.cleaned_data["status"]
        action.progress_notes = form.cleaned_data["progress_notes"]
        action.completion_percentage = form.cleaned_data["completion_percentage"]
        action.completed_at = (
            timezone.now()
            if action.status == MeetingActionItem.Status.COMPLETED
            else None
        )
        action.updated_by = request.user
        action.save()
        MeetingActionProgressUpdate.objects.create(
            action=action,
            status=action.status,
            completion_percentage=action.completion_percentage,
            notes=action.progress_notes,
            created_by=request.user,
            updated_by=request.user,
        )
        messages.success(request, _("The action progress was updated."))
    else:
        messages.error(request, _form_error_message(form))
    return redirect(f"{meeting.get_absolute_url()}#actions")


def invitation_response(request, response_token):
    attendee = get_object_or_404(
        MeetingAttendee.objects.select_related(
            "meeting__event", "meeting__event__venue",
        ),
        response_token=response_token,
        is_active=True,
        meeting__is_active=True,
    )
    form = InvitationResponseForm(
        request.POST or None,
        initial={"response_status": attendee.response_status},
    )
    submitted = False
    if request.method == "POST" and form.is_valid():
        attendee.response_status = form.cleaned_data["response_status"]
        attendee.responded_at = timezone.now()
        attendee.save(update_fields=[
            "response_status", "responded_at", "updated_at",
        ])
        submitted = True
    show_checkin_pass = bool(
        attendee.meeting.checkin_enabled
        and attendee.response_status in {
            MeetingAttendee.ResponseStatus.ACCEPTED,
            MeetingAttendee.ResponseStatus.TENTATIVE,
        }
    )
    checkin_url = (
        _attendee_checkin_url(request, attendee) if show_checkin_pass else ""
    )
    feedback_allowed, _feedback_message = _meeting_feedback_state(
        attendee.meeting,
        attendee,
    )
    has_feedback = MeetingFeedback.objects.filter(
        attendee=attendee,
        is_active=True,
    ).exists()
    return render(request, "meetings/invitation_response.html", {
        "attendee": attendee,
        "meeting": attendee.meeting,
        "form": form,
        "submitted": submitted,
        "checkin_qr": _qr_data_uri(checkin_url) if checkin_url else "",
        "feedback_url": (
            reverse(
                "meetings:meeting_feedback",
                kwargs={"response_token": attendee.response_token},
            )
            if feedback_allowed or has_feedback
            else ""
        ),
    })


@login_required(login_url="login")
@require_GET
def attendee_pass(request, meeting_id, attendee_id):
    if not _can_record_attendance(request.user):
        raise PermissionDenied
    attendee = get_object_or_404(
        MeetingAttendee.objects.select_related("meeting__event"),
        pk=attendee_id,
        meeting_id=meeting_id,
        is_active=True,
        meeting__is_active=True,
    )
    checkin_url = _attendee_checkin_url(request, attendee)
    return render(request, "meetings/attendee_pass.html", {
        "attendee": attendee,
        "meeting": attendee.meeting,
        "checkin_qr": _qr_data_uri(checkin_url),
    })


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def attendee_checkin(request, response_token):
    if not _can_record_attendance(request.user):
        raise PermissionDenied
    attendee = get_object_or_404(
        MeetingAttendee.objects.select_related(
            "meeting__event", "meeting__event__venue", "checked_in_by",
        ),
        response_token=response_token,
        is_active=True,
        meeting__is_active=True,
    )
    checkin_allowed, checkin_message = _meeting_checkin_state(attendee.meeting)
    if attendee.response_status == MeetingAttendee.ResponseStatus.DECLINED:
        checkin_allowed = False
        checkin_message = _(
            "This participant declined the invitation and cannot be checked in."
        )
    just_checked_in = False
    automatic = request.method == "GET" and request.GET.get("auto") == "1"
    if (
        (request.method == "POST" or automatic)
        and checkin_allowed
        and not attendee.checked_in_at
    ):
        with transaction.atomic():
            locked = MeetingAttendee.objects.select_for_update().get(
                pk=attendee.pk,
            )
            if not locked.checked_in_at:
                locked.attendance_status = MeetingAttendee.AttendanceStatus.PRESENT
                locked.checked_in_at = timezone.now()
                locked.checked_in_by = request.user
                locked.checkin_method = MeetingAttendee.CheckinMethod.QR
                locked.updated_by = request.user
                locked.save(update_fields=[
                    "attendance_status", "checked_in_at", "checked_in_by",
                    "checkin_method", "updated_by", "updated_at",
                ])
                just_checked_in = True
            attendee = locked
    elif attendee.checked_in_at:
        checkin_message = _("This participant is already checked in.")
    return render(request, "meetings/attendee_checkin.html", {
        "attendee": attendee,
        "meeting": attendee.meeting,
        "checkin_allowed": checkin_allowed,
        "checkin_message": checkin_message,
        "just_checked_in": just_checked_in,
        "automatic": automatic,
    })


@login_required(login_url="login")
@require_GET
def attendance_register_csv(request, meeting_id):
    _require_view_access(request.user)
    meeting = get_object_or_404(_meeting_queryset(request.user), pk=meeting_id, is_active=True)
    attendees = meeting.attendees.filter(is_active=True).select_related(
        "checked_in_by",
    ).order_by("full_name")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")
    response["Content-Disposition"] = (
        f'attachment; filename="{meeting.reference_number.replace("/", "-")}'
        '-attendance-register.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        _("Meeting reference"), _("Participant"), _("Organization"),
        _("Email address"), _("Phone number"),
        _("Invitation response"), _("Attendance"), _("Checked in at"),
        _("Checked in by"), _("Check-in method"),
    ])
    for attendee in attendees:
        checked_in_by = (
            attendee.checked_in_by.get_full_name().strip()
            or attendee.checked_in_by.username
            if attendee.checked_in_by
            else ""
        )
        writer.writerow([_safe_csv_value(value) for value in (
            meeting.reference_number,
            attendee.full_name,
            attendee.organization,
            attendee.email,
            attendee.phone_number,
            attendee.get_response_status_display(),
            attendee.get_attendance_status_display(),
            timezone.localtime(attendee.checked_in_at).isoformat()
            if attendee.checked_in_at else "",
            checked_in_by,
            attendee.get_checkin_method_display() if attendee.checkin_method else "",
        )])
    return response


@require_http_methods(["GET", "POST"])
def meeting_feedback(request, response_token):
    attendee = get_object_or_404(
        MeetingAttendee.objects.select_related(
            "meeting__event", "meeting__event__venue",
        ),
        response_token=response_token,
        is_active=True,
        meeting__is_active=True,
    )
    meeting = attendee.meeting
    existing = MeetingFeedback.objects.filter(
        attendee=attendee,
        is_active=True,
    ).first()
    feedback_allowed, feedback_message = _meeting_feedback_state(
        meeting,
        attendee,
    )
    form = MeetingFeedbackForm(request.POST or None)
    submitted = existing is not None
    if (
        request.method == "POST"
        and feedback_allowed
        and existing is None
        and form.is_valid()
    ):
        with transaction.atomic():
            locked_attendee = MeetingAttendee.objects.select_for_update().get(
                pk=attendee.pk,
            )
            existing = MeetingFeedback.objects.filter(
                attendee=locked_attendee,
                is_active=True,
            ).first()
            if existing is None:
                feedback = form.save(commit=False)
                feedback.meeting = meeting
                feedback.attendee = locked_attendee
                feedback.save()
                existing = feedback
        submitted = True
    return render(request, "meetings/meeting_feedback.html", {
        "attendee": attendee,
        "meeting": meeting,
        "form": form,
        "feedback": existing,
        "feedback_allowed": feedback_allowed,
        "feedback_message": feedback_message,
        "submitted": submitted,
    })


@login_required(login_url="login")
@require_GET
def feedback_report_csv(request, meeting_id):
    _require_view_access(request.user)
    meeting = get_object_or_404(_meeting_queryset(request.user), pk=meeting_id, is_active=True)
    feedbacks = meeting.feedback_responses.filter(is_active=True).select_related(
        "attendee",
    )
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")
    response["Content-Disposition"] = (
        f'attachment; filename="{meeting.reference_number.replace("/", "-")}'
        '-feedback-report.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        _("Meeting reference"), _("Respondent"), _("Organization and logistics"),
        _("Agenda and content"), _("Chairing and facilitation"),
        _("Venue or online platform"), _("Overall rating"),
        _("Comments"), _("Recommendations"), _("Submitted at"),
    ])
    for feedback in feedbacks:
        respondent = _("Anonymous") if feedback.is_anonymous else feedback.attendee.full_name
        writer.writerow([_safe_csv_value(value) for value in (
            meeting.reference_number,
            respondent,
            feedback.organization_rating,
            feedback.content_rating,
            feedback.facilitation_rating,
            feedback.venue_platform_rating,
            feedback.overall_rating,
            feedback.comments,
            feedback.recommendations,
            timezone.localtime(feedback.submitted_at).isoformat(),
        )])
    return response


@login_required(login_url="login")
@require_POST
def meeting_close(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(_meeting_queryset(request.user), pk=meeting_id, is_active=True)
    if meeting.closure_status == Meeting.ClosureStatus.CLOSED:
        messages.error(request, _("This meeting is already formally closed."))
        return redirect(f"{meeting.get_absolute_url()}#evaluation")
    blockers = _meeting_closure_blockers(meeting)
    if blockers:
        messages.error(request, " ".join(str(blocker) for blocker in blockers))
        return redirect(f"{meeting.get_absolute_url()}#evaluation")
    form = MeetingClosureForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect(f"{meeting.get_absolute_url()}#evaluation")
    with transaction.atomic():
        meeting.closure_status = Meeting.ClosureStatus.CLOSED
        meeting.closure_summary_sw = form.cleaned_data["closure_summary_sw"]
        meeting.closure_summary_en = form.cleaned_data["closure_summary_en"]
        meeting.closed_by = request.user
        meeting.closed_at = timezone.now()
        meeting.updated_by = request.user
        meeting.save()
        meeting.event.status = Event.Status.COMPLETED
        meeting.event.updated_by = request.user
        meeting.event.save(update_fields=["status", "updated_by", "updated_at"])
    messages.success(request, _("The meeting was formally closed."))
    return redirect(f"{meeting.get_absolute_url()}#evaluation")


@login_required(login_url="login")
@require_POST
def meeting_reopen(request, meeting_id):
    _require_manager(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, is_active=True)
    if meeting.closure_status != Meeting.ClosureStatus.CLOSED:
        messages.error(request, _("This meeting is not formally closed."))
        return redirect(f"{meeting.get_absolute_url()}#evaluation")
    meeting.closure_status = Meeting.ClosureStatus.OPEN
    meeting.closed_by = None
    meeting.closed_at = None
    meeting.updated_by = request.user
    meeting.save()
    messages.success(request, _("The meeting was reopened for post-meeting work."))
    return redirect(f"{meeting.get_absolute_url()}#evaluation")
