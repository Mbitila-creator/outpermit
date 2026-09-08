from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("conferences", "0010_conferenceguidingsubmission_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="conferenceguidingquestion",
            name="text",
            field=models.CharField(max_length=500, verbose_name="question"),
        ),
    ]
