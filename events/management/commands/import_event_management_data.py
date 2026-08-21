import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from permits.models import Department


EVENT_TABLE_PREFIXES = (
    "events_",
    "forms_builder_",
    "checkin_",
    "conferences_",
    "meetings_",
)
CORE_LOCATION_TABLES = {
    "core_country",
    "core_region",
    "core_district",
    "core_council",
    "core_ward",
}
EXPECTED_EVENT_CODES = {"NESIF-2026", "ELIMU-2026", "TUZO-2026"}
RENAMED_EVENT_CODES = {"ELIMU-2026": "WEUUTz-2026"}


def _tables(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        if row[0].startswith(EVENT_TABLE_PREFIXES) or row[0] in CORE_LOCATION_TABLES
    }


def _columns(connection, table):
    return {row[1]: row for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _foreign_keys(connection, table):
    return list(connection.execute(f'PRAGMA foreign_key_list("{table}")'))


class Command(BaseCommand):
    help = (
        "Import the mature Event Management data from its SQLite database, "
        "assigning all imported events to the DSTI department."
    )

    def add_arguments(self, parser):
        parser.add_argument("source_database", type=Path)
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required confirmation that the destination event tables may be populated.",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Run again with --confirm after reviewing the source and backup paths.")
        source_path = options["source_database"].expanduser().resolve()
        destination_path = Path(settings.DATABASES["default"]["NAME"]).resolve()
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("This guarded importer currently supports SQLite only.")
        if not source_path.is_file():
            raise CommandError(f"Source database does not exist: {source_path}")
        if source_path == destination_path:
            raise CommandError("Source and destination databases must be different files.")
        dsti = Department.objects.filter(code="DSTI", is_active=True).first()
        if not dsti:
            raise CommandError("The active DSTI department is required before importing events.")

        source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        destination = sqlite3.connect(destination_path)
        source.row_factory = sqlite3.Row
        destination.row_factory = sqlite3.Row
        try:
            source_codes = {
                row[0]
                for row in source.execute("SELECT code FROM events_event")
            }
            if source_codes != EXPECTED_EVENT_CODES:
                raise CommandError(
                    "Source event codes must be exactly: "
                    + ", ".join(sorted(EXPECTED_EVENT_CODES))
                    + f". Found: {', '.join(sorted(source_codes)) or 'none'}."
                )
            existing = destination.execute("SELECT COUNT(*) FROM events_event").fetchone()[0]
            if existing:
                raise CommandError(
                    "Destination Event Management tables are not empty. "
                    "Import is intentionally non-destructive and has stopped."
                )

            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = destination_path.with_name(
                f"{destination_path.stem}-before-event-import-{timestamp}{destination_path.suffix}"
            )
            destination.commit()
            backup_connection = sqlite3.connect(backup_path)
            destination.backup(backup_connection)
            backup_connection.close()

            source_tables = _tables(source)
            destination_tables = _tables(destination)
            tables = sorted(source_tables & destination_tables)
            if "events_event" not in tables:
                raise CommandError("Event Management migrations must be applied before importing data.")

            copied = {}
            skipped = {}
            destination.execute("PRAGMA foreign_keys=OFF")
            destination.execute("BEGIN")
            for table in tables:
                source_columns = _columns(source, table)
                destination_columns = _columns(destination, table)
                common_columns = [
                    name for name in destination_columns if name in source_columns
                ]
                auth_foreign_keys = {
                    row[3]: row for row in _foreign_keys(destination, table)
                    if row[2] == "auth_user"
                }
                required_auth_columns = {
                    name for name in auth_foreign_keys
                    if destination_columns[name][3]
                }
                select_sql = (
                    "SELECT " + ", ".join(f'"{name}"' for name in common_columns)
                    + f' FROM "{table}"'
                )
                inserted = 0
                omitted = 0
                for source_row in source.execute(select_sql):
                    values = dict(source_row)
                    for column in auth_foreign_keys:
                        values[column] = None
                    if any(source_row[column] is not None for column in required_auth_columns):
                        omitted += 1
                        continue
                    if table == "events_event":
                        values["owning_department_id"] = dsti.pk
                        values["code"] = RENAMED_EVENT_CODES.get(
                            values["code"], values["code"]
                        )
                    insert_columns = list(values)
                    placeholders = ", ".join("?" for _ in insert_columns)
                    destination.execute(
                        f'INSERT INTO "{table}" ('
                        + ", ".join(f'"{name}"' for name in insert_columns)
                        + f") VALUES ({placeholders})",
                        [values[name] for name in insert_columns],
                    )
                    inserted += 1
                copied[table] = inserted
                if omitted:
                    skipped[table] = omitted

            violations = list(destination.execute("PRAGMA foreign_key_check"))
            if violations:
                destination.rollback()
                sample = "; ".join(
                    f"{row[0]} row {row[1]} -> {row[2]}" for row in violations[:10]
                )
                raise CommandError(
                    f"Import failed foreign-key validation and was rolled back: {sample}"
                )
            destination.commit()
            destination.execute("PRAGMA foreign_keys=ON")
        finally:
            source.close()
            destination.close()

        self.stdout.write(self.style.SUCCESS(
            "Imported Event Management data for NESIF-2026, WEUUTz-2026 and TUZO-2026."
        ))
        self.stdout.write(f"All three events are owned by DSTI (department id {dsti.pk}).")
        self.stdout.write(f"Safety backup: {backup_path}")
        self.stdout.write(
            "Imported rows: " + ", ".join(
                f"{table}={count}" for table, count in copied.items() if count
            )
        )
        if skipped:
            self.stdout.write(self.style.WARNING(
                "Skipped rows requiring unmapped legacy staff accounts: "
                + ", ".join(f"{table}={count}" for table, count in skipped.items())
            ))
