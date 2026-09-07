from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.module_loading import import_string

from .models import Notification


def user_phone(user):
    profile = getattr(user, "profile", None)
    return (getattr(profile, "phone_number", "") or "").strip()


def queue_user_notification(user, event_key, subject, message, channels=None, send_now=True):
    channels = set(channels or settings.NOTIFICATION_CHANNELS)
    queued = []
    destinations = {
        Notification.Channel.EMAIL: (getattr(user, "email", "") or "").strip(),
        Notification.Channel.SMS: user_phone(user),
    }
    for channel in channels:
        recipient = destinations.get(channel, "")
        notification = Notification.objects.create(
            recipient_user=user, channel=channel, recipient=recipient,
            event_key=event_key, subject=subject, message=message,
            status=Notification.Status.PENDING if recipient else Notification.Status.SKIPPED,
            last_error="" if recipient else f"No {channel.lower()} recipient is configured.",
        )
        queued.append(notification)
        if send_now and recipient:
            deliver_notification(notification)
    return queued


def deliver_notification(notification):
    if notification.status == Notification.Status.SENT:
        return True
    notification.attempts += 1
    try:
        if notification.channel == Notification.Channel.EMAIL:
            delivered = send_mail(
                notification.subject, notification.message,
                settings.DEFAULT_FROM_EMAIL, [notification.recipient], fail_silently=False,
            )
        else:
            backend = import_string(settings.SMS_BACKEND)()
            delivered = backend.send(notification.recipient, notification.message, settings.SMS_FROM)
        if not delivered:
            raise RuntimeError("The notification provider did not confirm delivery.")
        notification.status = Notification.Status.SENT
        notification.sent_at = timezone.now()
        notification.last_error = ""
        success = True
    except Exception as error:
        notification.status = Notification.Status.FAILED
        notification.last_error = str(error)[:2000]
        success = False
    notification.save(update_fields=["attempts", "status", "sent_at", "last_error", "updated_at"])
    return success


def process_pending_notifications():
    maximum = settings.NOTIFICATION_MAX_ATTEMPTS
    queryset = Notification.objects.filter(
        status__in=[Notification.Status.PENDING, Notification.Status.FAILED], attempts__lt=maximum
    ).order_by("created_at")
    return sum(int(deliver_notification(item)) for item in queryset.iterator())
