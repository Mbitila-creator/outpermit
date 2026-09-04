from django.db import migrations


SECTIONS = (
    ("PPSQAS", "Pre and Primary School Quality Assurance Section"),
    ("SSQAS", "Secondary School Quality Assurance Section"),
    (
        "BETCQAS",
        "Basic Education Training Colleges Quality Assurance Section",
    ),
    ("RQAO", "Regional Quality Assurance Office"),
    ("DQAO", "District Quality Assurance Office"),
)

WORKFLOW_ROLES = (
    "REQUESTER",
    "HEAD_OF_UNIT",
    "ASSISTANT_DIRECTOR",
    "DIRECTOR",
)

WORKFLOW_MODULES = ("PERMIT", "TASK", "FINANCE", "EVENT")


def add_sqad_architecture(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")
    ApprovalRole = apps.get_model("permits", "ApprovalRole")
    DepartmentApprovalWorkflow = apps.get_model(
        "permits",
        "DepartmentApprovalWorkflow",
    )

    sqad, _created = Department.objects.update_or_create(
        code="SQAD",
        defaults={
            "name": "Schools Quality Assurance Division",
            "has_units": True,
            "is_active": True,
        },
    )

    for code, name in SECTIONS:
        DepartmentUnit.objects.update_or_create(
            department=sqad,
            code=code,
            defaults={
                "name": name,
                "parent": None,
                "is_active": True,
            },
        )

    roles = {
        role.code: role
        for role in ApprovalRole.objects.filter(code__in=WORKFLOW_ROLES)
    }
    if len(roles) != len(WORKFLOW_ROLES):
        return

    for module in WORKFLOW_MODULES:
        for step_order, role_code in enumerate(WORKFLOW_ROLES, start=1):
            DepartmentApprovalWorkflow.objects.update_or_create(
                department=sqad,
                module=module,
                step_order=step_order,
                defaults={
                    "approval_role": roles[role_code],
                    "is_required": True,
                    "is_active": True,
                },
            )


def deactivate_sqad_architecture(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")
    DepartmentApprovalWorkflow = apps.get_model(
        "permits",
        "DepartmentApprovalWorkflow",
    )

    sqad = Department.objects.filter(code="SQAD").first()
    if sqad is None:
        return
    DepartmentUnit.objects.filter(
        department=sqad,
        code__in=[code for code, _name in SECTIONS],
    ).update(is_active=False)
    DepartmentApprovalWorkflow.objects.filter(
        department=sqad,
        module__in=WORKFLOW_MODULES,
    ).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0021_department_unit_sections"),
    ]

    operations = [
        migrations.RunPython(
            add_sqad_architecture,
            deactivate_sqad_architecture,
        ),
    ]
