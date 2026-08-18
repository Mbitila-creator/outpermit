from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from events.auth import User

from .models import MeetingCommunicationLog


def _absolute_url(path, request=None):
    if settings.PUBLIC_BASE_URL:
        return f"{settings.PUBLIC_BASE_URL}/{path.lstrip('/')}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def _actor(request):
    if request is not None and request.user.is_authenticated:
        return request.user
    return None


def _send_and_log(
    *,
    meeting,
    communication_type,
    recipient_name,
    recipient_email,
    subject,
    body,
    request=None,
    attendee=None,
    action_item=None,
):
    log_values = {
        "meeting": meeting,
        "attendee": attendee,
        "action_item": action_item,
        "communication_type": communication_type,
        "recipient_name": recipient_name,
        "recipient_email": recipient_email,
        "subject": subject,
        "message": body,
        "created_by": _actor(request),
        "updated_by": _actor(request),
    }
    try:
        delivered = send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient_email],
            fail_silently=False,
        )
    except Exception as error:
        MeetingCommunicationLog.objects.create(
            **log_values,
            delivery_status=MeetingCommunicationLog.DeliveryStatus.FAILED,
            error_message=str(error),
        )
        raise
    MeetingCommunicationLog.objects.create(
        **log_values,
        delivery_status=(
            MeetingCommunicationLog.DeliveryStatus.SENT
            if delivered
            else MeetingCommunicationLog.DeliveryStatus.FAILED
        ),
        error_message=(
            "" if delivered else _("The email service did not confirm delivery.")
        ),
    )
    return bool(delivered)


def _meeting_details(meeting, language):
    event = meeting.event
    return {
        "event_name": event.title_en if language == "en" else event.title_sw,
        "meeting_date": date_format(
            timezone.localtime(event.starts_at),
            format="DATETIME_FORMAT",
            use_l10n=True,
        ),
        "venue": str(event.venue) if event.venue else _("To be confirmed"),
    }


def _online_access_details(meeting, language):
    if meeting.attendance_mode == meeting.AttendanceMode.IN_PERSON:
        return ""
    instructions = (
        meeting.online_instructions_en
        if language == "en" and meeting.online_instructions_en
        else meeting.online_instructions_sw
    )
    lines = [
        "",
        _("Online meeting access:"),
        _("Platform: %(platform)s") % {
            "platform": meeting.get_online_platform_display(),
        },
        _("Joining link: %(link)s") % {"link": meeting.online_join_url},
    ]
    if meeting.online_meeting_id:
        lines.append(
            _("Meeting ID: %(meeting_id)s") % {
                "meeting_id": meeting.online_meeting_id,
            }
        )
    if meeting.online_passcode:
        lines.append(
            _("Passcode: %(passcode)s") % {"passcode": meeting.online_passcode}
        )
    if instructions:
        lines.append(_("Joining instructions: %(instructions)s") % {
            "instructions": instructions,
        })
    return "\n".join(lines)


def send_meeting_invitation(attendee, request=None):
    """Send one bilingual-ready invitation and return whether it was delivered."""
    recipient = attendee.email.strip()
    if not recipient:
        raise ValueError(_("Enter an email address before sending the invitation."))

    language = attendee.preferred_language
    meeting = attendee.meeting
    with translation.override(language):
        details = _meeting_details(meeting, language)
        event_name = details["event_name"]
        response_path = reverse(
            "meetings:invitation_response",
            kwargs={"response_token": attendee.response_token},
        )
        response_url = _absolute_url(response_path, request=request)
        subject = _("Meeting invitation — %(meeting)s") % {"meeting": event_name}
        body = _(
            "Dear %(name)s,\n\n"
            "You are invited to attend %(meeting)s.\n\n"
            "Reference: %(reference)s\n"
            "Date and time: %(date)s\n"
            "Venue: %(venue)s\n"
            "%(online_access)s\n"
            "Chairperson: %(chairperson)s\n\n"
            "Confirm your attendance using this secure link:\n%(response_url)s"
        ) % {
            "name": attendee.full_name,
            "meeting": event_name,
            "reference": meeting.reference_number,
            "date": details["meeting_date"],
            "venue": details["venue"],
            "online_access": _online_access_details(meeting, language),
            "chairperson": meeting.chairperson_name,
            "response_url": response_url,
        }
        delivered = _send_and_log(
            meeting=meeting,
            attendee=attendee,
            communication_type=MeetingCommunicationLog.CommunicationType.INVITATION,
            recipient_name=attendee.full_name,
            recipient_email=recipient,
            subject=subject,
            body=body,
            request=request,
        )

    if delivered:
        attendee.invitation_sent_at = timezone.now()
        attendee.updated_by = request.user if request and request.user.is_authenticated else None
        attendee.save(update_fields=[
            "invitation_sent_at", "updated_by", "updated_at",
        ])
    return bool(delivered)


