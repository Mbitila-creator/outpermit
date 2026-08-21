from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.models import Event
from forms_builder.models import (
    EventForm,
    FormQuestion,
    FormSection,
    QuestionOption,
)


EVENT_CODE = "WEUUTz-2026"

def configure_options(question, options):
    active_values = []
    for order, (value, label_sw, label_en) in enumerate(options, start=1):
        active_values.append(value)
        QuestionOption.objects.update_or_create(
            question=question,
            value=value,
            defaults={
                "label_sw": label_sw,
                "label_en": label_en,
                "display_order": order,
                "is_active": True,
            },
        )
    question.options.exclude(value__in=active_values).update(is_active=False)


def configure_question(form, section, *, label_en, label_sw, question_type,
                       order, required=False, options=(), existing_label_en=None,
                       help_en="", help_sw=""):
    lookup_label = existing_label_en or label_en
    question = FormQuestion.objects.filter(
        section__event_form=form,
        label_en=lookup_label,
    ).first()
    if question is None and lookup_label != label_en:
        question = FormQuestion.objects.filter(
            section__event_form=form,
            label_en=label_en,
        ).first()
    if question is None:
        question = FormQuestion(section=section, label_en=label_en)
    question.section = section
    question.label_en = label_en
    question.label_sw = label_sw
    question.question_type = question_type
    question.display_order = order
    question.is_required = required
    question.help_text_en = help_en
    question.help_text_sw = help_sw
    question.is_active = True
    question.save()
    if options:
        configure_options(question, options)
    return question


