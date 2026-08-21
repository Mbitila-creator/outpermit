from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.models import Event
from forms_builder.models import EventForm, FormQuestion


EVENT_CODE = "WEUUTz-2026"
FORM_SLUG = "exhibition-participant-registration-form"
ROUTING_SECTION_TITLES = {
    "Participation Type",
    "Conference Areas",
    "Other Participation",
}


class Command(BaseCommand):
    help = (
        "Remove participation routing from the WEUUTz registration form and "
        "show its exhibition sections continuously."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required before updating the WEUUTz registration form.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Run again with --confirm to apply the changes.")

        event = Event.objects.filter(code__iexact=EVENT_CODE).first()
        if event is None:
            raise CommandError(f"The {EVENT_CODE} event was not found.")

        event_form = event.forms.filter(slug=FORM_SLUG).first()
        if event_form is None:
            raise CommandError(
                f"The {EVENT_CODE} exhibition registration form was not found."
            )

        routing_sections = event_form.sections.filter(
            title_en__in=ROUTING_SECTION_TITLES,
        )
        participation_section = routing_sections.filter(
            title_en="Participation Type",
        ).first()
        participation_question = None
        if participation_section is not None:
            participation_question = participation_section.questions.filter(
                label_en=(
                    "In which part(s) of the event do you intend to participate?"
                ),
            ).first()
            participation_section.questions.update(is_active=False)

        for section in routing_sections:
            section.is_active = False
            section.condition_question = None
            section.condition_value = ""
            section.save(update_fields=[
                "is_active", "condition_question", "condition_value", "updated_at",
            ])

        if participation_question is not None:
            FormQuestion.objects.filter(
                section__event_form=event_form,
                condition_question=participation_question,
                condition_value__in=["CONFERENCE", "OTHER"],
            ).update(is_active=False)
            FormQuestion.objects.filter(
                section__event_form=event_form,
                condition_question=participation_question,
                condition_value="EXHIBITION",
            ).update(condition_question=None, condition_value="")
            event_form.sections.filter(
                condition_question=participation_question,
            ).update(condition_question=None, condition_value="")

        active_sections = list(
            event_form.sections.filter(is_active=True).order_by(
                "display_order", "pk",
            )
        )
        for display_order, section in enumerate(active_sections, start=1):
            update_fields = []
            if section.display_order != display_order:
                section.display_order = display_order
                update_fields.append("display_order")
            if section.condition_question_id:
                section.condition_question = None
                section.condition_value = ""
                update_fields.extend(["condition_question", "condition_value"])
            if update_fields:
                update_fields.append("updated_at")
                section.save(update_fields=update_fields)

        self.stdout.write(self.style.SUCCESS(
            f"Configured {event_form.name_en}: {len(active_sections)} continuous "
            "exhibition registration sections; participation routing disabled."
        ))
