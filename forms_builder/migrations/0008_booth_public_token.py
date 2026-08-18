import uuid

from django.db import migrations, models


def populate_booth_tokens(apps, schema_editor):
    Booth = apps.get_model("forms_builder", "Booth")

    for booth in Booth.objects.filter(public_token__isnull=True).iterator():
        booth.public_token = uuid.uuid4()
        booth.save(update_fields=["public_token"])


class Migration(migrations.Migration):

    dependencies = [
        (
            "forms_builder",
            "0007_booth_booth_unique_booth_code_per_event",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="booth",
            name="public_token",
            field=models.UUIDField(
                editable=False,
                null=True,
            ),
        ),
        migrations.RunPython(
            populate_booth_tokens,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="booth",
            name="public_token",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                verbose_name="booth public token",
            ),
        ),
    ]

