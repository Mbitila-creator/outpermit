import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from forms_builder.models import EventForm, FormSubmission


class Command(BaseCommand):
    help = "Preview or apply chronological registration-reference renumbering."

    def add_arguments(self, parser):
        parser.add_argument("event_code")
        parser.add_argument("form_slug")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the displayed mapping. Without this flag, no data is changed.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        event_form = EventForm.objects.filter(
            event__code__iexact=options["event_code"],
            slug=options["form_slug"],
        ).select_related("event").first()
        if event_form is None:
            raise CommandError("No matching event form was found.")

        submissions = list(
            FormSubmission.objects.filter(event_form=event_form).order_by(
                "created_at", "id"
            )
        )
        prefix = event_form.event.code.replace(" ", "-").upper()
        form_code = event_form.form_type[:3].upper()
        mapping = [
            (submission, f"{prefix}-{form_code}-{position:05d}")
            for position, submission in enumerate(submissions, start=1)
        ]

        if not mapping:
            self.stdout.write("No submissions were found.")
            return

        for submission, new_reference in mapping:
            self.stdout.write(f"{submission.reference_number} -> {new_reference}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING(
                "Preview only. Run the same command with --apply to save these changes."
            ))
            transaction.set_rollback(True)
            return

        for submission, _new_reference in mapping:
            FormSubmission.objects.filter(pk=submission.pk).update(
                reference_number=f"TMP-{uuid.uuid4()}"
            )
        for submission, new_reference in mapping:
            FormSubmission.objects.filter(pk=submission.pk).update(
                reference_number=new_reference
            )

        self.stdout.write(self.style.SUCCESS(
            f"Renumbered {len(mapping)} submissions from {mapping[0][1]} "
            f"through {mapping[-1][1]}."
        ))

