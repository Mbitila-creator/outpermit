from django.db import migrations


def rename_commissioner_office(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    Department.objects.filter(code="CEO").update(
        name="Office for Commissioner of Education",
    )


def restore_commissioner_office(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    Department.objects.filter(code="CEO").update(
        name="Commissioner of Education Office",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0016_rename_commissioner_education_office"),
    ]

    operations = [
        migrations.RunPython(
            rename_commissioner_office,
            restore_commissioner_office,
        ),
    ]
