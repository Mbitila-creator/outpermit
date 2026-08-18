import uuid

from django.db import migrations, models


def populate_response_tokens(apps, schema_editor):
    MeetingAttendee = apps.get_model("meetings", "MeetingAttendee")
    for attendee in MeetingAttendee.objects.filter(
        response_token__isnull=True,
    ).iterator():
        attendee.response_token = uuid.uuid4()
        attendee.save(update_fields=["response_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("meetings", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="meetingattendee",
            name="preferred_language",
            field=models.CharField(
                choices=[("sw", "Kiswahili"), ("en", "English")],
                default="sw",
                max_length=5,
                verbose_name="preferred language",
            ),
        ),
        migrations.AddField(
            model_name="meetingattendee",
            name="response_token",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                null=True,
                verbose_name="invitation response token",
            ),
        ),
        migrations.RunPython(
            populate_response_tokens,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="meetingattendee",
            name="response_token",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                verbose_name="invitation response token",
            ),
        ),
    ]

