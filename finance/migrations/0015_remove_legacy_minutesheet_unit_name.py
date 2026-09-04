from django.db import migrations
from django.db.models import Q


def map_minute_sheets_to_department_units(apps, schema_editor):
    MinuteSheet = apps.get_model("finance", "MinuteSheet")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")

    sheets = MinuteSheet.objects.filter(department_unit__isnull=True).exclude(
        unit_name__isnull=True
    ).exclude(unit_name="")
    for sheet in sheets.iterator():
        candidates = DepartmentUnit.objects.filter(
            Q(code__iexact=sheet.unit_name) | Q(name__iexact=sheet.unit_name)
        )
        if sheet.department_id:
            candidates = candidates.filter(department_id=sheet.department_id)
        department_unit = candidates.order_by("id").first()
        if department_unit:
            sheet.department_unit_id = department_unit.id
            if not sheet.department_id:
                sheet.department_id = department_unit.department_id
            sheet.save(update_fields=["department_unit", "department"])


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0014_alter_budgetline_options_budgetline_department_and_more"),
        ("permits", "0025_remove_legacy_unit_names"),
    ]

    operations = [
        migrations.RunPython(
            map_minute_sheets_to_department_units,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(model_name="minutesheet", name="unit_name"),
    ]
