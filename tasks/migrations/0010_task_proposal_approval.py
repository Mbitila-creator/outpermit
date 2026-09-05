from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0009_remove_legacy_task_unit_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="task", name="approval_status",
            field=models.CharField(
                choices=[
                    ("NOT_REQUIRED", "Approval not required"),
                    ("PENDING", "Pending approval"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                ], db_index=True, default="NOT_REQUIRED", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="task", name="approval_decision_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="task", name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task", name="approver",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="task_approval_requests", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="task", name="proposed_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="proposed_tasks", to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
