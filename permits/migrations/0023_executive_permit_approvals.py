from django.db import migrations, models


EXECUTIVE_ROLES = (
    ("PERMANENT_SECRETARY", "Permanent Secretary"),
    (
        "DPS_HES",
        "Deputy Permanent Secretary - Higher Education and Science",
    ),
    ("DPS_BE", "Deputy Permanent Secretary - Basic Education"),
    ("COMMISSIONER_EDUCATION", "Commissioner for Education"),
)


def configure_executive_structure(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    ApprovalRole = apps.get_model("permits", "ApprovalRole")

    # Preserve the existing department and every related foreign key while
    # applying the corrected organizational code.
    Department.objects.filter(code="CEO").update(code="COE")

    for code, name in EXECUTIVE_ROLES:
        ApprovalRole.objects.update_or_create(
            code=code,
            defaults={"name": name, "is_active": True},
        )


def reverse_executive_structure(apps, schema_editor):
    Department = apps.get_model("permits", "Department")
    ApprovalRole = apps.get_model("permits", "ApprovalRole")

    Department.objects.filter(code="COE").update(code="CEO")
    ApprovalRole.objects.filter(
        code__in=[code for code, _name in EXECUTIVE_ROLES],
    ).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0022_add_sqad_sections_and_workflows"),
    ]

    operations = [
        migrations.AddField(
            model_name="externalworkrequest",
            name="executive_approval_chain",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="externalworkrequest",
            name="executive_approval_history",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="externalworkrequest",
            name="executive_approval_stage",
            field=models.CharField(blank=True, db_index=True, max_length=40),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="role",
            field=models.CharField(
                choices=[
                    ("REQUESTER", "Requester"),
                    ("ADMIN", "Admin"),
                    ("DIRECTOR", "Director"),
                    ("HEAD_OF_UNIT", "Head of Unit"),
                    ("ASSISTANT_DIRECTOR", "Assistant Director"),
                    ("DIVISION_BUDGET_OFFICER", "Division Budget Officer"),
                    ("ACCOUNTANT", "Accountant"),
                    ("EVENT_ADMIN", "Event Administrator"),
                    ("REGISTRATION_OFFICER", "Event Registration Officer"),
                    ("ATTENDANCE_OFFICER", "Event Attendance Officer"),
                    ("REPORT_OFFICER", "Event Reports Officer"),
                    ("PERMANENT_SECRETARY", "Permanent Secretary"),
                    (
                        "DPS_HES",
                        "Deputy Permanent Secretary - Higher Education and Science",
                    ),
                    ("DPS_BE", "Deputy Permanent Secretary - Basic Education"),
                    ("COMMISSIONER_EDUCATION", "Commissioner for Education"),
                ],
                default="REQUESTER",
                max_length=30,
            ),
        ),
        migrations.RunPython(
            configure_executive_structure,
            reverse_executive_structure,
        ),
    ]
