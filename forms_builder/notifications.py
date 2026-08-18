from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from .models import EventForm, EventReminder, FormSubmission, NotificationLog, Payment
from .services import participant_certificate_path


def _absolute_url(path, request=None):
    if settings.PUBLIC_BASE_URL:
        return f"{settings.PUBLIC_BASE_URL}/{path.lstrip('/')}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def _notification_content(submission, notification_type, request=None):
    language = submission.language if submission.language in {"sw", "en"} else "sw"
    event = submission.event_form.event
    event_name = event.title_en if language == "en" else event.title_sw
    with translation.override(language):
        status_path = reverse(
            "forms_builder:participant_portal",
            kwargs={"participant_token": submission.participant_token},
        )
        status_url = _absolute_url(status_path, request=request)
        if notification_type == NotificationLog.NotificationType.REGISTRATION_RECEIVED:
            subject = _("Registration received — %(event)s") % {"event": event_name}
            body = _(
                "We have received your registration for %(event)s.\n\n"
                "Reference number: %(reference)s\n"
                "Check status: %(status_url)s"
            ) % {
                "event": event_name,
                "reference": submission.reference_number,
                "status_url": status_url,
            }
        elif notification_type == NotificationLog.NotificationType.REGISTRATION_APPROVED:
            subject = _("Registration approved — %(event)s") % {"event": event_name}
            body = _(
                "Your registration for %(event)s has been approved.\n\n"
                "Reference number: %(reference)s\n"
                "Check status: %(status_url)s"
            ) % {
                "event": event_name,
                "reference": submission.reference_number,
                "status_url": status_url,
            }
        elif notification_type == NotificationLog.NotificationType.REGISTRATION_REJECTED:
            subject = _("Registration update — %(event)s") % {"event": event_name}
            body = _(
                "Your registration for %(event)s was not approved. "
                "Please contact the event organizer if you need assistance.\n\n"
                "Reference number: %(reference)s\n"
                "Check status: %(status_url)s"
            ) % {
                "event": event_name,
                "reference": submission.reference_number,
                "status_url": status_url,
            }
        elif notification_type == NotificationLog.NotificationType.CERTIFICATE_AUTHORIZED:
            subject = _("Certificate available — %(event)s") % {"event": event_name}
            certificate_url = _absolute_url(
                participant_certificate_path(submission, language=language),
                request=request,
            )
            body = _(
                "Your certificate for %(event)s is now available.\n\n"
                "Reference number: %(reference)s\nCertificate: %(certificate_url)s"
            ) % {
                "event": event_name,
                "reference": submission.reference_number,
                "certificate_url": certificate_url,
            }
        elif notification_type == NotificationLog.NotificationType.CERTIFICATE_DENIED:
            subject = _("Certificate decision — %(event)s") % {"event": event_name}
            portal_path = reverse(
                "forms_builder:participant_portal",
                kwargs={"participant_token": submission.participant_token},
            )
            portal_url = _absolute_url(portal_path, request=request)
            reason = submission.certificate_record.denial_reason
            body = _(
                "Your certificate was not authorized.\n\n"
                "Event: %(event)s\n"
                "Reference number: %(reference)s\n"
                "Reason: %(reason)s\n"
                "View certificate status: %(portal_url)s"
            ) % {
                "event": event_name,
                "reference": submission.reference_number,
                "reason": reason,
                "portal_url": portal_url,
            }
        else:
            subject = _("Check-in confirmed — %(event)s") % {"event": event_name}
            body = _(
                "Your attendance at %(event)s has been confirmed.\n\n"
                "Reference number: %(reference)s"
            ) % {
                "event": event_name,
                "reference": submission.reference_number,
            }

    return subject, body


