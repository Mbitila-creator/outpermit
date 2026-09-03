from django.db import migrations


DEPARTMENT_CHANGES = (
    ("AFU", "FAU", "Finance and Accounting Unit"),
    ("DHRAM", "AHRM", "Administration and Human Resource Management"),
    ("GCU", "GCU", "Government Communication Unit"),
    ("IAU", "IAU", "Internal Audit Unit"),
    ("ICTU", "ICTU", "Information and Communication Technology Unit"),
    ("LU", "LSU", "Legal Service Unit"),
    ("PSU", "PMU", "Procurement Management Unit"),
    ("DPP", "DPP", "Policy and Planning Division"),
    ("DSQC", "MEU", "Monitoring and Evaluation Unit"),
    ("DHE", "HED", "Higher Education Division"),
    ("DSTI", "DSTI", "Science Technology and Innovation Division"),
    ("DTVET", "DTVET", "Technical and Vocational Education Training Division"),
    (
        "DOCE",
        "DOCE",
        "Department of the Office of Commissioner of Education",
    ),
)

REVERSE_DEPARTMENT_CHANGES = (
    ("FAU", "AFU", "Department of Accounting and Finance"),
    (
        "AHRM",
        "DHRAM",
        "Department of Human Resources Administration and Management",
    ),
    ("GCU", "GCU", "Government Communication Department"),
    ("IAU", "IAU", "Internal Audit Department"),
    (
        "ICTU",
        "ICTU",
        "Information and Communication Technology Department",
    ),
    ("LSU", "LU", "Legal Department"),
    ("PMU", "PSU", "Procurement and Supply Department"),
    ("DPP", "DPP", "Department of Policies and Plans"),
    ("MEU", "DSQC", "Department of Monitoring and Evaluation"),
    ("HED", "DHE", "Department of Higher Education"),
    ("DSTI", "DSTI", "Department of Science Technology and Innovation"),
    (
        "DTVET",
        "DTVET",
        "Directorate of Technical and Vocational Education Training",
    ),
    (
        "DOCE",
        "DOCE",
        "Department of the Office of Commissioner of Education",
    ),
)


def update_departments(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    for old_code, new_code, new_name in DEPARTMENT_CHANGES:
        Department.objects.filter(code=old_code).update(
            code=new_code,
            name=new_name,
        )
    Department.objects.update_or_create(
        code="SQAD",
        defaults={
            "name": "Schools Quality Assurance Division",
            "is_active": True,
        },
    )


def restore_departments(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    Department.objects.filter(
        code="SQAD",
        name="Schools Quality Assurance Division",
    ).delete()
    for current_code, old_code, old_name in REVERSE_DEPARTMENT_CHANGES:
        Department.objects.filter(code=current_code).update(
            code=old_code,
            name=old_name,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0014_remove_moduleroleassignment_unique_module_role_per_user_and_more"),
    ]

    operations = [
        migrations.RunPython(update_departments, restore_departments),
    ]
