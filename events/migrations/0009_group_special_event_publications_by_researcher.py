import hashlib
import unicodedata

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _identity_key(full_name, institution):
    normalized_parts = []
    for value in (full_name, institution):
        normalized = unicodedata.normalize("NFKC", str(value or ""))
        normalized_parts.append(" ".join(normalized.split()).casefold())
    return hashlib.sha256("\x00".join(normalized_parts).encode("utf-8")).hexdigest()


def group_existing_rows(apps, schema_editor):
    Participant = apps.get_model("events", "SpecialEventParticipant")
    Publication = apps.get_model("events", "SpecialEventPublication")

    grouped = {}
    for participant in Participant.objects.order_by("event_id", "id"):
        key = (
            participant.event_id,
            _identity_key(participant.full_name, participant.institution),
        )
        grouped.setdefault(key, []).append(participant)

    for (event_id, identity_key), participants in grouped.items():
        participants.sort(key=lambda participant: (not participant.is_active, participant.pk))
        canonical = participants[0]
        canonical.identity_key = identity_key
        canonical.is_active = any(participant.is_active for participant in participants)
        canonical.save(update_fields=["identity_key", "is_active"])

        for participant in participants:
            Publication.objects.create(
                participant_id=canonical.pk,
                source_sheet=participant.source_sheet,
                source_number=participant.source_number,
                source_row_index=participant.source_row_index,
                research_title=participant.research_title,
                award_category=participant.research_field,
                award_year="",
                is_active=participant.is_active,
                created_by_id=participant.created_by_id,
                updated_by_id=participant.updated_by_id,
            )

        for duplicate in participants[1:]:
            duplicate.delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("events", "0008_specialeventparticipant"),
    ]

    operations = [
        migrations.AddField(
            model_name="specialeventparticipant",
            name="identity_key",
            field=models.CharField(
                default="",
                editable=False,
                max_length=64,
                verbose_name="researcher identity key",
            ),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name="SpecialEventPublication",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="is active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="updated at")),
                ("source_sheet", models.CharField(max_length=100, verbose_name="source sheet")),
                ("source_number", models.CharField(max_length=50, verbose_name="source row number")),
                (
                    "source_row_index",
                    models.PositiveIntegerField(
                        default=0,
                        editable=False,
                        verbose_name="source row position",
                    ),
                ),
                ("research_title", models.TextField(verbose_name="research title")),
                ("award_category", models.TextField(verbose_name="award category")),
                ("award_year", models.CharField(max_length=50, verbose_name="award year")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_created_records",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="created by",
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="publications",
                        to="events.specialeventparticipant",
                        verbose_name="researcher",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_updated_records",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="updated by",
                    ),
                ),
            ],
            options={
                "verbose_name": "special event publication",
                "verbose_name_plural": "special event publications",
                "ordering": ["source_sheet", "source_row_index", "research_title"],
            },
        ),
        migrations.RunPython(group_existing_rows, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="specialeventparticipant",
            name="unique_special_event_source_row",
        ),
        migrations.RemoveIndex(
            model_name="specialeventparticipant",
            name="special_event_participant_idx",
        ),
        migrations.RemoveField(model_name="specialeventparticipant", name="research_field"),
        migrations.RemoveField(model_name="specialeventparticipant", name="research_title"),
        migrations.RemoveField(model_name="specialeventparticipant", name="source_number"),
        migrations.RemoveField(model_name="specialeventparticipant", name="source_row_index"),
        migrations.RemoveField(model_name="specialeventparticipant", name="source_sheet"),
        migrations.AlterModelOptions(
            name="specialeventparticipant",
            options={
                "ordering": ["event", "full_name", "institution"],
                "verbose_name": "special event researcher",
                "verbose_name_plural": "special event researchers",
            },
        ),
        migrations.AlterField(
            model_name="specialeventparticipant",
            name="full_name",
            field=models.CharField(max_length=300, verbose_name="researcher name"),
        ),
        migrations.AddConstraint(
            model_name="specialeventparticipant",
            constraint=models.UniqueConstraint(
                fields=("event", "identity_key"),
                name="unique_special_event_researcher",
            ),
        ),
        migrations.AddIndex(
            model_name="specialeventparticipant",
            index=models.Index(
                fields=["event", "is_active"],
                name="special_event_researcher_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="specialeventpublication",
            constraint=models.UniqueConstraint(
                fields=("participant", "source_sheet", "source_number"),
                name="unique_special_event_publication_source",
            ),
        ),
        migrations.AddIndex(
            model_name="specialeventpublication",
            index=models.Index(
                fields=["participant", "is_active"],
                name="special_event_publication_idx",
            ),
        ),
    ]