def send_rsvp_reminder(attendee, request=None):
    if attendee.response_status in {
        attendee.ResponseStatus.ACCEPTED,
        attendee.ResponseStatus.DECLINED,
    }:
        raise ValueError(_("This participant has already submitted a final response."))
    recipient = attendee.email.strip()
    if not recipient:
        raise ValueError(_("Enter an email address before sending the reminder."))
    language = attendee.preferred_language
    meeting = attendee.meeting
    with translation.override(language):
        details = _meeting_details(meeting, language)
        response_path = reverse(
            "meetings:invitation_response",
            kwargs={"response_token": attendee.response_token},
        )
        response_url = _absolute_url(response_path, request=request)
        subject = _("Reminder: confirm attendance — %(meeting)s") % {
            "meeting": details["event_name"],
        }
        body = _(
            "Dear %(name)s,\n\n"
            "This is a reminder to confirm whether you will attend %(meeting)s.\n\n"
            "Reference: %(reference)s\n"
            "Date and time: %(date)s\n"
            "Venue: %(venue)s\n"
            "%(online_access)s\n\n"
            "Submit your response using this secure link:\n%(response_url)s"
        ) % {
            "name": attendee.full_name,
            "meeting": details["event_name"],
            "reference": meeting.reference_number,
            "date": details["meeting_date"],
            "venue": details["venue"],
            "online_access": _online_access_details(meeting, language),
            "response_url": response_url,
        }
        return _send_and_log(
            meeting=meeting,
            attendee=attendee,
            communication_type=MeetingCommunicationLog.CommunicationType.RSVP_REMINDER,
            recipient_name=attendee.full_name,
            recipient_email=recipient,
            subject=subject,
            body=body,
            request=request,
        )


def send_upcoming_meeting_reminder(attendee, request=None):
    if attendee.response_status not in {
        attendee.ResponseStatus.ACCEPTED,
        attendee.ResponseStatus.TENTATIVE,
    }:
        raise ValueError(_("Meeting reminders are sent only to confirmed or tentative participants."))
    recipient = attendee.email.strip()
    if not recipient:
        raise ValueError(_("Enter an email address before sending the reminder."))
    language = attendee.preferred_language
    meeting = attendee.meeting
    if meeting.event.starts_at <= timezone.now():
        raise ValueError(_("A reminder cannot be sent after the meeting has started."))
    if meeting.event.status == "CANCELLED":
        raise ValueError(_("A reminder cannot be sent for a cancelled meeting."))
    with translation.override(language):
        details = _meeting_details(meeting, language)
        subject = _("Upcoming meeting reminder — %(meeting)s") % {
            "meeting": details["event_name"],
        }
        body = _(
            "Dear %(name)s,\n\n"
            "This is a reminder that %(meeting)s is approaching.\n\n"
            "Reference: %(reference)s\n"
            "Date and time: %(date)s\n"
            "Venue: %(venue)s\n"
            "%(online_access)s\n\n"
            "Please keep this information available and arrive or join on time."
        ) % {
            "name": attendee.full_name,
            "meeting": details["event_name"],
            "reference": meeting.reference_number,
            "date": details["meeting_date"],
            "venue": details["venue"],
            "online_access": _online_access_details(meeting, language),
        }
        delivered = _send_and_log(
            meeting=meeting,
            attendee=attendee,
            communication_type=MeetingCommunicationLog.CommunicationType.MEETING_REMINDER,
            recipient_name=attendee.full_name,
            recipient_email=recipient,
            subject=subject,
            body=body,
            request=request,
        )
        return delivered


