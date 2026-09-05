from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0010_task_proposal_approval"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskassignment",
            name="is_group_leader",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddConstraint(
            model_name="taskassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_group_leader=True),
                fields=("task",),
                name="unique_group_leader_per_task",
            ),
        ),
    ]
