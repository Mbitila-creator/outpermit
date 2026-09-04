from django.db import migrations
from django.db.models import Q


def map_tasks_to_department_units(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")

    tasks = Task.objects.filter(department_unit__isnull=True).exclude(
        unit_name__isnull=True
    ).exclude(unit_name="")
    for task in tasks.iterator():
        candidates = DepartmentUnit.objects.filter(
            Q(code__iexact=task.unit_name) | Q(name__iexact=task.unit_name)
        )
        if task.department_id:
            candidates = candidates.filter(department_id=task.department_id)
        department_unit = candidates.order_by("id").first()
        if department_unit:
            task.department_unit_id = department_unit.id
            if not task.department_id:
                task.department_id = department_unit.department_id
            task.save(update_fields=["department_unit", "department"])


class Migration(migrations.Migration):

    dependencies = [
        ("permits", "0025_remove_legacy_unit_names"),
        ("tasks", "0008_task_department_task_department_unit"),
    ]

    operations = [
        migrations.RunPython(map_tasks_to_department_units, migrations.RunPython.noop),
        migrations.RemoveField(model_name="task", name="unit_name"),
    ]
