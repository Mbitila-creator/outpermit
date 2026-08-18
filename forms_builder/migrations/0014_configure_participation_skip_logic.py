from django.db import migrations


FORM_SLUG = "exhibition-participant-registration-form"


def configure_participation_form(apps, schema_editor):
    EventForm = apps.get_model("forms_builder", "EventForm")
    FormSection = apps.get_model("forms_builder", "FormSection")
    FormQuestion = apps.get_model("forms_builder", "FormQuestion")
    QuestionOption = apps.get_model("forms_builder", "QuestionOption")

    event_form = EventForm.objects.filter(slug=FORM_SLUG).first()
    if event_form is None:
        return

    institution = event_form.sections.filter(
        questions__label_en="Institution Name",
    ).distinct().first()
    representative = event_form.sections.filter(
        questions__label_en="Representative Name",
    ).distinct().first()

    if institution:
        institution.title_sw = "Taarifa za Taasisi"
        institution.title_en = "Institution Information"
        institution.display_order = 1
        institution.save(
            update_fields=["title_sw", "title_en", "display_order"]
        )
        institution.questions.filter(label_en="Institution Name").update(
            display_order=1,
        )
        FormQuestion.objects.get_or_create(
            section=institution,
            label_en="Institution Email Address",
            defaults={
                "label_sw": "Anwani ya Barua Pepe ya Taasisi",
                "question_type": "EMAIL",
                "is_required": True,
                "display_order": 2,
            },
        )
        FormQuestion.objects.get_or_create(
            section=institution,
            label_en="Institution Phone Number",
            defaults={
                "label_sw": "Namba ya Simu ya Taasisi",
                "question_type": "PHONE",
                "is_required": True,
                "display_order": 3,
            },
        )

    if representative:
        representative.title_sw = "Taarifa za Mwakilishi"
        representative.title_en = "Representative Information"
        representative.display_order = 2
        representative.save(
            update_fields=["title_sw", "title_en", "display_order"]
        )
        for order, label in enumerate(
            [
                "Representative Name",
                "Representative Email Address",
                "Representative Phone Number",
            ],
            start=1,
        ):
            representative.questions.filter(label_en=label).update(
                display_order=order,
            )

    participation_section, _ = FormSection.objects.get_or_create(
        event_form=event_form,
        title_en="Participation Type",
        defaults={
            "title_sw": "Aina ya Ushiriki",
            "display_order": 3,
        },
    )
    participation_section.display_order = 3
    participation_section.is_active = True
    participation_section.save(update_fields=["display_order", "is_active"])

    participation_question, _ = FormQuestion.objects.get_or_create(
        section=participation_section,
        label_en=(
            "In which part(s) of the event do you intend to participate?"
        ),
        defaults={
            "label_sw": (
                "Unakusudia kushiriki katika sehemu ipi/zipi za tukio?"
            ),
            "question_type": "MULTIPLE_CHOICE",
            "is_required": True,
            "display_order": 1,
        },
    )

    participation_options = [
        ("EXHIBITION", "Maonesho", "Exhibition", 1),
        ("CONFERENCE", "Kongamano", "Conference", 2),
        ("OTHER", "Nyingine", "Other", 3),
    ]
    for value, label_sw, label_en, order in participation_options:
        QuestionOption.objects.update_or_create(
            question=participation_question,
            value=value,
            defaults={
                "label_sw": label_sw,
                "label_en": label_en,
                "display_order": order,
                "is_active": True,
            },
        )

    exhibition_titles = {"Booths", "Products", "Electricity", "Extra"}
    exhibition_sections = event_form.sections.filter(
        title_en__in=exhibition_titles,
    ).order_by("display_order", "id")
    for order, section in enumerate(exhibition_sections, start=4):
        section.display_order = order
        section.condition_question = participation_question
        section.condition_value = "EXHIBITION"
        section.save(
            update_fields=[
                "display_order",
                "condition_question",
                "condition_value",
            ]
        )

    conference_section, _ = FormSection.objects.get_or_create(
        event_form=event_form,
        title_en="Conference Areas",
        defaults={
            "title_sw": "Maeneo ya Kongamano",
            "display_order": 8,
        },
    )
    conference_section.display_order = 8
    conference_section.condition_question = participation_question
    conference_section.condition_value = "CONFERENCE"
    conference_section.is_active = True
    conference_section.save(
        update_fields=[
            "display_order",
            "condition_question",
            "condition_value",
            "is_active",
        ]
    )

    conference_question, _ = FormQuestion.objects.get_or_create(
        section=conference_section,
        label_en=(
            "Which conference area(s) are you interested in attending?"
        ),
        defaults={
            "label_sw": (
                "Unapendelea kuhudhuria eneo/maeneo yapi ya kongamano?"
            ),
            "question_type": "MULTIPLE_CHOICE",
            "is_required": True,
            "display_order": 1,
        },
    )
    conference_options = [
        ("BASIC_EDUCATION", "Elimu ya Msingi", "Basic Education", 1),
        (
            "HIGHER_EDUCATION_TVET",
            "Elimu ya Juu na Elimu na Mafunzo ya Ufundi na Stadi za Kazi (TVET)",
            "Higher Education and Technical and Vocational Education and Training (TVET)",
            2,
        ),
        (
            "STI",
            "Sayansi, Teknolojia na Ubunifu (STI)",
            "Science, Technology and Innovation (STI)",
            3,
        ),
    ]
    for value, label_sw, label_en, order in conference_options:
        QuestionOption.objects.update_or_create(
            question=conference_question,
            value=value,
            defaults={
                "label_sw": label_sw,
                "label_en": label_en,
                "display_order": order,
                "is_active": True,
            },
        )

    other_section, _ = FormSection.objects.get_or_create(
        event_form=event_form,
        title_en="Other Participation",
        defaults={
            "title_sw": "Ushiriki Mwingine",
            "display_order": 9,
        },
    )
    other_section.display_order = 9
    other_section.condition_question = participation_question
    other_section.condition_value = "OTHER"
    other_section.is_active = True
    other_section.save(
        update_fields=[
            "display_order",
            "condition_question",
            "condition_value",
            "is_active",
        ]
    )
    FormQuestion.objects.get_or_create(
        section=other_section,
        label_en="Please specify the other type of participation.",
        defaults={
            "label_sw": "Tafadhali bainisha aina nyingine ya ushiriki.",
            "question_type": "SHORT_TEXT",
            "is_required": True,
            "display_order": 1,
        },
    )


def remove_participation_configuration(apps, schema_editor):
    EventForm = apps.get_model("forms_builder", "EventForm")
    event_form = EventForm.objects.filter(slug=FORM_SLUG).first()
    if event_form is None:
        return

    event_form.sections.filter(
        title_en__in=[
            "Conference Areas",
            "Other Participation",
        ],
    ).delete()
    participation = event_form.sections.filter(
        title_en="Participation Type",
    ).first()
    if participation:
        event_form.sections.filter(
            condition_question__section=participation,
        ).update(condition_question=None, condition_value="")
        participation.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("forms_builder", "0013_add_section_skip_logic"),
    ]

    operations = [
        migrations.RunPython(
            configure_participation_form,
            remove_participation_configuration,
        ),
    ]

