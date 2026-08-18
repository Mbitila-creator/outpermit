from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("meetings", "0002_attendee_invitation_response"),
    ]

    operations = [
        migrations.AddField(
            model_name="meetingactionitem",
            name="responsible_email",
            field=models.EmailField(
                blank=True,
                max_length=254,
                verbose_name="responsible person's email",
            ),
        ),
        migrations.CreateModel(
            name="MeetingCommunicationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True, verbose_name="is active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                ("communication_type", models.CharField(choices=[("INVITATION", "Meeting invitation"), ("RSVP_REMINDER", "Attendance confirmation reminder"), ("ACTION_REMINDER", "Action deadline reminder")], max_length=30, verbose_name="communication type")),
                ("delivery_status", models.CharField(choices=[("SENT", "Sent"), ("FAILED", "Failed")], max_length=20, verbose_name="delivery status")),
                ("recipient_name", models.CharField(max_length=200, verbose_name="recipient name")),
                ("recipient_email", models.EmailField(max_length=254, verbose_name="recipient email")),
                ("subject", models.CharField(max_length=300, verbose_name="subject")),
                ("message", models.TextField(verbose_name="message")),
                ("sent_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="sent at")),
                ("error_message", models.TextField(blank=True, verbose_name="error message")),
                ("action_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="communications", to="meetings.meetingactionitem", verbose_name="meeting action item")),
                ("attendee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="communications", to="meetings.meetingattendee", verbose_name="meeting participant")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_created_records", to=settings.AUTH_USER_MODEL, verbose_name="created by")),
                ("meeting", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="communications", to="meetings.meeting", verbose_name="meeting")),
                ("updated_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(app_label)s_%(class)s_updated_records", to=settings.AUTH_USER_MODEL, verbose_name="updated by")),
            ],
            options={
                "verbose_name": "meeting communication",
                "verbose_name_plural": "meeting communications",
                "ordering": ["-sent_at", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="meetingcommunicationlog",
            index=models.Index(fields=["meeting", "communication_type", "delivery_status"], name="meeting_comm_status_idx"),
        ),
    ]

