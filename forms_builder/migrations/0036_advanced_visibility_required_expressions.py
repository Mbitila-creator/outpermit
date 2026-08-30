from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forms_builder", "0035_eventform_qr_record_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="formsection",
            name="visibility_expression",
            field=models.CharField(
                blank=True,
                help_text="Expert mode example: q12 == 'YES' and q15 >= 18.",
                max_length=500,
                verbose_name="advanced visibility expression",
            ),
        ),
        migrations.AddField(
            model_name="formquestion",
            name="visibility_expression",
            field=models.CharField(
                blank=True,
                help_text="Expert mode example: q12 == 'YES' and q15 >= 18.",
                max_length=500,
                verbose_name="advanced visibility expression",
            ),
        ),
        migrations.AddField(
            model_name="formquestion",
            name="required_expression",
            field=models.CharField(
                blank=True,
                help_text="Expert mode example: q12 == 'YES' and COUNT(q15) > 0.",
                max_length=500,
                verbose_name="advanced required expression",
            ),
        ),
    ]
