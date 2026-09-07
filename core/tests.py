from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from tasks.models import Task, TaskAssignment

from .models import Notification
from .notification_service import queue_user_notification


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="recipient", email="recipient@example.test"
        )

    def test_email_is_delivered_and_logged(self):
        records = queue_user_notification(
            self.user, "TEST_EVENT", "Test subject", "Test message",
            channels={"EMAIL"},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(records[0].status, Notification.Status.SENT)
        self.assertEqual(records[0].attempts, 1)

    @override_settings(SMS_BACKEND="core.sms_backends.DisabledSMSBackend")
    def test_unconfigured_sms_failure_is_logged_without_breaking_workflow(self):
        self.user.profile.phone_number = "+255700000000"
        self.user.profile.save(update_fields=["phone_number"])
        record = queue_user_notification(
            self.user, "SMS_TEST", "", "Message", channels={"SMS"}
        )[0]
        self.assertEqual(record.status, Notification.Status.FAILED)
        self.assertIn("not configured", record.last_error)

    def test_task_assignment_queues_notification(self):
        creator = User.objects.create_user(username="creator")
        task = Task.objects.create(title="Prepare brief", created_by=creator)
        TaskAssignment.objects.create(
            task=task, assigned_to=self.user, assigned_by=creator
        )
        record = Notification.objects.get(event_key="TASK_ASSIGNED")
        self.assertEqual(record.recipient_user, self.user)
        self.assertEqual(record.status, Notification.Status.SENT)
