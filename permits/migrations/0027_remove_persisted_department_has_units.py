from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("permits", "0026_alter_externalworkrequest_report_file_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="department",
            name="has_units",
        ),
    ]
