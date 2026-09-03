from django.db import migrations


NEW_DEPARTMENTS = (
    ("BED", "Basic Education Division"),
    ("SNEU", "Special Needs Education Unit"),
)


def add_departments(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    for code, name in NEW_DEPARTMENTS:
        Department.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "is_active": True,
            },
        )


def remove_departments(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    for code, name in NEW_DEPARTMENTS:
        Department.objects.filter(code=code, name=name).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0017_rename_office_for_commissioner_education"),
    ]

    operations = [
        migrations.RunPython(add_departments, remove_departments),
    ]
