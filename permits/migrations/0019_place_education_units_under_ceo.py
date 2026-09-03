from django.db import migrations


UNIT_CHANGES = (
    ("BE", "BED", "Basic Education Division"),
    ("SE", "SNEU", "Special Needs Education Unit"),
)


def place_units_under_ceo(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")

    ceo, _created = Department.objects.update_or_create(
        code="CEO",
        defaults={
            "name": "Office for Commissioner of Education",
            "has_units": True,
            "is_active": True,
        },
    )

    for legacy_code, new_code, new_name in UNIT_CHANGES:
        unit = DepartmentUnit.objects.filter(
            department=ceo,
            code=new_code,
        ).first()
        if unit is None:
            unit = DepartmentUnit.objects.filter(
                department=ceo,
                code=legacy_code,
            ).first()
        if unit is None:
            DepartmentUnit.objects.create(
                department=ceo,
                code=new_code,
                name=new_name,
                is_active=True,
            )
        else:
            unit.code = new_code
            unit.name = new_name
            unit.is_active = True
            unit.save(update_fields=["code", "name", "is_active"])

    Department.objects.filter(code__in=["BED", "SNEU"]).update(
        is_active=False,
    )


def restore_standalone_departments(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")

    ceo = Department.objects.filter(code="CEO").first()
    if ceo:
        legacy_names = {
            "BED": ("BE", "Basic Education"),
            "SNEU": ("SE", "Special Education"),
        }
        for current_code, (legacy_code, legacy_name) in legacy_names.items():
            DepartmentUnit.objects.filter(
                department=ceo,
                code=current_code,
            ).update(
                code=legacy_code,
                name=legacy_name,
            )

    Department.objects.filter(code__in=["BED", "SNEU"]).update(
        is_active=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0018_add_basic_and_special_needs_education"),
    ]

    operations = [
        migrations.RunPython(
            place_units_under_ceo,
            restore_standalone_departments,
        ),
    ]
