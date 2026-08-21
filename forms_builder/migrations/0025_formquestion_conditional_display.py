from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("forms_builder", "0024_alter_notificationlog_notification_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="formquestion",
            name="condition_question",
            field=models.ForeignKey(
                blank=True,
                help_text="Leave blank to always show this question.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="conditional_questions",
                to="forms_builder.formquestion",
                verbose_name="show when question",
            ),
        ),
        migrations.AddField(
            model_name="formquestion",
            name="condition_value",
            field=models.CharField(
                blank=True,
                help_text="Use the stored value of an option from the controlling question.",
                max_length=100,
                verbose_name="show when answer contains",
            ),
        ),
    ]
