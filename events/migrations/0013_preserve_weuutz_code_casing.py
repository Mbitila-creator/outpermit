from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


UPPERCASE_CODE = "WEUUTZ-2026"
DISPLAY_CODE = "WEUUTz-2026"


def preserve_display_casing(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.filter(code=UPPERCASE_CODE).update(code=DISPLAY_CODE)


def restore_uppercase_code(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.filter(code=DISPLAY_CODE).update(code=UPPERCASE_CODE)


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0012_rename_elimu_event_code"),
    ]

    operations = [
        migrations.RunPython(preserve_display_casing, restore_uppercase_code),
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
