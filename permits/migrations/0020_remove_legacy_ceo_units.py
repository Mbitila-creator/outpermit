from django.db import migrations


LEGACY_UNITS = (
    ("DBEP", "Development of Basic Education Policy"),
    ("EC", "Education Commission"),
    ("SR", "School Registration"),
    ("TE", "Teacher Education"),
)


def remove_legacy_units(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")
    UserProfile = apps.get_model("permits", "UserProfile")
    Task = apps.get_model("tasks", "Task")
    FinanceRequest = apps.get_model("finance", "FinanceRequest")
    MinuteSheet = apps.get_model("finance", "MinuteSheet")
    BudgetLine = apps.get_model("finance", "BudgetLine")

    ceo = Department.objects.filter(code="CEO").first()
    if ceo is None:
        return

    bed = DepartmentUnit.objects.filter(
        department=ceo,
        code="BED",
    ).first()
    if bed is None:
        bed = DepartmentUnit.objects.create(
            department=ceo,
            code="BED",
            name="Basic Education Division",
            is_active=True,
        )

    for legacy_code, _legacy_name in LEGACY_UNITS:
        legacy_unit = DepartmentUnit.objects.filter(
            department=ceo,
            code=legacy_code,
        ).first()
        if legacy_unit is None:
            continue

        UserProfile.objects.filter(department_unit=legacy_unit).update(
            department=ceo,
            department_unit=bed,
        )
        Task.objects.filter(department_unit=legacy_unit).update(
            department=ceo,
            department_unit=bed,
        )
        FinanceRequest.objects.filter(department_unit=legacy_unit).update(
            department=ceo,
            department_unit=bed,
        )
        MinuteSheet.objects.filter(department_unit=legacy_unit).update(
            department=ceo,
            department_unit=bed,
        )
        BudgetLine.objects.filter(department_unit=legacy_unit).update(
            department=ceo,
            department_unit=bed,
        )
        legacy_unit.delete()


def restore_legacy_units(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")

    ceo = Department.objects.filter(code="CEO").first()
    if ceo is None:
        return
    for code, name in LEGACY_UNITS:
        DepartmentUnit.objects.update_or_create(
            department=ceo,
            code=code,
            defaults={
                "name": name,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0014_alter_budgetline_options_budgetline_department_and_more"),
        ("permits", "0019_place_education_units_under_ceo"),
        ("tasks", "0008_task_department_task_department_unit"),
    ]

    operations = [
        migrations.RunPython(remove_legacy_units, restore_legacy_units),
    ]
