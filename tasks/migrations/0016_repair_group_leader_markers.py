from django.db import migrations


def repair_group_leader_markers(apps, schema_editor):
    TaskAssignment = apps.get_model("tasks", "TaskAssignment")

    # Clear markers first so partially synchronized historical rows cannot
    # collide with the unique constraint while they are repaired.
    TaskAssignment.objects.update(group_leader_unique_marker=None)

    leader_task_ids = (
        TaskAssignment.objects.filter(is_group_leader=True)
        .order_by()
        .values_list("task_id", flat=True)
        .distinct()
    )
    for task_id in leader_task_ids.iterator():
        leaders = TaskAssignment.objects.filter(
            task_id=task_id,
            is_group_leader=True,
        ).order_by("assigned_at", "pk")
        leader = leaders.first()
        if leader is None:
            continue
        leaders.exclude(pk=leader.pk).update(is_group_leader=False)
        TaskAssignment.objects.filter(pk=leader.pk).update(
            group_leader_unique_marker=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0015_alter_crossdepartmenttaskrequest_attachment_and_more"),
    ]

    operations = [
        migrations.RunPython(
            repair_group_leader_markers,
            migrations.RunPython.noop,
        ),
    ]