def send_submission_notification(submission, notification_type, request=None):
    if submission.event_form.form_type == EventForm.FormType.EVALUATION:
        return None

    recipient = submission.submitter_email.strip()
    subject, body = _notification_content(
        submission,
        notification_type,
        request=request,
    )
    log = NotificationLog.objects.create(
        submission=submission,
        notification_type=notification_type,
        recipient=recipient,
        subject=subject,
        delivery_status=NotificationLog.DeliveryStatus.SKIPPED,
    )

    if not recipient:
        log.error_message = _("No participant email address was provided.")
        log.save(update_fields=["error_message", "updated_at"])
        return log

    try:
        delivered = send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        if delivered:
            log.delivery_status = NotificationLog.DeliveryStatus.SENT
            log.sent_at = timezone.now()
        else:
            log.delivery_status = NotificationLog.DeliveryStatus.FAILED
            log.error_message = _("The email backend did not confirm delivery.")
    except Exception as error:
        log.delivery_status = NotificationLog.DeliveryStatus.FAILED
        log.error_message = str(error)[:2000]

    log.save(
        update_fields=[
            "delivery_status",
            "error_message",
            "sent_at",
            "updated_at",
        ]
    )
    return log


def send_payment_notification(payment, notification_type, request=None):
    submission = payment.submission
    language = submission.language if submission.language in {"sw", "en"} else "sw"
    event = submission.event_form.event
    event_name = event.title_en if language == "en" else event.title_sw
    payment_path = reverse(
        "forms_builder:participant_payment",
        kwargs={"participant_token": submission.participant_token},
    )
    payment_url = _absolute_url(payment_path, request=request)
    with translation.override(language):
        if notification_type == NotificationLog.NotificationType.PAYMENT_VERIFIED:
            subject = _("Payment verified — %(event)s") % {"event": event_name}
            message = _("Your payment has been verified successfully.")
        elif notification_type == NotificationLog.NotificationType.PAYMENT_REJECTED:
            subject = _("Payment update — %(event)s") % {"event": event_name}
            message = _("Your payment was rejected. Review the payment details and submit again.")
        else:
            subject = _("Payment received — %(event)s") % {"event": event_name}
            message = _("Your payment information has been received and is awaiting verification.")
        body = _(
            "%(message)s\n\nEvent: %(event)s\nReference number: %(reference)s\n"
            "Amount: %(currency)s %(amount)s\nPayment status: %(payment_url)s"
        ) % {
            "message": message, "event": event_name,
            "reference": submission.reference_number,
            "currency": payment.currency, "amount": f"{payment.amount:,.2f}",
            "payment_url": payment_url,
        }
    recipient = submission.submitter_email.strip()
    log = NotificationLog.objects.create(
        submission=submission, notification_type=notification_type,
        recipient=recipient, subject=subject,
        delivery_status=NotificationLog.DeliveryStatus.SKIPPED,
    )
    if not recipient:
        log.error_message = _("No participant email address was provided.")
    else:
        try:
            delivered = send_mail(
                subject, body, settings.DEFAULT_FROM_EMAIL, [recipient],
                fail_silently=False,
            )
            log.delivery_status = (
                NotificationLog.DeliveryStatus.SENT
                if delivered else NotificationLog.DeliveryStatus.FAILED
            )
            if delivered:
                log.sent_at = timezone.now()
            else:
                log.error_message = _("The email backend did not confirm delivery.")
        except Exception as error:
            log.delivery_status = NotificationLog.DeliveryStatus.FAILED
            log.error_message = str(error)[:2000]
    log.save(update_fields=["delivery_status", "error_message", "sent_at", "updated_at"])
    return log


