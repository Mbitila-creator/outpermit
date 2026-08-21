from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


OLD_CODE = "ELIMU-2026"
NEW_CODE = "WEUUTz-2026"


def rename_event_code(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    if Event.objects.filter(code=NEW_CODE).exists():
        return
    Event.objects.filter(code=OLD_CODE).update(code=NEW_CODE)


def restore_event_code(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    if Event.objects.filter(code=OLD_CODE).exists():
        return
    Event.objects.filter(code=NEW_CODE).update(code=OLD_CODE)


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0011_event_department_ownership"),
    ]

    operations = [
        migrations.RunPython(rename_event_code, restore_event_code),
        migrations.AlterField(
            model_name="event",
            name="code",
            field=models.CharField(
                help_text=_("Use a short unique code, for example WEUUTz-2026."),
                max_length=50,
                unique=True,
                verbose_name="event code",
            ),
        ),
    ]