def send_action_reminder(action, request=None):
    if action.status in {
        action.Status.AWAITING_REVIEW,
        action.Status.COMPLETED,
        action.Status.CANCELLED,
    }:
        raise ValueError(_("A reminder cannot be sent for a closed action."))
    recipient = action.responsible_email.strip()
    if not recipient and action.responsible_user_id:
        recipient = action.responsible_user.email.strip()
    if not recipient:
        raise ValueError(_("Enter an email address for the responsible person."))
    language = (
        action.responsible_user.preferred_language
        if action.responsible_user_id
        else "sw"
    )
    meeting = action.meeting
    with translation.override(language):
        details = _meeting_details(meeting, language)
        description = (
            action.description_en
            if language == "en" and action.description_en
            else action.description_sw
        )
        due_date = (
            date_format(action.due_date, format="DATE_FORMAT", use_l10n=True)
            if action.due_date
            else _("Not specified")
        )
        subject = _("Action reminder — %(meeting)s") % {
            "meeting": details["event_name"],
        }
        body = _(
            "Dear %(name)s,\n\n"
            "This is a reminder about an action assigned from %(meeting)s.\n\n"
            "Reference: %(reference)s\n"
            "Action: %(action)s\n"
            "Due date: %(due_date)s\n"
            "Current status: %(status)s\n\n"
            "Please complete the action or provide a progress update."
        ) % {
            "name": action.responsible_name,
            "meeting": details["event_name"],
            "reference": meeting.reference_number,
            "action": description,
            "due_date": due_date,
            "status": action.get_status_display(),
        }
        delivered = _send_and_log(
            meeting=meeting,
            action_item=action,
            communication_type=MeetingCommunicationLog.CommunicationType.ACTION_REMINDER,
            recipient_name=action.responsible_name,
            recipient_email=recipient,
            subject=subject,
            body=body,
            request=request,
        )
        return delivered


def send_action_escalation(action, request=None):
    today = timezone.localdate()
    if action.status in {
        action.Status.AWAITING_REVIEW,
        action.Status.COMPLETED,
        action.Status.CANCELLED,
    }:
        raise ValueError(_("An escalation cannot be sent for a closed action."))
    if not action.due_date or action.due_date >= today:
        raise ValueError(_("Only overdue actions can be escalated."))
    recipient = action.responsible_email.strip()
    if not recipient and action.responsible_user_id:
        recipient = action.responsible_user.email.strip()
    if not recipient:
        raise ValueError(_("Enter an email address for the responsible person."))
    language = (
        action.responsible_user.preferred_language
        if action.responsible_user_id
        else "sw"
    )
    meeting = action.meeting
    days_overdue = (today - action.due_date).days
    with translation.override(language):
        details = _meeting_details(meeting, language)
        description = (
            action.description_en
            if language == "en" and action.description_en
            else action.description_sw
        )
        due_date = date_format(action.due_date, format="DATE_FORMAT", use_l10n=True)
        subject = _("Overdue action escalation — %(meeting)s") % {
            "meeting": details["event_name"],
        }
        body = _(
            "Dear %(name)s,\n\n"
            "This action from %(meeting)s is now %(days)s day(s) overdue and requires immediate attention.\n\n"
            "Reference: %(reference)s\n"
            "Action: %(action)s\n"
            "Due date: %(due_date)s\n"
            "Current status: %(status)s\n\n"
            "Please complete the action or provide a progress update without further delay."
        ) % {
            "name": action.responsible_name,
            "meeting": details["event_name"],
            "days": days_overdue,
            "reference": meeting.reference_number,
            "action": description,
            "due_date": due_date,
            "status": action.get_status_display(),
        }
        delivered = _send_and_log(
            meeting=meeting,
            action_item=action,
            communication_type=MeetingCommunicationLog.CommunicationType.ACTION_ESCALATION,
            recipient_name=action.responsible_name,
            recipient_email=recipient,
            subject=subject,
            body=body,
            request=request,
        )
        if delivered and action.status not in {
            action.Status.OVERDUE,
            action.Status.RETURNED,
        }:
            action.status = action.Status.OVERDUE
            action.updated_by = _actor(request)
            action.save(update_fields=["status", "updated_by", "updated_at"])
        return delivered


