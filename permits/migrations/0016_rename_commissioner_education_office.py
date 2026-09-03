from django.db import migrations


def rename_commissioner_office(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    Department.objects.filter(code="DOCE").update(
        code="CEO",
        name="Commissioner of Education Office",
    )


def restore_commissioner_office(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    Department.objects.filter(code="CEO").update(
        code="DOCE",
        name="Department of the Office of Commissioner of Education",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0015_update_ministry_departments"),
    ]

    operations = [
        migrations.RunPython(
            rename_commissioner_office,
            restore_commissioner_office,
        ),
    ]