def send_event_reminder_notification(submission, reminder, request=None):
    language = submission.language if submission.language in {"sw", "en"} else "sw"
    event_name = (
        reminder.event.title_en if language == "en" else reminder.event.title_sw
    )
    subject = reminder.subject_en if language == "en" else reminder.subject_sw
    custom_message = reminder.message_en if language == "en" else reminder.message_sw
    recipient = submission.submitter_email.strip()

    with translation.override(language):
        body = _(
            "%(message)s\n\n"
            "Event: %(event)s\n"
            "Reference number: %(reference)s"
        ) % {
            "message": custom_message,
            "event": event_name,
            "reference": submission.reference_number,
        }

    log = NotificationLog.objects.create(
        submission=submission,
        event_reminder=reminder,
        notification_type=NotificationLog.NotificationType.EVENT_REMINDER,
        recipient=recipient,
        subject=subject,
        delivery_status=NotificationLog.DeliveryStatus.SKIPPED,
    )
    if not recipient:
        log.error_message = _("No participant email address was provided.")
        log.save(update_fields=["error_message", "updated_at"])
        return log

    try:
        delivered = send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        if delivered:
            log.delivery_status = NotificationLog.DeliveryStatus.SENT
            log.sent_at = timezone.now()
        else:
            log.delivery_status = NotificationLog.DeliveryStatus.FAILED
            log.error_message = _("The email backend did not confirm delivery.")
    except Exception as error:
        log.delivery_status = NotificationLog.DeliveryStatus.FAILED
        log.error_message = str(error)[:2000]
    log.save(
        update_fields=[
            "delivery_status",
            "error_message",
            "sent_at",
            "updated_at",
        ]
    )
    return log


def process_event_reminder(reminder, request=None, force=False):
    with transaction.atomic():
        locked_reminder = EventReminder.objects.select_for_update().get(
            pk=reminder.pk
        )
        if locked_reminder.status in {
            EventReminder.Status.PROCESSING,
            EventReminder.Status.COMPLETED,
        }:
            return locked_reminder
        if not force and locked_reminder.status != EventReminder.Status.SCHEDULED:
            return locked_reminder
        locked_reminder.status = EventReminder.Status.PROCESSING
        locked_reminder.save(update_fields=["status", "updated_at"])

    submissions = FormSubmission.objects.filter(
        event_form__event=locked_reminder.event,
        event_form__form_type__in=[
            EventForm.FormType.REGISTRATION,
            EventForm.FormType.EXHIBITOR,
            EventForm.FormType.SPEAKER,
        ],
        review_status=FormSubmission.ReviewStatus.APPROVED,
        is_active=True,
        is_complete=True,
    ).select_related("event_form__event")
    counts = {
        NotificationLog.DeliveryStatus.SENT: 0,
        NotificationLog.DeliveryStatus.SKIPPED: 0,
        NotificationLog.DeliveryStatus.FAILED: 0,
    }
    for submission in submissions.iterator():
        log = send_event_reminder_notification(
            submission,
            locked_reminder,
            request=request,
        )
        counts[log.delivery_status] += 1

    locked_reminder.status = EventReminder.Status.COMPLETED
    locked_reminder.sent_count = counts[NotificationLog.DeliveryStatus.SENT]
    locked_reminder.skipped_count = counts[
        NotificationLog.DeliveryStatus.SKIPPED
    ]
    locked_reminder.failed_count = counts[NotificationLog.DeliveryStatus.FAILED]
    locked_reminder.processed_at = timezone.now()
    locked_reminder.save(
        update_fields=[
            "status",
            "sent_count",
            "skipped_count",
            "failed_count",
            "processed_at",
            "updated_at",
        ]
    )
    return locked_reminder


def process_due_reminders(request=None):
    due_reminders = EventReminder.objects.filter(
        status=EventReminder.Status.SCHEDULED,
        scheduled_for__lte=timezone.now(),
    ).select_related("event").order_by("scheduled_for")
    processed = []
    for reminder in due_reminders:
        result = process_event_reminder(reminder, request=request)
        if result.status == EventReminder.Status.COMPLETED:
            processed.append(result)
    return processed


def resend_notification(log, request=None):
    if (
        log.notification_type == NotificationLog.NotificationType.EVENT_REMINDER
        and log.event_reminder
    ):
        return send_event_reminder_notification(
            log.submission,
            log.event_reminder,
            request=request,
        )
    if log.notification_type in {
        NotificationLog.NotificationType.PAYMENT_RECEIVED,
        NotificationLog.NotificationType.PAYMENT_VERIFIED,
        NotificationLog.NotificationType.PAYMENT_REJECTED,
    }:
        payment = log.submission.payments.order_by("-created_at").first()
        if payment:
            return send_payment_notification(
                payment, log.notification_type, request=request,
            )
    return send_submission_notification(
        log.submission,
        log.notification_type,
        request=request,
    )

