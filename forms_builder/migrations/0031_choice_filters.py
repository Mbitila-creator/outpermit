from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("forms_builder", "0030_question_calculations_and_validation")]

    operations = [
        migrations.AddField(
            model_name="formquestion",
            name="choice_filter_question",
            field=models.ForeignKey(
                blank=True,
                help_text="For cascading choices, show only options matching an earlier question.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="filtered_choice_questions",
                to="forms_builder.formquestion",
                verbose_name="filter choices using question",
            ),
        ),
        migrations.AddField(
            model_name="questionoption",
            name="filter_values",
            field=models.CharField(
                blank=True,
                help_text="Comma-separated stored values. Leave blank to show this option for every answer.",
                max_length=500,
                verbose_name="controlling answer values",
            ),
        ),
    ]
