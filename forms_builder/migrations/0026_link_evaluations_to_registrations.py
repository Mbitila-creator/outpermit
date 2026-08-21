from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("forms_builder", "0025_formquestion_conditional_display"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventform",
            name="requires_participant_registration",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Allow access only from the portal of a participant "
                    "registered for this event."
                ),
                verbose_name="requires participant registration",
            ),
        ),
        migrations.AddField(
            model_name="formsubmission",
            name="registration_submission",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "The participant registration that supplied the identity "
                    "for this evaluation submission."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="linked_evaluation_submissions",
                to="forms_builder.formsubmission",
                verbose_name="linked participant registration",
            ),
        ),
    ]
