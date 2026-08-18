from decimal import Decimal

from django.db import migrations


def configure_elimu_booth_pricing(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    FormQuestion = apps.get_model("forms_builder", "FormQuestion")
    QuantityPricingRule = apps.get_model(
        "forms_builder", "QuantityPricingRule"
    )

    event = Event.objects.filter(code="ELIMU-2026").first()
    if event is None:
        return
    question = FormQuestion.objects.filter(
        section__event_form__event=event,
        label_en="How many exhibition booths does your institution require?",
        question_type="NUMBER",
    ).first()
    if question is None:
        return

    QuantityPricingRule.objects.update_or_create(
        event=event,
        defaults={
            "quantity_question": question,
            "first_unit_amount": Decimal("2000000.00"),
            "additional_unit_amount": Decimal("1500000.00"),
            "currency": "TZS",
            "is_active": True,
        },
    )


def remove_elimu_booth_pricing(apps, schema_editor):
    QuantityPricingRule = apps.get_model(
        "forms_builder", "QuantityPricingRule"
    )
    QuantityPricingRule.objects.filter(event__code="ELIMU-2026").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("forms_builder", "0018_quantity_pricing_rule"),
    ]

    operations = [
        migrations.RunPython(
            configure_elimu_booth_pricing,
            remove_elimu_booth_pricing,
        ),
    ]

