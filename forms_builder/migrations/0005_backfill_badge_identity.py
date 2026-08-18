from django.db import migrations


NAME_LABELS_EN = {
    "representative name",
    "participant name",
    "full name",
}
NAME_LABELS_SW = {
    "jina la mwakilishi",
    "jina la mshiriki",
    "jina kamili",
}
ORGANIZATION_LABELS_EN = {
    "institution name",
    "organization name",
    "organisation name",
}
ORGANIZATION_LABELS_SW = {
    "jina la taasisi",
    "jina la shirika",
}


def backfill_badge_identity(apps, schema_editor):
    form_submission = apps.get_model(
        "forms_builder",
        "FormSubmission",
    )
    form_answer = apps.get_model("forms_builder", "FormAnswer")

    for submission in form_submission.objects.all().iterator():
        badge_name = submission.badge_name
        badge_organization = submission.badge_organization
        answers = form_answer.objects.filter(
            submission_id=submission.pk
        ).select_related("question")

        for answer in answers:
            value = answer.text_value.strip()
            if not value:
                continue

            label_en = answer.question.label_en.strip().casefold()
            label_sw = answer.question.label_sw.strip().casefold()

            if label_en in NAME_LABELS_EN or label_sw in NAME_LABELS_SW:
                badge_name = value

            if (
                label_en in ORGANIZATION_LABELS_EN
                or label_sw in ORGANIZATION_LABELS_SW
            ):
                badge_organization = value

        submission.badge_name = badge_name
        submission.badge_organization = badge_organization
        submission.badge_title = (
            "Participant" if submission.language == "en" else "Mshiriki"
        )
        submission.save(
            update_fields=[
                "badge_name",
                "badge_organization",
                "badge_title",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            "forms_builder",
            "0004_participant_badge_identity",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_badge_identity,
            migrations.RunPython.noop,
        ),
    ]

