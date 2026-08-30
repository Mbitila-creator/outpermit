from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forms_builder", "0034_remove_displaylogicgroup_logic_group_is_root_target_or_nested_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventform",
            name="qr_record_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Allow administrators to create public QR verification cards from "
                    "completed submissions to this form. Submitted answers will be visible "
                    "to anyone who scans the QR code."
                ),
                verbose_name="enable individual QR records",
            ),
        ),
    ]
