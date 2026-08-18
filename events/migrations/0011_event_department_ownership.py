from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0010_allow_blank_legacy_award_year"),
        ("permits", "0011_alter_userprofile_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="owning_department",
            field=models.ForeignKey(
                blank=True,
                help_text="The department that owns this event and its operational data.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="permits.department",
                verbose_name="owning department",
            ),
        ),
        migrations.AddIndex(
            model_name="event",
            index=models.Index(
                fields=["owning_department", "status", "starts_at"],
                name="event_dept_status_start_idx",
            ),
        ),
    ]
