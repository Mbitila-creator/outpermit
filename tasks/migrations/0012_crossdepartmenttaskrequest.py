from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0011_taskassignment_group_leader"),
    ]

    operations = [
        migrations.CreateModel(
            name="CrossDepartmentTaskRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField()),
                ("priority", models.CharField(choices=[("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High"), ("URGENT", "Urgent")], default="MEDIUM", max_length=20)),
                ("start_date", models.DateTimeField(blank=True, null=True)),
                ("due_date", models.DateTimeField(blank=True, null=True)),
                ("attachment", models.FileField(blank=True, null=True, upload_to="task_cross_department_requests/")),
                ("status", models.CharField(choices=[("PENDING", "Pending providing director approval"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("CANCELLED", "Cancelled")], db_index=True, default="PENDING", max_length=20)),
                ("decision_note", models.TextField(blank=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("providing_department", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="incoming_cross_task_requests", to="permits.department")),
                ("providing_director", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cross_task_requests_received", to=settings.AUTH_USER_MODEL)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cross_task_requests_made", to=settings.AUTH_USER_MODEL)),
                ("requesting_department", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="outgoing_cross_task_requests", to="permits.department")),
                ("task", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cross_department_request", to="tasks.task")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