class Command(BaseCommand):
    help = "Create or improve only the WEUUTz-2026 exhibition evaluation form."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required before updating the WEUUTz evaluation form.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Run again with --confirm to apply the changes.")

        event = Event.objects.filter(code__iexact=EVENT_CODE).first()
        if event is None:
            raise CommandError(f"The {EVENT_CODE} event was not found.")

        event.evaluation_enabled = True
        event.save(update_fields=["evaluation_enabled", "updated_at"])

        form = event.forms.filter(
            form_type=EventForm.FormType.EVALUATION,
        ).order_by("pk").first()
        if form is None:
            form = EventForm(event=event, form_type=EventForm.FormType.EVALUATION)
        form.name_sw = "Dodoso la Tathmini ya Maadhimisho"
        form.name_en = "Commemoration Evaluation Questionnaire"
        form.slug = "exhibition-evaluation"
        form.introduction_sw = (
            "Tafadhali jaza dodoso hili kwa niaba ya taasisi yako. Taarifa "
            "zitasaidia kutathmini na kuboresha maadhimisho yajayo."
        )
        form.introduction_en = (
            "Please complete this questionnaire on behalf of your institution. "
            "The information will support evaluation and improvement of future commemorations."
        )
        form.success_message_sw = "Asante. Tathmini yako ya WEUUTz imepokelewa."
        form.success_message_en = "Thank you. Your WEUUTz evaluation has been received."
        form.show_event_summary = True
        form.allow_multiple_submissions = False
        form.is_published = True
        form.is_active = True
        form.save()

        preliminary = form.sections.filter(
            title_en__in=("Participants Views", "I. PRELIMINARY INFORMATION")
        ).order_by("pk").first()
        if preliminary is None:
            preliminary, _ = FormSection.objects.get_or_create(
                event_form=form, title_en="PRELIMINARY INFORMATION"
            )
        preliminary.title_sw = "I. TAARIFA ZA AWALI"
        preliminary.title_en = "I. PRELIMINARY INFORMATION"
        preliminary.description_sw = "Taarifa za taasisi inayoshiriki katika maadhimisho."
        preliminary.description_en = "Information about the institution participating in the commemoration."
        preliminary.display_order = 1
        preliminary.is_active = True
        preliminary.save()

        evaluation, _ = FormSection.objects.update_or_create(
            event_form=form,
            title_en="II. EVALUATION AND FOLLOW-UP",
            defaults={
                "title_sw": "II. TATHMINI NA UFUATILIAJI",
                "description_sw": "Tathmini matokeo ya ushiriki wa taasisi yako.",
                "description_en": "Evaluate the outcomes of your institution's participation.",
                "display_order": 2,
                "is_active": True,
            },
        )

        # Retain historical answers while removing superseded questions from
        # the live questionnaire and current management charts.
        FormQuestion.objects.filter(section__event_form=form).update(is_active=False)

        service_options = (
            ("RESEARCH", "Utafiti", "Research"),
            ("TRAINING", "Mafunzo", "Training"),
            ("AGENCY", "Uwakala", "Agency services"),
            ("EDUCATION", "Elimu", "Education"),
            ("CONSULTANCY", "Ushauri", "Consultancy"),
            ("RESCUE", "Uokozi", "Rescue services"),
            ("COORDINATION", "Uratibu", "Coordination"),
            ("SECURITY", "Ulinzi", "Security"),
            ("MARKETING", "Masoko", "Marketing"),
            ("OTHER", "Nyinginezo", "Other"),
        )

        configure_question(
            form, preliminary,
            label_en="Institution name",
            label_sw="Jina la taasisi",
            question_type=FormQuestion.QuestionType.SHORT_TEXT,
            order=1, required=True,
        )
        configure_question(
            form, preliminary,
            label_en="Address",
            label_sw="Anuani",
            question_type=FormQuestion.QuestionType.LONG_TEXT,
            order=2, required=True,
        )
        configure_question(
            form, preliminary,
            label_en="What type of service does your institution provide to the community? Select all that apply.",
            label_sw="Aina ya huduma unayotoa kwa jamii: Tafadhali, chagua kati ya zifuatazo.",
            question_type=FormQuestion.QuestionType.MULTIPLE_CHOICE,
            order=3, required=True, options=service_options,
        )
        configure_question(
            form, preliminary,
            label_en="If other, please specify the service",
            label_sw="Tafadhali, taja huduma nyinginezo",
            question_type=FormQuestion.QuestionType.SHORT_TEXT,
            order=4,
        )
        booth_question = configure_question(
            form, preliminary,
            label_en="Number of your institution's booths at the 2026 National Education, Skills and Innovation Week",
            label_sw="Idadi ya mabanda ya taasisi yako katika Maadhimisho ya Wiki ya Kitaifa ya Elimu, Ujuzi na Ubunifu, mwaka 2026",
            question_type=FormQuestion.QuestionType.NUMBER,
            order=5, required=True,
        )
        booth_question.minimum_value = 0
        booth_question.save(update_fields=["minimum_value", "updated_at"])

        visitors_question = configure_question(
            form, evaluation,
            label_en="State the number of people who visited your booth during the 2026 commemoration",
            label_sw="Tafadhali, taja idadi ya wananchi waliotembelea banda lako katika maadhimisho ya mwaka huu, 2026.",
            question_type=FormQuestion.QuestionType.NUMBER,
            order=1, required=True,
        )
        visitors_question.minimum_value = 0
        visitors_question.save(update_fields=["minimum_value", "updated_at"])
        configure_question(
            form, evaluation,
            label_en="State the achievements your institution gained during the 2026 commemoration",
            label_sw="Tafadhali, taja mafanikio uliyoyapata katika maadhimisho ya mwaka huu, 2026.",
            question_type=FormQuestion.QuestionType.LONG_TEXT,
            order=2, required=True,
        )
        configure_question(
            form, evaluation,
            label_en="State the challenges your institution experienced during the 2026 commemoration in Tanga City",
            label_sw="Tafadhali, taja changamoto ulizozipata katika Maadhimisho ya mwaka huu, 2026 hapa Jijini Tanga.",
            question_type=FormQuestion.QuestionType.LONG_TEXT,
            order=3, required=True,
        )
        configure_question(
            form, evaluation,
            label_en="Give recommendations for improving the commemoration in 2027",
            label_sw="Tafadhali, toa maoni ya kuboresha Maadhimisho haya kwa mwaka ujao, 2027.",
            question_type=FormQuestion.QuestionType.LONG_TEXT,
            order=4, required=True,
            existing_label_en="What should we improve in future exhibitions?",
        )

        self.stdout.write(self.style.SUCCESS(
            f"Configured {form.name_en}: "
            f"{form.sections.filter(is_active=True).count()} sections, "
            f"{FormQuestion.objects.filter(section__event_form=form, is_active=True).count()} questions."
        ))
