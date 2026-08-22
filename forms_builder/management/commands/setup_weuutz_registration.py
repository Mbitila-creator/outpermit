from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.models import Event
from forms_builder.models import EventForm, FormQuestion, FormSubmission


EVENT_CODE = "WEUUTz-2026"
FORM_SLUG = "exhibition-participant-registration-form"
ROUTING_SECTION_TITLES = {
    "Participation Type",
    "Conference Areas",
    "Other Participation",
}
QUESTION_PLACEHOLDERS = {
    "Institution Name": (
        "mf., Chuo Kikuu cha Dar es Salaam (UDSM)",
        "e.g., University of Dar es Salaam (UDSM)",
    ),
    "Institution Email Address": (
        "mf., info@udsm.ac.tz",
        "e.g., info@udsm.ac.tz",
    ),
    "Institution Phone Number": (
        "mf., 0712 345 678",
        "e.g., 0712 345 678",
    ),
    "Representative Name": (
        "mf., Dkt. Paulina Msuva",
        "e.g., Dr. Paulina Msuva",
    ),
    "Representative Email Address": (
        "mf., paulina.msuva@udsm.ac.tz",
        "e.g., paulina.msuva@udsm.ac.tz",
    ),
    "Representative Phone Number": (
        "mf., 0765 423 189",
        "e.g., 0765 423 189",
    ),
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

        for label_en, (placeholder_sw, placeholder_en) in (
            QUESTION_PLACEHOLDERS.items()
        ):
            FormQuestion.objects.filter(
                section__event_form=event_form,
                label_en=label_en,
            ).update(
                placeholder_sw=placeholder_sw,
                placeholder_en=placeholder_en,
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

        auto_registered = FormSubmission.objects.filter(
            event_form__event=event,
            event_form__form_type__in=[
                EventForm.FormType.REGISTRATION,
                EventForm.FormType.EXHIBITOR,
                EventForm.FormType.SPEAKER,
            ],
            is_active=True,
            is_complete=True,
            review_status=FormSubmission.ReviewStatus.PENDING,
        ).update(review_status=FormSubmission.ReviewStatus.APPROVED)

        self.stdout.write(self.style.SUCCESS(
            f"Configured {event_form.name_en}: {len(active_sections)} continuous "
            "exhibition registration sections; participation routing disabled; "
            f"{auto_registered} existing registration(s) made check-in ready."
        ))
