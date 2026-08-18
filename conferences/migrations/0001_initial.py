from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("events", "0010_allow_blank_legacy_award_year"),
        ("forms_builder", "0024_alter_notificationlog_notification_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConferenceSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True, verbose_name="is active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                ("code", models.CharField(max_length=80, verbose_name="session code")),
                ("title", models.CharField(max_length=300, verbose_name="session title")),
                ("starts_at", models.DateTimeField(verbose_name="session starts")),
                ("ends_at", models.DateTimeField(verbose_name="session ends")),
                ("venue_name", models.CharField(blank=True, max_length=250, verbose_name="session venue")),
                ("registration_option_value", models.CharField(help_text="Stored value of the matching registration-form option.", max_length=100, verbose_name="registration option value")),
                ("display_order", models.PositiveIntegerField(default=0, verbose_name="display order")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_created_records", to=settings.AUTH_USER_MODEL, verbose_name="created by")),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conference_sessions", to="events.event", verbose_name="conference event")),
                ("updated_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_updated_records", to=settings.AUTH_USER_MODEL, verbose_name="updated by")),
            ],
            options={"ordering": ("starts_at", "display_order", "id")},
        ),
        migrations.CreateModel(
            name="ConferenceSessionAttendance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True, verbose_name="is active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                ("checked_in_at", models.DateTimeField(auto_now_add=True, verbose_name="checked in at")),
                ("method", models.CharField(choices=[("QR", "QR code"), ("MANUAL", "Manual lookup")], default="QR", max_length=20, verbose_name="check-in method")),
                ("checked_in_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="conference_session_checkins", to=settings.AUTH_USER_MODEL, verbose_name="checked in by")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_created_records", to=settings.AUTH_USER_MODEL, verbose_name="created by")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attendance_records", to="conferences.conferencesession", verbose_name="conference session")),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conference_session_attendance", to="forms_builder.formsubmission", verbose_name="participant registration")),
                ("updated_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_updated_records", to=settings.AUTH_USER_MODEL, verbose_name="updated by")),
            ],
            options={"ordering": ("-checked_in_at",)},
        ),
        migrations.AddConstraint(
            model_name="conferencesession",
            constraint=models.UniqueConstraint(fields=("event", "code"), name="unique_conference_session_code_per_event"),
        ),
        migrations.AddConstraint(
            model_name="conferencesession",
            constraint=models.UniqueConstraint(fields=("event", "registration_option_value"), name="unique_conference_session_option_per_event"),
        ),
        migrations.AddConstraint(
            model_name="conferencesessionattendance",
            constraint=models.UniqueConstraint(fields=("session", "submission"), name="unique_participant_checkin_per_conference_session"),
        ),
    ]

