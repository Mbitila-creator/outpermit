import uuid

from django.db import migrations, models


def populate_participant_tokens(apps, schema_editor):
    form_submission = apps.get_model(
        "forms_builder",
        "FormSubmission",
    )

    for submission in form_submission.objects.filter(
        participant_token__isnull=True
    ).iterator():
        submission.participant_token = uuid.uuid4()
        submission.save(update_fields=["participant_token"])


class Migration(migrations.Migration):

    dependencies = [
        (
            "forms_builder",
            "0003_formsubmission_review_notes_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="formsubmission",
            name="badge_name",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Name that will be printed on the participant badge."
                ),
                max_length=200,
                verbose_name="badge name",
            ),
        ),
        migrations.AddField(
            model_name="formsubmission",
            name="badge_organization",
            field=models.CharField(
                blank=True,
                max_length=250,
                verbose_name="badge organization",
            ),
        ),
        migrations.AddField(
            model_name="formsubmission",
            name="badge_title",
            field=models.CharField(
                blank=True,
                max_length=150,
                verbose_name="badge title or role",
            ),
        ),
        migrations.AddField(
            model_name="formsubmission",
            name="participant_token",
            field=models.UUIDField(
                editable=False,
                null=True,
            ),
        ),
        migrations.RunPython(
            populate_participant_tokens,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="formsubmission",
            name="participant_token",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                verbose_name="participant token",
            ),
        ),
    ]

