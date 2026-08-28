from django.db import migrations, models


def enable_existing_event_certificates(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.filter(certificate_enabled=False).update(certificate_enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0014_eventtimetable"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="certificate_enabled",
            field=models.BooleanField(default=True, verbose_name="certificate enabled"),
        ),
        migrations.RunPython(
            enable_existing_event_certificates,
            migrations.RunPython.noop,
        ),
    ]
