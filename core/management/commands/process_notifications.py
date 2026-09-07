from django.core.management.base import BaseCommand
from core.notification_service import process_pending_notifications


class Command(BaseCommand):
    help = "Deliver pending or retryable email and SMS notifications."

    def handle(self, *args, **options):
        sent = process_pending_notifications()
        self.stdout.write(self.style.SUCCESS(f"Delivered {sent} notification(s)."))
