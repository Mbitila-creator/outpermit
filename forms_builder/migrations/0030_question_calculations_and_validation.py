from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("forms_builder", "0029_remove_displaylogicgroup_logic_group_has_exactly_one_target_and_more")]

    operations = [
        migrations.AddField(
            model_name="formquestion", name="calculation_expression",
            field=models.CharField(blank=True, help_text="Use question references such as q12 + q13.", max_length=500, verbose_name="calculation expression"),
        ),
        migrations.AddField(
            model_name="formquestion", name="calculation_decimal_places",
            field=models.PositiveSmallIntegerField(blank=True, default=2, verbose_name="calculation decimal places"),
        ),
        migrations.AddField(
            model_name="formquestion", name="validation_expression",
            field=models.CharField(blank=True, help_text="Example: q12 <= q13 and q14 > 0.", max_length=500, verbose_name="validation expression"),
        ),
        migrations.AddField(
            model_name="formquestion", name="validation_message_en",
            field=models.CharField(blank=True, max_length=300, verbose_name="validation message in English"),
        ),
        migrations.AddField(
            model_name="formquestion", name="validation_message_sw",
            field=models.CharField(blank=True, max_length=300, verbose_name="validation message in Kiswahili"),
        ),
        migrations.AlterField(
            model_name="formquestion", name="question_type",
            field=models.CharField(choices=[("SHORT_TEXT", "Short text"), ("LONG_TEXT", "Long text"), ("EMAIL", "Email address"), ("PHONE", "Phone number"), ("NUMBER", "Number"), ("CALCULATED", "Calculated number"), ("DATE", "Date"), ("DATETIME", "Date and time"), ("SINGLE_CHOICE", "Single choice"), ("MULTIPLE_CHOICE", "Multiple choice"), ("DROPDOWN", "Dropdown"), ("YES_NO", "Yes or No"), ("FILE", "File upload"), ("IMAGE", "Image upload")], default="SHORT_TEXT", max_length=30, verbose_name="question type"),
        ),
    ]
