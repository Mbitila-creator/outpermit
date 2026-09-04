from django.db import migrations, models


def rename_commissioner_role(apps, schema_editor):
    ApprovalRole = apps.get_model("permits", "ApprovalRole")
    ApprovalRole.objects.filter(code="COMMISSIONER_EDUCATION").update(
        name="Commissioner of Education"
    )


def restore_commissioner_role(apps, schema_editor):
    ApprovalRole = apps.get_model("permits", "ApprovalRole")
    ApprovalRole.objects.filter(code="COMMISSIONER_EDUCATION").update(
        name="Commissioner for Education"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("permits", "0023_executive_permit_approvals"),
    ]

    operations = [
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
                    ("COMMISSIONER_EDUCATION", "Commissioner of Education"),
                ],
                default="REQUESTER",
                max_length=30,
            ),
        ),
        migrations.RunPython(rename_commissioner_role, restore_commissioner_role),
    ]
