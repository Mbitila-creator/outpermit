from django.db import migrations, models
import django.db.models.deletion


SECTIONS = (
    ("BEPDS", "Basic Education Policy Development Section"),
    ("BETTS", "Basic Education Teachers Training Section"),
    ("SAS", "School Accreditation Section"),
)


def add_basic_education_sections(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")

    ceo = Department.objects.filter(code="CEO", is_active=True).first()
    if ceo is None:
        return
    bed = DepartmentUnit.objects.filter(
        department=ceo,
        code="BED",
        is_active=True,
    ).first()
    if bed is None:
        return

    for code, name in SECTIONS:
        DepartmentUnit.objects.update_or_create(
            department=ceo,
            code=code,
            defaults={
                "name": name,
                "parent": bed,
                "is_active": True,
            },
        )


def flatten_basic_education_sections(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")

    ceo = Department.objects.filter(code="CEO").first()
    if ceo:
        DepartmentUnit.objects.filter(
            department=ceo,
            code__in=[code for code, _name in SECTIONS],
        ).update(parent=None)


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0020_remove_legacy_ceo_units"),
    ]

    operations = [
        migrations.AddField(
            model_name="departmentunit",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sections",
                to="permits.departmentunit",
            ),
        ),
        migrations.RunPython(
            add_basic_education_sections,
            flatten_basic_education_sections,
        ),
    ]
