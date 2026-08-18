from django.db import migrations


def remove_legacy_summit_tables(apps, schema_editor):
    """Permanently discard the replaced Summit events and participants."""
    existing_tables = set(schema_editor.connection.introspection.table_names())
    quoted = schema_editor.connection.ops.quote_name
    with schema_editor.connection.cursor() as cursor:
        for table_name in ("summit_summitparticipant", "summit_summitevent"):
            if table_name in existing_tables:
                cursor.execute(f"DROP TABLE {quoted(table_name)}")


class Migration(migrations.Migration):
    dependencies = [("core", "0004_council_district")]

    operations = [
        migrations.RunPython(remove_legacy_summit_tables, migrations.RunPython.noop),
    ]
