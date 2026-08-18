from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from forms_builder.models import EventForm

from conferences.guiding_questions import configure_guiding_questions
from conferences.management.commands.setup_conference_registration import (
    EVENT_CODE,
    FORM_SLUG,
)


class Command(BaseCommand):
    help = "Create or update session-dependent conference guiding questions."

    @transaction.atomic
    def handle(self, *args, **options):
        event_form = EventForm.objects.filter(
            event__code=EVENT_CODE,
            slug=FORM_SLUG,
        ).first()
        if event_form is None:
            raise CommandError(
                "Run setup_conference_registration before configuring guiding questions."
            )

        topics = configure_guiding_questions(event_form)
        question_count = sum(topic.questions.filter(is_active=True).count() for topic in topics)
        self.stdout.write(
            self.style.SUCCESS(
                f"Configured {len(topics)} guiding subtopics and {question_count} questions."
            )
        )