def send_action_review_submission_notifications(action, request=None):
    managers = User.objects.filter(
        is_active=True,
        profile__role__in={"ADMIN", "HEAD_OF_UNIT"},
        profile__department=action.meeting.event.owning_department,
    ).exclude(email="")
    if action.responsible_user_id:
        managers = managers.exclude(pk=action.responsible_user_id)
    managers = managers.order_by("pk")
    review_url = _absolute_url(
        reverse("meetings:action_review_center"),
        request=request,
    )
    sent = 0
    failed = 0
    for manager in managers:
        language = manager.preferred_language
        with translation.override(language):
            description = (
                action.description_en
                if language == "en" and action.description_en
                else action.description_sw
            )
            subject = _("Action completion awaiting review — %(reference)s") % {
                "reference": action.meeting.reference_number,
            }
            body = _(
                "Dear %(name)s,\n\n"
                "A responsible officer has submitted a meeting action for completion verification.\n\n"
                "Meeting: %(meeting)s\n"
                "Action: %(action)s\n"
                "Responsible person: %(responsible)s\n\n"
                "Open the Action Review Centre:\n%(review_url)s"
            ) % {
                "name": manager.get_full_name().strip() or manager.username,
                "meeting": action.meeting.reference_number,
                "action": description,
                "responsible": action.responsible_name,
                "review_url": review_url,
            }
            try:
                sent += int(_send_and_log(
                    meeting=action.meeting,
                    action_item=action,
                    communication_type=(
                        MeetingCommunicationLog.CommunicationType.ACTION_REVIEW_SUBMITTED
                    ),
                    recipient_name=manager.get_full_name().strip() or manager.username,
                    recipient_email=manager.email,
                    subject=subject,
                    body=body,
                    request=request,
                ))
            except Exception:
                failed += 1
    return sent, failed


def send_action_review_result_notification(action, review, request=None):
    recipient = action.responsible_email.strip()
    if not recipient and action.responsible_user_id:
        recipient = action.responsible_user.email.strip()
    if not recipient:
        return False
    language = (
        action.responsible_user.preferred_language
        if action.responsible_user_id
        else "sw"
    )
    workspace_url = _absolute_url(
        reverse("meetings:personal_meeting_workspace"),
        request=request,
    )
    with translation.override(language):
        description = (
            action.description_en
            if language == "en" and action.description_en
            else action.description_sw
        )
        subject = _("Action completion review result — %(reference)s") % {
            "reference": action.meeting.reference_number,
        }
        body = _(
            "Dear %(name)s,\n\n"
            "Your meeting action completion submission has been reviewed.\n\n"
            "Meeting: %(meeting)s\n"
            "Action: %(action)s\n"
            "Review result: %(outcome)s\n"
            "Review comment: %(comment)s\n\n"
            "Open your meetings workspace:\n%(workspace_url)s"
        ) % {
            "name": action.responsible_name,
            "meeting": action.meeting.reference_number,
            "action": description,
            "outcome": review.get_outcome_display(),
            "comment": review.comment or _("No additional comment."),
            "workspace_url": workspace_url,
        }
        return _send_and_log(
            meeting=action.meeting,
            action_item=action,
            communication_type=(
                MeetingCommunicationLog.CommunicationType.ACTION_REVIEW_RESULT
            ),
            recipient_name=action.responsible_name,
            recipient_email=recipient,
            subject=subject,
            body=body,
            request=request,
        )
