from django.core.management.base import BaseCommand
from forms_builder.notifications import process_due_reminders


class Command(BaseCommand):
    help = "Send scheduled event reminders whose sending time has arrived."

    def handle(self, *args, **options):
        processed_reminders = process_due_reminders()

        for reminder in processed_reminders:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Sent reminder {reminder.pk} for {reminder.event.code}."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {len(processed_reminders)} due reminder(s)."
            )
        )

