from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0012_crossdepartmenttaskrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="crossdepartmenttaskrequest",
            name="group_leader",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cross_task_requests_led",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="crossdepartmenttaskrequest",
            name="requesting_staff",
            field=models.ManyToManyField(
                related_name="cross_task_requests_as_internal_staff",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
