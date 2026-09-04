from django.db import migrations
from django.db.models import Q


def map_profiles_to_department_units(apps, schema_editor):
    UserProfile = apps.get_model("permits", "UserProfile")
    DepartmentUnit = apps.get_model("permits", "DepartmentUnit")

    profiles = UserProfile.objects.filter(
        department_unit__isnull=True,
    ).exclude(unit_name__isnull=True).exclude(unit_name="")

    for profile in profiles.iterator():
        candidates = DepartmentUnit.objects.filter(
            Q(code__iexact=profile.unit_name) | Q(name__iexact=profile.unit_name)
        )
        if profile.department_id:
            candidates = candidates.filter(department_id=profile.department_id)
        department_unit = candidates.order_by("id").first()
        if department_unit:
            profile.department_unit_id = department_unit.id
            if not profile.department_id:
                profile.department_id = department_unit.department_id
            profile.save(update_fields=["department_unit", "department"])


class Migration(migrations.Migration):

    dependencies = [
        ("permits", "0024_rename_commissioner_role_label"),
    ]

    operations = [
        migrations.RunPython(
            map_profiles_to_department_units,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="externalworkrequest",
            name="unit_name",
        ),
        migrations.RemoveField(
            model_name="userprofile",
            name="unit_name",
        ),
    ]
