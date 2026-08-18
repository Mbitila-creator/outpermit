from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("events", "0007_event_participation_fee_event_payment_currency_and_more"),
        ("meetings", "0003_meeting_communications"),
    ]

    operations = [
        migrations.CreateModel(
            name="MeetingSeries",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True, verbose_name="is active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                ("code", models.CharField(max_length=50, unique=True, verbose_name="series code")),
                ("name_sw", models.CharField(max_length=250, verbose_name="series name in Kiswahili")),
                ("name_en", models.CharField(max_length=250, verbose_name="series name in English")),
                ("description_sw", models.TextField(blank=True, verbose_name="description in Kiswahili")),
                ("description_en", models.TextField(blank=True, verbose_name="description in English")),
                ("frequency", models.CharField(choices=[("ON_DEMAND", "On demand"), ("WEEKLY", "Weekly"), ("MONTHLY", "Monthly"), ("QUARTERLY", "Quarterly"), ("ANNUALLY", "Annually")], default="MONTHLY", max_length=20, verbose_name="meeting frequency")),
                ("meeting_type", models.CharField(choices=[("MANAGEMENT", "Management meeting"), ("TECHNICAL", "Technical meeting"), ("COMMITTEE", "Committee meeting"), ("BOARD", "Board meeting"), ("STAKEHOLDER", "Stakeholder meeting"), ("WORKING_SESSION", "Working session"), ("OTHER", "Other meeting")], default="MANAGEMENT", max_length=30, verbose_name="default meeting type")),
                ("default_duration_minutes", models.PositiveIntegerField(default=120, verbose_name="default duration in minutes")),
                ("chairperson_name", models.CharField(max_length=200, verbose_name="default chairperson")),
                ("secretary_name", models.CharField(blank=True, max_length=200, verbose_name="default secretary")),
                ("quorum_required", models.PositiveIntegerField(blank=True, null=True, verbose_name="default required quorum")),
                ("objectives_sw", models.TextField(blank=True, verbose_name="default objectives in Kiswahili")),
                ("objectives_en", models.TextField(blank=True, verbose_name="default objectives in English")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_created_records", to=settings.AUTH_USER_MODEL, verbose_name="created by")),
                ("updated_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_updated_records", to=settings.AUTH_USER_MODEL, verbose_name="updated by")),
                ("venue", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="meeting_series", to="events.venue", verbose_name="default venue")),
            ],
            options={"verbose_name": "meeting series", "verbose_name_plural": "meeting series", "ordering": ["name_sw", "code"]},
        ),
        migrations.AddField(
            model_name="meeting",
            name="series",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="meetings", to="meetings.meetingseries", verbose_name="meeting series"),
        ),
        migrations.CreateModel(
            name="MeetingSeriesAgendaTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True, verbose_name="is active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                ("item_number", models.PositiveIntegerField(verbose_name="agenda item number")),
                ("title_sw", models.CharField(max_length=300, verbose_name="agenda title in Kiswahili")),
                ("title_en", models.CharField(max_length=300, verbose_name="agenda title in English")),
                ("presenter_name", models.CharField(blank=True, max_length=200, verbose_name="default presenter")),
                ("allocated_minutes", models.PositiveIntegerField(blank=True, null=True, verbose_name="allocated minutes")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_created_records", to=settings.AUTH_USER_MODEL, verbose_name="created by")),
                ("series", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="agenda_templates", to="meetings.meetingseries", verbose_name="meeting series")),
                ("updated_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_updated_records", to=settings.AUTH_USER_MODEL, verbose_name="updated by")),
            ],
            options={"verbose_name": "series agenda template", "verbose_name_plural": "series agenda templates", "ordering": ["series", "item_number"]},
        ),
        migrations.AddConstraint(
            model_name="meetingseriesagendatemplate",
            constraint=models.UniqueConstraint(fields=("series", "item_number"), name="unique_agenda_template_per_series"),
        ),
    ]

