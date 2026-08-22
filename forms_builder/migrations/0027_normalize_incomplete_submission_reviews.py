from django.db import migrations


def normalize_incomplete_submission_reviews(apps, schema_editor):
    FormSubmission = apps.get_model("forms_builder", "FormSubmission")
    FormSubmission.objects.filter(is_complete=False).exclude(
        review_status="PENDING",
    ).update(
        review_status="PENDING",
        reviewed_by=None,
        reviewed_at=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("forms_builder", "0026_link_evaluations_to_registrations"),
    ]

    operations = [
        migrations.RunPython(
            normalize_incomplete_submission_reviews,
            migrations.RunPython.noop,
        ),
    ]
