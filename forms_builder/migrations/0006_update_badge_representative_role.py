from django.db import migrations


def update_badge_representative_role(apps, schema_editor):
    FormSubmission = apps.get_model("forms_builder", "FormSubmission")

    FormSubmission.objects.filter(language="en").update(
        badge_title="Representative"
    )
    FormSubmission.objects.exclude(language="en").update(
        badge_title="Mwakilishi"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("forms_builder", "0005_backfill_badge_identity"),
    ]

    operations = [
        migrations.RunPython(
            update_badge_representative_role,
            migrations.RunPython.noop,
        ),
    ]

