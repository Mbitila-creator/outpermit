from django.conf import settings
from django.core.mail import send_mail


def send_email_notification(user, subject, message, fail_silently=True):
    if not user or not getattr(user, "email", None):
        return False

    send_mail(
        subject,
        message,
        getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
        [user.email],
        fail_silently=fail_silently,
    )

    return True


def notify_user(user, subject, message):
    return send_email_notification(
        user=user,
        subject=subject,
        message=message,
        fail_silently=True,
    )


def notify_many_users(users, subject, message):
    sent_count = 0

    for user in users:
        if notify_user(user, subject, message):
            sent_count += 1

    return sent_count