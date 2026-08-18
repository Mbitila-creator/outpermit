from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0009_group_special_event_publications_by_researcher"),
    ]

    operations = [
        migrations.AlterField(
            model_name="specialeventpublication",
            name="award_year",
            field=models.CharField(
                blank=True,
                help_text="May be left blank for legacy records and completed later.",
                max_length=50,
                verbose_name="award year",
            ),
        ),
    ]

