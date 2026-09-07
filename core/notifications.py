from .notification_service import queue_user_notification


def send_email_notification(user, subject, message, fail_silently=True):
    if not user or not getattr(user, "email", None):
        return False
    notifications = queue_user_notification(
        user, "GENERAL", subject, message, channels={"EMAIL"}, send_now=True
    )
    return bool(notifications and notifications[0].status == "SENT")


def notify_user(user, subject, message):
    if not user:
        return False
    records = queue_user_notification(user, "GENERAL", subject, message)
    return any(record.status == "SENT" for record in records)


def notify_many_users(users, subject, message):
    sent_count = 0

    for user in users:
        if notify_user(user, subject, message):
            sent_count += 1

    return sent_count
