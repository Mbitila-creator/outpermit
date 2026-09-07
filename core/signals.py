from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from tasks.models import Task, TaskAssignment
from finance.models import FinanceRequest

from .notification_service import queue_user_notification


@receiver(pre_save, sender=Task)
def remember_task_approval_status(sender, instance, **kwargs):
    instance._notification_previous_approval = None
    if instance.pk:
        instance._notification_previous_approval = sender.objects.filter(
            pk=instance.pk
        ).values_list("approval_status", flat=True).first()


@receiver(post_save, sender=Task)
def notify_task_approval(sender, instance, created, **kwargs):
    previous = getattr(instance, "_notification_previous_approval", None)
    if instance.approval_status == "PENDING" and instance.approver_id and (created or previous != "PENDING"):
        queue_user_notification(
            instance.approver, "TASK_APPROVAL_REQUIRED", "Task awaiting approval",
            f'The task proposal "{instance.title}" is awaiting your decision.',
        )
    elif (
        instance.proposed_by_id and previous
        and previous != instance.approval_status
        and instance.approval_status in {"APPROVED", "REJECTED"}
    ):
        queue_user_notification(
            instance.proposed_by, f"TASK_{instance.approval_status}",
            "Task proposal update",
            f'Your task proposal "{instance.title}" was {instance.get_approval_status_display().lower()}.',
        )


@receiver(pre_save, sender=FinanceRequest)
def remember_finance_status(sender, instance, **kwargs):
    instance._notification_previous_status = None
    if instance.pk:
        instance._notification_previous_status = sender.objects.filter(
            pk=instance.pk
        ).values_list("status", flat=True).first()


@receiver(post_save, sender=TaskAssignment)
def notify_task_assignment(sender, instance, created, **kwargs):
    if created:
        queue_user_notification(
            instance.assigned_to, "TASK_ASSIGNED", "New task assigned",
            f'You have been assigned the task "{instance.task.title}".',
        )


@receiver(post_save, sender=FinanceRequest)
def notify_finance_request_change(sender, instance, created, **kwargs):
    previous = getattr(instance, "_notification_previous_status", None)
    if (
        instance.requested_by_id
        and instance.status != "DRAFT"
        and (created or previous != instance.status)
    ):
        queue_user_notification(
            instance.requested_by, f"FINANCE_{instance.status}",
            "Finance request update",
            f"Your finance request {instance.request_no} is now {instance.get_status_display()}.",
        )
