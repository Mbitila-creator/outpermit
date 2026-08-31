import csv
import re
import secrets
import uuid
from types import SimpleNamespace
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from events.auth import User, has_event_role
from events.models import Event, EventTimetable
from events.access import events_visible_to
from .models import (
    Booth,
    BoothInterest,
    CertificateRecord,
    EventForm,
    FormAnswer,
    FormQuestion,
    FormSubmission,
    NotificationLog,
    Payment,
    QuestionOption,
)
from .notifications import (
    process_due_reminders, send_payment_notification, send_submission_notification,
)
from .display_logic import (
    group_spec_json,
    question_passes_visual_validation,
    question_is_required,
    required_group_spec_json,
    validation_group_spec_json,
    target_is_visible,
)
from .expressions import ExpressionError, evaluate_expression
from .services import (
    booth_detail_url,
    certificate_number,
    certificate_is_for_institution,
    certificate_display_recipient_name,
    certificate_qr_logo_path,
    certificate_recipient_name,
    certificate_verification_url,
    event_date_range,
    generate_certificate_pdf,
    generate_qr_png,
    participant_check_in_url,
    sync_badge_identity_from_answers,
    safe_spreadsheet_value,
    payment_amount_for_submission,
    weuutz_event_sentence_html,
)


EVALUATION_REPORT_ROLES = {
    User.Role.SYSTEM_ADMIN,
    User.Role.EVENT_ADMIN,
    User.Role.REPORT_OFFICER,
    User.Role.DIRECTOR,
    User.Role.ASSISTANT_DIRECTOR,
}


def normalize_registration_email(value):
    return "".join((value or "").casefold().split())


def normalize_registration_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("0"):
        return f"255{digits[1:]}"
    return digits


def registration_identity_conflicts(candidates, email, phone):
    """Return a duplicate and the identity fields that conflict."""
    normalized_email = normalize_registration_email(email)
    normalized_phone = normalize_registration_phone(phone)
    duplicate = None
    email_conflict = False
    phone_conflict = False

    for candidate in candidates:
        candidate_email = normalize_registration_email(candidate.submitter_email)
        candidate_phone = normalize_registration_phone(candidate.submitter_phone)
        matches_email = bool(
            normalized_email
            and candidate_email
            and normalized_email == candidate_email
        )
        matches_phone = bool(
            normalized_phone
            and candidate_phone
            and normalized_phone == candidate_phone
        )
        if matches_email or matches_phone:
            duplicate = duplicate or candidate
            email_conflict = email_conflict or matches_email
            phone_conflict = phone_conflict or matches_phone

    return duplicate, email_conflict, phone_conflict


@csrf_exempt
@require_http_methods(["POST"])
def run_due_reminders(request):
    configured_token = settings.REMINDER_SCHEDULER_TOKEN
    if not configured_token:
        return JsonResponse(
            {"detail": "Reminder scheduler is not configured."},
            status=503,
        )

    authorization = request.headers.get("Authorization", "")
    scheme, separator, supplied_token = authorization.partition(" ")
    dedicated_token = request.headers.get("X-Reminder-Token", "")
    authorized = (
        bool(dedicated_token)
        and secrets.compare_digest(dedicated_token, configured_token)
    ) or (
        bool(separator)
        and scheme.lower() == "bearer"
        and secrets.compare_digest(supplied_token, configured_token)
    )
    if not authorized:
        return JsonResponse({"detail": "Forbidden."}, status=403)

    processed = process_due_reminders(request=request)
    response = JsonResponse({"processed": len(processed)})
    response["Cache-Control"] = "no-store"
    return response


def can_view_evaluation_reports(user):
    return bool(
        user.is_authenticated
        and (
            user.is_superuser
            or has_event_role(user, EVALUATION_REPORT_ROLES)
        )
    )


evaluation_report_required = user_passes_test(
    can_view_evaluation_reports,
    login_url="login",
)


def localized_answer_value(answer, language):
    selected_options = list(answer.selected_options.all())
    if selected_options:
        return ", ".join(
            option.label_en if language == "en" else option.label_sw
            for option in selected_options
        )
    if answer.uploaded_file:
        return answer.uploaded_file.url
    if answer.text_value:
        return answer.text_value
    if answer.number_value is not None:
        return str(answer.number_value)
    if answer.date_value:
        return answer.date_value.isoformat()
    if answer.datetime_value:
        return answer.datetime_value.isoformat()
    if answer.boolean_value is not None:
        return _("Yes") if answer.boolean_value else _("No")
    return ""


def numeric_rating_value(answer):
    value = answer.number_value
    if value is None:
        selected_options = list(answer.selected_options.all())
        if len(selected_options) == 1:
            try:
                value = Decimal(selected_options[0].value)
            except (InvalidOperation, TypeError, ValueError):
                value = None
    if value is not None and Decimal("1") <= value <= Decimal("5"):
        return value
    return None


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")


def public_booths_queryset():
    return Booth.objects.select_related(
        "event",
        "event__venue",
        "assigned_submission",
    ).filter(
        is_active=True,
        event__is_active=True,
        event__is_public=True,
        event__booth_enabled=True,
        assigned_submission__isnull=False,
        status__in=[Booth.Status.ASSIGNED, Booth.Status.READY],
    )


@require_http_methods(["GET"])
def booth_directory(request, event_slug):
    event = get_object_or_404(
        Event.objects.select_related("venue"),
        slug=event_slug,
        is_active=True,
        is_public=True,
        booth_enabled=True,
    )
    booths = public_booths_queryset().filter(event=event).order_by(
        "zone_en",
        "code",
    )
    return render(
        request,
        "forms_builder/booth_directory.html",
        {"event": event, "booths": booths},
    )


@require_http_methods(["GET", "POST"])
def booth_detail(request, public_token):
    booth = get_object_or_404(
        public_booths_queryset(),
        public_token=public_token,
    )
    offerings = list(
        booth.offerings.filter(is_active=True).order_by(
            "display_order",
            "name_en",
        )
    )
    interest_errors = {}
    interest_values = {}

    if request.method == "POST":
        interest_values = {
            "visitor_name": request.POST.get("visitor_name", "").strip(),
            "email": request.POST.get("email", "").strip(),
            "phone": request.POST.get("phone", "").strip(),
            "message": request.POST.get("message", "").strip(),
            "offering": request.POST.get("offering", "").strip(),
        }
        if not interest_values["email"] and not interest_values["phone"]:
            interest_errors["contact"] = _(
                "Enter an email address or phone number."
            )
        if interest_values["email"] and "@" not in interest_values["email"]:
            interest_errors["email"] = _("Enter a valid email address.")

        selected_offering = None
        if interest_values["offering"]:
            selected_offering = next(
                (
                    offering
                    for offering in offerings
                    if str(offering.pk) == interest_values["offering"]
                ),
                None,
            )
            if selected_offering is None:
                interest_errors["offering"] = _("Select a valid option.")

        if not interest_errors:
            BoothInterest.objects.create(
                booth=booth,
                offering=selected_offering,
                visitor_name=interest_values["visitor_name"],
                email=interest_values["email"],
                phone=interest_values["phone"],
                message=interest_values["message"],
                language=request.LANGUAGE_CODE,
            )
            return redirect(
                f"{request.path}?interest=success#visitor-interest"
            )

    return render(
        request,
        "forms_builder/booth_detail.html",
        {
            "booth": booth,
            "event": booth.event,
            "submission": booth.assigned_submission,
            "offerings": offerings,
            "interest_errors": interest_errors,
            "interest_values": interest_values,
            "interest_success": request.GET.get("interest") == "success",
        },
    )


@require_http_methods(["GET"])
def booth_qr(request, public_token):
    booth = get_object_or_404(
        public_booths_queryset(),
        public_token=public_token,
    )
    image_data = generate_qr_png(
        booth_detail_url(
            booth,
            request=request,
            language=request.LANGUAGE_CODE,
        )
    )
    response = HttpResponse(image_data, content_type="image/png")
    if request.GET.get("download") == "1":
        response["Content-Disposition"] = (
            f'attachment; filename="{booth.event.code}-{booth.code}-qr.png"'
        )
    response["X-Content-Type-Options"] = "nosniff"
    return response


def evaluation_forms_queryset(user):
    return EventForm.objects.filter(
        event__in=events_visible_to(user),
        form_type=EventForm.FormType.EVALUATION,
        is_active=True,
    ).select_related("event").order_by("-event__starts_at", "name_en")


@evaluation_report_required
@require_http_methods(["GET"])
def evaluation_reports(request):
    evaluation_forms = evaluation_forms_queryset(request.user)
    selected_form_id = request.GET.get("form", "").strip()
    selected_form = (
        get_object_or_404(evaluation_forms, pk=selected_form_id)
        if selected_form_id
        else evaluation_forms.first()
    )
    questions = []
    response_rows = []
    rating_statistics = []
    total_responses = 0
    overall_average = None

    if selected_form:
        questions = list(
            FormQuestion.objects.filter(
                section__event_form=selected_form,
                section__is_active=True,
                is_active=True,
            ).select_related("section").order_by(
                "section__display_order",
                "display_order",
                "id",
            )
        )
        submissions = list(
            FormSubmission.objects.filter(
                event_form=selected_form,
                is_active=True,
                is_complete=True,
            ).prefetch_related(
                "answers__question",
                "answers__selected_options",
            ).order_by("-created_at")
        )
        total_responses = len(submissions)
        rating_values = {question.pk: [] for question in questions}

        for submission in submissions:
            answers_by_question = {
                answer.question_id: answer
                for answer in submission.answers.all()
            }
            row_answers = []
            for question in questions:
                answer = answers_by_question.get(question.pk)
                row_answers.append(
                    localized_answer_value(answer, request.LANGUAGE_CODE)
                    if answer
                    else ""
                )
                if answer:
                    rating_value = numeric_rating_value(answer)
                    if rating_value is not None:
                        rating_values[question.pk].append(rating_value)
            response_rows.append(
                {"submission": submission, "answers": row_answers}
            )

        all_ratings = []
        for question in questions:
            values = rating_values[question.pk]
            if values:
                average = sum(values) / len(values)
                all_ratings.extend(values)
                rating_statistics.append(
                    {
                        "label": (
                            question.label_en
                            if request.LANGUAGE_CODE == "en"
                            else question.label_sw
                        ),
                        "average": round(average, 2),
                        "count": len(values),
                    }
                )
        if all_ratings:
            overall_average = round(
                sum(all_ratings) / len(all_ratings),
                2,
            )

    return render(
        request,
        "forms_builder/evaluation_reports.html",
        {
            "evaluation_forms": evaluation_forms,
            "selected_form": selected_form,
            "questions": questions,
            "response_rows": response_rows,
            "rating_statistics": rating_statistics,
            "total_responses": total_responses,
            "overall_average": overall_average,
        },
    )


@evaluation_report_required
@require_http_methods(["GET"])
def evaluation_report_csv(request):
    selected_form = get_object_or_404(
        evaluation_forms_queryset(request.user),
        pk=request.GET.get("form"),
    )
    questions = list(
        FormQuestion.objects.filter(
            section__event_form=selected_form,
            section__is_active=True,
            is_active=True,
        ).order_by(
            "section__display_order",
            "display_order",
            "id",
        )
    )
    submissions = FormSubmission.objects.filter(
        event_form=selected_form,
        is_active=True,
        is_complete=True,
    ).prefetch_related(
        "answers__question",
        "answers__selected_options",
    ).order_by("created_at")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")
    response["Content-Disposition"] = (
        f'attachment; filename="{selected_form.event.code}-evaluation.csv"'
    )
    writer = csv.writer(response)
    question_labels = [
        question.label_en
        if request.LANGUAGE_CODE == "en"
        else question.label_sw
        for question in questions
    ]
    writer.writerow(
        [
            _("Evaluation reference"),
            _("Submitted on"),
            _("Language"),
            _("Email address"),
            _("Phone number"),
            *question_labels,
        ]
    )
    for submission in submissions:
        answers_by_question = {
            answer.question_id: answer
            for answer in submission.answers.all()
        }
        values = [
            submission.reference_number,
            submission.created_at.isoformat(),
            submission.language,
            submission.submitter_email,
            submission.submitter_phone,
        ]
        values.extend(
            localized_answer_value(
                answers_by_question.get(question.pk),
                request.LANGUAGE_CODE,
            )
            if answers_by_question.get(question.pk)
            else ""
            for question in questions
        )
        writer.writerow([safe_spreadsheet_value(value) for value in values])
    return response


def get_public_event_form(request, event_slug, form_slug):
    queryset = EventForm.objects.select_related(
            "event",
            "event__category",
            "event__venue",
            "event__venue__council",
            "event__venue__council__region",
        ).prefetch_related(
            "sections__questions__options",
        ).filter(
        event__slug=event_slug,
        slug=form_slug,
        event__is_active=True,
        is_active=True,
    )
    staff_preview = bool(
        request.method == "GET"
        and request.GET.get("preview") == "1"
        and can_view_evaluation_reports(request.user)
    )
    if staff_preview:
        queryset = queryset.filter(event__in=events_visible_to(request.user))
    else:
        queryset = queryset.filter(event__is_public=True, is_published=True)
    event_form = get_object_or_404(queryset)
    is_evaluation = event_form.form_type == EventForm.FormType.EVALUATION
    form_enabled = (
        event_form.event.evaluation_enabled
        if is_evaluation
        else event_form.event.registration_enabled
    )
    if not form_enabled and not staff_preview:
        raise Http404("This public form is not enabled.")

    return event_form


def form_availability(event_form):
    current_time = timezone.now()
    event = event_form.event
    is_evaluation = event_form.form_type == EventForm.FormType.EVALUATION

    opening_dates = [date for date in (
        event_form.opens_at,
        None if is_evaluation else event.registration_opens_at,
    ) if date]
    form_not_open = bool(opening_dates and current_time < max(opening_dates))

    closing_dates = [date for date in (
        event_form.closes_at,
        None if is_evaluation else event.registration_closes_at,
        None if is_evaluation else event.ends_at,
    ) if date]
    form_closed = bool(closing_dates and current_time > min(closing_dates))

    if not is_evaluation:
        if event.status == Event.Status.DRAFT:
            form_not_open = True
        elif event.status in {
            Event.Status.REGISTRATION_CLOSED,
            Event.Status.COMPLETED,
            Event.Status.CANCELLED,
        }:
            form_closed = True

    return form_not_open, form_closed


def validate_question_answer(request, question, *, enforce_required=True, override_value=None):
    field_name = f"question_{question.id}"
    question_type = question.question_type

    if question_type == FormQuestion.QuestionType.MULTIPLE_CHOICE:
        raw_value = request.POST.getlist(field_name)
    elif question_type in {
        FormQuestion.QuestionType.FILE,
        FormQuestion.QuestionType.IMAGE,
    }:
        raw_value = request.FILES.get(field_name)
    elif override_value is not None:
        raw_value = str(override_value)
    else:
        raw_value = request.POST.get(field_name, "").strip()

    is_empty = (
        raw_value is None
        or raw_value == ""
        or raw_value == []
    )

    if enforce_required and question.is_required and is_empty:
        return None, "This field is required."

    if is_empty:
        return {
            "question": question,
            "empty": True,
        }, None

    result = {
        "question": question,
        "empty": False,
        "text_value": "",
        "number_value": None,
        "date_value": None,
        "datetime_value": None,
        "boolean_value": None,
        "uploaded_file": None,
        "selected_options": [],
    }

    if question_type in {
        FormQuestion.QuestionType.SHORT_TEXT,
        FormQuestion.QuestionType.LONG_TEXT,
        FormQuestion.QuestionType.EMAIL,
        FormQuestion.QuestionType.PHONE,
    }:
        text_value = str(raw_value).strip()

        if (
            question.minimum_length is not None
            and len(text_value) < question.minimum_length
        ):
            return None, (
                f"Enter at least {question.minimum_length} characters."
            )

        if (
            question.maximum_length is not None
            and len(text_value) > question.maximum_length
        ):
            return None, (
                f"Enter no more than {question.maximum_length} characters."
            )

        if (
            question_type == FormQuestion.QuestionType.EMAIL
            and "@" not in text_value
        ):
            return None, "Enter a valid email address."

        result["text_value"] = text_value

    elif question_type in {
        FormQuestion.QuestionType.NUMBER,
        FormQuestion.QuestionType.CALCULATED,
    }:
        try:
            number_value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            return None, "Enter a valid number."

        if (
            question.minimum_value is not None
            and number_value < question.minimum_value
        ):
            return None, (
                f"The minimum allowed value is "
                f"{question.minimum_value}."
            )

        if (
            question.maximum_value is not None
            and number_value > question.maximum_value
        ):
            return None, (
                f"The maximum allowed value is "
                f"{question.maximum_value}."
            )

        result["number_value"] = number_value

    elif question_type == FormQuestion.QuestionType.DATE:
        date_value = parse_date(str(raw_value))

        if date_value is None:
            return None, "Enter a valid date."

        result["date_value"] = date_value

    elif question_type == FormQuestion.QuestionType.DATETIME:
        datetime_value = parse_datetime(str(raw_value))

        if datetime_value is None:
            return None, "Enter a valid date and time."

        if timezone.is_naive(datetime_value):
            datetime_value = timezone.make_aware(datetime_value)

        result["datetime_value"] = datetime_value

    elif question_type == FormQuestion.QuestionType.YES_NO:
        if raw_value not in {"yes", "no"}:
            return None, "Select Yes or No."

        result["boolean_value"] = raw_value == "yes"

    elif question_type in {
        FormQuestion.QuestionType.SINGLE_CHOICE,
        FormQuestion.QuestionType.DROPDOWN,
    }:
        option = QuestionOption.objects.filter(
            question=question,
            value=raw_value,
            is_active=True,
        ).first()

        if option is None:
            return None, "Select a valid option."

        if not choice_option_is_available(request, question, option):
            return None, "This option is not available for the earlier answer selected."

        result["selected_options"] = [option]

    elif question_type == FormQuestion.QuestionType.MULTIPLE_CHOICE:
        options = list(
            QuestionOption.objects.filter(
                question=question,
                value__in=raw_value,
                is_active=True,
            )
        )

        if len(options) != len(set(raw_value)):
            return None, "One or more selected options are invalid."

        if any(not choice_option_is_available(request, question, option) for option in options):
            return None, "One or more selected options are not available for the earlier answer selected."

        result["selected_options"] = options

    elif question_type in {
        FormQuestion.QuestionType.FILE,
        FormQuestion.QuestionType.IMAGE,
    }:
        result["uploaded_file"] = raw_value

    else:
        result["text_value"] = str(raw_value).strip()

    return result, None


def choice_option_is_available(request, question, option):
    """Enforce cascading-choice filters independently of browser JavaScript."""
    if not question.choice_filter_question_id or not option.filter_value_list:
        return True
    controlling_values = request.POST.getlist(
        f"question_{question.choice_filter_question_id}"
    )
    return bool(set(controlling_values) & set(option.filter_value_list))


def expression_answer_values(request, questions):
    """Return trusted calculated values and raw scalar answers keyed by question id."""
    values = {}
    calculated = []
    for question in questions:
        field_name = f"question_{question.id}"
        if question.question_type == FormQuestion.QuestionType.CALCULATED:
            calculated.append(question)
            continue
        if question.question_type == FormQuestion.QuestionType.MULTIPLE_CHOICE:
            values[question.id] = request.POST.getlist(field_name)
            continue
        raw = request.POST.get(field_name, "").strip()
        if question.question_type == FormQuestion.QuestionType.NUMBER and raw:
            try:
                values[question.id] = Decimal(raw)
            except InvalidOperation:
                values[question.id] = raw
        elif question.question_type == FormQuestion.QuestionType.YES_NO:
            values[question.id] = raw == "yes" if raw else ""
        else:
            values[question.id] = raw

    unresolved = list(calculated)
    for _ in range(len(calculated) + 1):
        progressed = False
        for question in unresolved[:]:
            try:
                value = evaluate_expression(question.calculation_expression, values)
            except ExpressionError:
                continue
            quantizer = Decimal(1).scaleb(-question.calculation_decimal_places)
            values[question.id] = Decimal(value).quantize(quantizer)
            unresolved.remove(question)
            progressed = True
        if not unresolved or not progressed:
            break
    return values, unresolved


def draft_answer_value(answer):
    """Return the stored form-control value for restoring a draft answer."""
    selected_values = list(
        answer.selected_options.values_list("value", flat=True)
    )
    if selected_values:
        return selected_values
    if answer.text_value:
        return answer.text_value
    if answer.number_value is not None:
        return str(answer.number_value)
    if answer.date_value:
        return answer.date_value.isoformat()
    if answer.datetime_value:
        return answer.datetime_value.strftime("%Y-%m-%dT%H:%M")
    if answer.boolean_value is not None:
        return "yes" if answer.boolean_value else "no"
    return ""


def save_answer_data(submission, validated_answers):
    """Replace a submission's answers with the supplied validated values."""
    submission.answers.all().delete()
    for answer_data in validated_answers:
        if answer_data.get("empty"):
            continue
        answer_data = answer_data.copy()
        selected_options = answer_data.pop("selected_options", [])
        question = answer_data.pop("question")
        answer_data.pop("empty", None)
        answer = FormAnswer.objects.create(
            submission=submission,
            question=question,
            repeat_index=answer_data.pop("repeat_index", 0),
            **answer_data,
        )
        if selected_options:
            answer.selected_options.set(selected_options)


def section_is_visible_for_submission(request, section):
    """Apply a section's legacy or advanced display logic on the server."""
    return target_is_visible(request, section)


def question_is_visible_for_submission(request, question):
    """Apply a question's legacy or advanced display logic on the server."""
    return target_is_visible(request, question)


@require_http_methods(["GET", "POST"])
def public_event_form(request, event_slug, form_slug):
    event_form = get_public_event_form(
        request=request,
        event_slug=event_slug,
        form_slug=form_slug,
    )

    form_not_open, form_closed = form_availability(event_form)

    sections = list(
        event_form.sections
        .filter(is_active=True)
        .prefetch_related(
            "questions__options",
            "display_logic__rules",
            "questions__display_logic__rules",
            "questions__required_logic__rules",
            "questions__validation_logic__rules",
        )
        .order_by("display_order", "id")
    )
    for section in sections:
        section.display_logic_json = group_spec_json(section)
        active_questions = [
            question for question in section.questions.all()
            if question.is_active
        ]
        section.active_questions = active_questions
        for question in active_questions:
            question.display_logic_json = group_spec_json(question)
            question.required_logic_json = required_group_spec_json(question)
            question.validation_logic_json = validation_group_spec_json(question)
        section.likert_questions = [
            question for question in active_questions
            if section.display_order in {2, 3}
            and (section.display_order == 2 or question.display_order <= 8)
            and question.question_type
            == FormQuestion.QuestionType.SINGLE_CHOICE
            and len([
                option for option in question.options.all()
                if option.is_active
            ]) == 5
        ]
        section.regular_questions = [
            question for question in active_questions
            if question not in section.likert_questions
        ]
        section.use_likert_matrix = bool(section.likert_questions)
        section.likert_options = (
            [
                option for option in section.likert_questions[0].options.all()
                if option.is_active
            ]
            if section.use_likert_matrix
            else []
        )

    language_code = request.LANGUAGE_CODE
    is_evaluation = event_form.form_type == EventForm.FormType.EVALUATION
    staff_preview = bool(
        request.method == "GET"
        and request.GET.get("preview") == "1"
        and can_view_evaluation_reports(request.user)
        and events_visible_to(request.user).filter(pk=event_form.event_id).exists()
    )
    participant_registration = None
    draft_submission = None
    draft_answer_values = {}
    draft_token = (
        request.GET.get("draft", "").strip()
        or request.POST.get("_draft_token", "").strip()
    )
    participant_token = request.GET.get("participant", "").strip()
    if participant_token:
        try:
            participant_token = uuid.UUID(participant_token)
        except (ValueError, AttributeError):
            raise Http404("Invalid participant portal link.")
        participant_registration = FormSubmission.objects.filter(
            participant_token=participant_token,
            event_form__event=event_form.event,
            event_form__form_type__in=[
                EventForm.FormType.REGISTRATION,
                EventForm.FormType.EXHIBITOR,
                EventForm.FormType.SPEAKER,
            ],
            is_active=True,
            is_complete=True,
        ).first()
    if (
        event_form.requires_participant_registration
        and participant_registration is None
        and not staff_preview
    ):
        return redirect("forms_builder:registration_status")

    if is_evaluation and participant_registration is not None:
        draft_submission = (
            FormSubmission.objects.filter(
                event_form=event_form,
                registration_submission=participant_registration,
                is_active=True,
                is_complete=False,
            )
            .prefetch_related("answers__selected_options")
            .order_by("pk")
            .first()
        )
    elif not is_evaluation and draft_token:
        try:
            draft_token = uuid.UUID(draft_token)
        except (ValueError, AttributeError):
            raise Http404("Invalid draft link.")
        draft_submission = (
            FormSubmission.objects.filter(
                event_form=event_form,
                participant_token=draft_token,
                registration_submission__isnull=True,
                is_active=True,
                is_complete=False,
            )
            .prefetch_related("answers__selected_options")
            .first()
        )
        if draft_submission is None:
            raise Http404("This registration draft was not found.")

    if request.method == "GET" and draft_submission is not None:
        draft_answer_values = {
            (
                str(answer.question_id)
                if not answer.repeat_index
                else f"{answer.question_id}__repeat_{answer.repeat_index}"
            ): draft_answer_value(answer)
            for answer in draft_submission.answers.all()
        }

    if request.method == "POST":
        save_draft = request.POST.get("_save_draft") == "1"
        if save_draft and (
            (
                is_evaluation
                and participant_registration is None
            )
            or staff_preview
        ):
            return JsonResponse(
                {"success": False, "message": "Draft saving is unavailable."},
                status=403,
            )
        if form_not_open:
            return JsonResponse(
                {
                    "success": False,
                    "message": "This form is not open yet.",
                    "errors": {},
                },
                status=400,
            )

        if form_closed:
            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "The submission period for this form has ended."
                    ),
                    "errors": {},
                },
                status=400,
            )

        if (
            is_evaluation
            and not save_draft
            and not event_form.allow_multiple_submissions
        ):
            previous_submission = None
            if participant_registration is not None:
                previous_submission = FormSubmission.objects.filter(
                    event_form=event_form,
                    registration_submission=participant_registration,
                    is_complete=True,
                ).first()
            elif request.user.is_authenticated:
                previous_submission = FormSubmission.objects.filter(
                    event_form=event_form,
                    submitted_by=request.user,
                    is_complete=True,
                ).first()
            else:
                previous_reference = request.session.get(
                    "evaluation_submissions",
                    {},
                ).get(str(event_form.pk))
                if previous_reference:
                    previous_submission = FormSubmission.objects.filter(
                        event_form=event_form,
                        reference_number=previous_reference,
                        is_complete=True,
                    ).first()

            if previous_submission:
                return JsonResponse(
                    {
                        "success": False,
                        "duplicate": True,
                        "message": _(
                            "You have already submitted this evaluation."
                        ),
                        "redirect_url": reverse(
                            "forms_builder:submission_success",
                            kwargs={
                                "reference_number": previous_submission.reference_number,
                            },
                        ),
                    },
                    status=409,
                )

        questions = list(
            FormQuestion.objects.filter(
                section__event_form=event_form,
                section__is_active=True,
                is_active=True,
            )
            .select_related(
                "section", "section__condition_question", "condition_question"
            )
            .prefetch_related("options")
            .order_by(
                "section__display_order",
                "display_order",
                "id",
            )
        )

        errors = {}
        validated_answers = []
        expression_values, unresolved_calculations = expression_answer_values(
            request, questions
        )
        unresolved_ids = {item.id for item in unresolved_calculations}

        repeat_expression_cache = {}
        for question in questions:
            repeat_count = 1
            if question.section.is_repeatable:
                try:
                    repeat_count = int(request.POST.get(
                        f"_repeat_section_{question.section_id}",
                        question.section.minimum_repeats,
                    ))
                except (TypeError, ValueError):
                    repeat_count = question.section.minimum_repeats
                repeat_count = max(
                    question.section.minimum_repeats,
                    min(question.section.maximum_repeats, repeat_count),
                )

            for repeat_index in range(repeat_count):
                question_request = request
                current_expression_values = expression_values
                current_unresolved_ids = unresolved_ids
                if repeat_index:
                    repeat_post = request.POST.copy()
                    repeat_files = request.FILES.copy()
                    for candidate in questions:
                        source_name = f"question_{candidate.id}__repeat_{repeat_index}"
                        target_name = f"question_{candidate.id}"
                        if source_name in request.POST:
                            repeat_post.setlist(target_name, request.POST.getlist(source_name))
                        else:
                            repeat_post.pop(target_name, None)
                        if source_name in request.FILES:
                            repeat_files.setlist(target_name, request.FILES.getlist(source_name))
                        else:
                            repeat_files.pop(target_name, None)
                    question_request = SimpleNamespace(POST=repeat_post, FILES=repeat_files)
                    cache_key = (question.section_id, repeat_index)
                    if cache_key not in repeat_expression_cache:
                        values, unresolved = expression_answer_values(question_request, questions)
                        repeat_expression_cache[cache_key] = (
                            values,
                            {item.id for item in unresolved},
                        )
                    current_expression_values, current_unresolved_ids = repeat_expression_cache[cache_key]

                if not section_is_visible_for_submission(question_request, question.section):
                    continue
                if not question_is_visible_for_submission(question_request, question):
                    continue

                error_key = str(question.id) if not repeat_index else f"{question.id}__repeat_{repeat_index}"
                if (
                    question.question_type == FormQuestion.QuestionType.CALCULATED
                    and question.id in current_unresolved_ids
                ):
                    if not save_draft:
                        errors[error_key] = (
                            "This value could not be calculated. Complete its referenced questions."
                        )
                    continue

                answer_data, error = validate_question_answer(
                    question_request,
                    question,
                    enforce_required=(
                        not save_draft and question_is_required(question_request, question)
                    ),
                    override_value=(
                        current_expression_values.get(question.id)
                        if question.question_type == FormQuestion.QuestionType.CALCULATED
                        else None
                    ),
                )

                if error:
                    errors[error_key] = error
                else:
                    if (
                        not save_draft
                        and not answer_data.get("empty")
                        and not question_passes_visual_validation(question_request, question)
                    ):
                        errors[error_key] = (
                            question.validation_message_en
                            if language_code == "en"
                            else question.validation_message_sw or question.validation_message_en
                            or "This answer does not meet the validation rules."
                        )
                        continue
                    if question.validation_expression and not answer_data.get("empty"):
                        try:
                            valid = bool(evaluate_expression(
                                question.validation_expression, current_expression_values
                            ))
                        except ExpressionError:
                            valid = save_draft
                        if not valid:
                            errors[error_key] = (
                                question.validation_message_en
                                if language_code == "en"
                                else question.validation_message_sw or question.validation_message_en
                            )
                            continue
                    answer_data["repeat_index"] = repeat_index
                    validated_answers.append(answer_data)

        if errors:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Please correct the highlighted fields.",
                    "errors": errors,
                },
                status=400,
            )

        if save_draft:
            with transaction.atomic():
                EventForm.objects.select_for_update().get(pk=event_form.pk)
                draft_submission = (
                    FormSubmission.objects.select_for_update()
                    .filter(
                        pk=(draft_submission.pk if draft_submission else None),
                        is_active=True,
                        is_complete=False,
                    )
                    .order_by("pk")
                    .first()
                )
                if draft_submission is None:
                    draft_submission = FormSubmission.objects.create(
                        event_form=event_form,
                        registration_submission=participant_registration,
                        language=language_code,
                        submitter_email=(
                            participant_registration.submitter_email
                            if participant_registration else ""
                        ),
                        submitter_phone=(
                            participant_registration.submitter_phone
                            if participant_registration else ""
                        ),
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        is_complete=False,
                    )
                else:
                    draft_submission.language = language_code
                    draft_submission.ip_address = get_client_ip(request)
                    draft_submission.user_agent = request.META.get(
                        "HTTP_USER_AGENT", ""
                    )
                    draft_submission.save(update_fields=[
                        "language", "ip_address", "user_agent", "updated_at",
                    ])
                save_answer_data(draft_submission, validated_answers)
            return JsonResponse({
                "success": True,
                "draft_saved": True,
                "draft_token": str(draft_submission.participant_token),
            })

        email_answers = []
        phone_answers = []
        for answer_data in validated_answers:
            question = answer_data["question"]

            if (
                question.question_type
                == FormQuestion.QuestionType.EMAIL
            ):
                email_answers.append(
                    (question, answer_data.get("text_value", ""))
                )

            if (
                question.question_type
                == FormQuestion.QuestionType.PHONE
            ):
                phone_answers.append(
                    (question, answer_data.get("text_value", ""))
                )

        def representative_answer(answers):
            for question, value in answers:
                labels = f"{question.label_en} {question.label_sw}".lower()
                if "representative" in labels or "mwakilishi" in labels:
                    return value
            return answers[0][1] if answers else ""

        submitter_email = representative_answer(email_answers)
        submitter_phone = representative_answer(phone_answers)
        if participant_registration is not None:
            submitter_email = participant_registration.submitter_email
            submitter_phone = participant_registration.submitter_phone

        def find_duplicate_submission():
            if participant_registration is not None:
                duplicate = FormSubmission.objects.filter(
                    event_form=event_form,
                    registration_submission=participant_registration,
                    is_active=True,
                    is_complete=True,
                ).first()
                return duplicate, bool(duplicate), False
            candidates = FormSubmission.objects.filter(
                event_form=event_form,
                is_active=True,
                is_complete=True,
            ).only(
                "id", "submitter_email", "submitter_phone"
            )
            return registration_identity_conflicts(
                candidates,
                submitter_email,
                submitter_phone,
            )

        with transaction.atomic():
            EventForm.objects.select_for_update().get(pk=event_form.pk)
            (
                duplicate_submission,
                email_conflict,
                phone_conflict,
            ) = find_duplicate_submission()
            if duplicate_submission is not None:
                duplicate_message = _(
                    "A registration with this email address or phone number "
                    "already exists. Use the registration-status page to "
                    "access your existing registration."
                )
                conflicting_answers = []
                if email_conflict:
                    conflicting_answers.extend(email_answers)
                if phone_conflict:
                    conflicting_answers.extend(phone_answers)
                identity_errors = {
                    str(question.pk): duplicate_message
                    for question, _value in conflicting_answers
                }
                return JsonResponse(
                    {
                        "success": False,
                        "duplicate": True,
                        "message": duplicate_message,
                        "errors": identity_errors,
                    },
                    status=409,
                )
            submission = None
            if draft_submission is not None:
                submission = (
                    FormSubmission.objects.select_for_update()
                    .filter(
                        pk=draft_submission.pk,
                        is_active=True,
                        is_complete=False,
                    )
                    .order_by("pk")
                    .first()
                )
            if submission is None:
                submission = FormSubmission(event_form=event_form)
            submission.registration_submission = participant_registration
            submission.submitted_by = (
                request.user if request.user.is_authenticated else None
            )
            submission.language = language_code
            submission.submitter_email = submitter_email
            submission.submitter_phone = submitter_phone
            submission.ip_address = get_client_ip(request)
            submission.user_agent = request.META.get("HTTP_USER_AGENT", "")
            submission.is_complete = True
            if event_form.form_type in {
                EventForm.FormType.REGISTRATION,
                EventForm.FormType.EXHIBITOR,
                EventForm.FormType.SPEAKER,
            }:
                submission.review_status = FormSubmission.ReviewStatus.APPROVED
            submission.created_by = (
                request.user if request.user.is_authenticated else None
            )
            submission.updated_by = (
                request.user if request.user.is_authenticated else None
            )
            submission.save()
            save_answer_data(submission, validated_answers)

        if event_form.form_type != EventForm.FormType.EVALUATION:
            sync_badge_identity_from_answers(submission)
        elif not event_form.allow_multiple_submissions:
            evaluation_submissions = request.session.get(
                "evaluation_submissions",
                {},
            )
            evaluation_submissions[str(event_form.pk)] = (
                submission.reference_number
            )
            request.session["evaluation_submissions"] = (
                evaluation_submissions
            )

        if event_form.form_type != EventForm.FormType.EVALUATION:
            send_submission_notification(
                submission,
                NotificationLog.NotificationType.REGISTRATION_RECEIVED,
                request=request,
            )

        success_url = reverse(
            "forms_builder:submission_success",
            kwargs={"reference_number": submission.reference_number},
        )
        recent_submissions = request.session.get("recent_submissions", {})
        recent_submissions[submission.reference_number] = str(
            submission.participant_token
        )
        request.session["recent_submissions"] = recent_submissions

        return JsonResponse(
            {
                "success": True,
                "message": (
                    event_form.success_message_en
                    if language_code == "en"
                    else event_form.success_message_sw
                ),
                "reference_number": submission.reference_number,
                "redirect_url": success_url,
            }
        )

    context = {
        "event_form": event_form,
        "event": event_form.event,
        "sections": sections,
        "language_code": language_code,
        "form_not_open": form_not_open,
        "form_closed": form_closed,
        "is_evaluation": is_evaluation,
        "participant_registration": participant_registration,
        "staff_preview": staff_preview,
        "draft_answer_values": draft_answer_values,
        "draft_autosave_enabled": bool(
            not staff_preview
            and (
                not is_evaluation
                or participant_registration is not None
            )
        ),
        "draft_token": (
            str(draft_submission.participant_token)
            if draft_submission is not None else ""
        ),
    }

    return render(
        request,
        "forms_builder/public_event_form.html",
        context,
    )


def submission_success(request, reference_number):
    submission = get_object_or_404(
        FormSubmission.objects.select_related(
            "event_form",
            "event_form__event",
            "event_form__event__venue",
        ),
        reference_number=reference_number,
        is_complete=True,
    )

    return render(
        request,
        "forms_builder/submission_success.html",
        {
            "submission": submission,
            "event_form": submission.event_form,
            "event": submission.event_form.event,
            "is_evaluation": (
                submission.event_form.form_type
                == EventForm.FormType.EVALUATION
            ),
            "can_access_payment": (
                request.session.get("recent_submissions", {}).get(
                    submission.reference_number
                ) == str(submission.participant_token)
            ),
        },
    )


@require_http_methods(["GET"])
def participant_portal(request, participant_token):
    submission = get_object_or_404(
        FormSubmission.objects.select_related(
            "event_form__event",
            "event_form__event__category",
            "event_form__event__venue",
            "check_in",
            "booth_assignment",
            "certificate_record",
        ),
        participant_token=participant_token,
        is_active=True,
        is_complete=True,
        event_form__form_type__in=[
            EventForm.FormType.REGISTRATION,
            EventForm.FormType.EXHIBITOR,
            EventForm.FormType.SPEAKER,
        ],
    )
    event = submission.event_form.event
    timetable = EventTimetable.objects.filter(
        event=event, is_active=True, is_published=True
    ).first()
    certificate_record = getattr(submission, "certificate_record", None)
    latest_payment = submission.payments.order_by("-created_at").first()
    evaluation_form = None
    selected_conference_sessions = list(
        event.conference_sessions.filter(
            registration_option_value__in=submission.answers.filter(
                selected_options__is_active=True
            ).values_list("selected_options__value", flat=True),
            is_active=True,
        ).order_by("starts_at", "display_order", "id")
    )
    if event.evaluation_enabled:
        evaluation_form = EventForm.objects.filter(
            event=event,
            form_type=EventForm.FormType.EVALUATION,
            is_published=True,
            is_active=True,
        ).first()
    return render(
        request,
        "forms_builder/participant_portal.html",
        {
            "submission": submission,
            "event": event,
            "latest_payment": latest_payment,
            "checked_in": hasattr(submission, "check_in"),
            "certificate_authorized": (
                certificate_record is not None
                and certificate_record.status
                == CertificateRecord.Status.AUTHORIZED
            ),
            "certificate_record": certificate_record,
            "booth": getattr(submission, "booth_assignment", None),
            "evaluation_form": evaluation_form,
            "conference_feedback_available": event.category.is_conference,
            "selected_conference_sessions": selected_conference_sessions,
            "timetable": timetable,
        },
    )


@require_http_methods(["GET", "POST"])
def participant_payment(request, participant_token):
    submission = get_object_or_404(
        FormSubmission.objects.select_related("event_form__event"),
        participant_token=participant_token,
        is_active=True,
        is_complete=True,
        event_form__form_type__in=[
            EventForm.FormType.REGISTRATION,
            EventForm.FormType.EXHIBITOR,
            EventForm.FormType.SPEAKER,
        ],
        event_form__event__payment_enabled=True,
    )
    event = submission.event_form.event
    calculated_amount = payment_amount_for_submission(submission)
    pricing_rule = getattr(event, "quantity_pricing_rule", None)
    payment_currency = (
        pricing_rule.currency
        if pricing_rule and pricing_rule.is_active
        else event.payment_currency
    )
    latest_payment = submission.payments.order_by("-created_at").first()
    errors = {}

    if request.method == "POST":
        method = request.POST.get("method", "").strip()
        transaction_reference = request.POST.get(
            "transaction_reference", ""
        ).strip()
        proof = request.FILES.get("proof")
        valid_methods = {value for value, label in Payment.Method.choices}
        if method not in valid_methods:
            errors["method"] = _("Select a valid payment method.")
        if method != Payment.Method.CASH and not transaction_reference:
            errors["transaction_reference"] = _(
                "Enter the transaction reference."
            )
        if latest_payment and latest_payment.status in {
            Payment.Status.PENDING,
            Payment.Status.VERIFIED,
        }:
            errors["payment"] = _(
                "A payment is already pending or verified for this registration."
            )
        if calculated_amount is None:
            errors["payment"] = _(
                "The payment amount could not be calculated. Contact the event organizer."
            )

        if not errors:
            payment = Payment.objects.create(
                submission=submission,
                amount=calculated_amount,
                currency=payment_currency,
                method=method,
                transaction_reference=transaction_reference,
                proof=proof,
                paid_at=timezone.now(),
            )
            send_payment_notification(
                payment,
                NotificationLog.NotificationType.PAYMENT_RECEIVED,
                request=request,
            )
            return redirect(
                "forms_builder:participant_payment",
                participant_token=submission.participant_token,
            )

    return render(
        request,
        "forms_builder/participant_payment.html",
        {
            "submission": submission,
            "event": event,
            "latest_payment": latest_payment,
            "payment_errors": errors,
            "payment_methods": Payment.Method.choices,
            "calculated_amount": calculated_amount,
            "payment_currency": payment_currency,
        },
    )


@require_http_methods(["GET"])
def payment_receipt(request, participant_token):
    submission = get_object_or_404(
        FormSubmission.objects.select_related("event_form__event"),
        participant_token=participant_token,
        is_active=True,
    )
    payment = submission.payments.filter(
        status=Payment.Status.VERIFIED,
    ).order_by("-verified_at", "-created_at").first()
    if payment is None:
        raise Http404("No verified payment was found.")
    return render(request, "forms_builder/payment_receipt.html", {
        "submission": submission,
        "event": submission.event_form.event,
        "payment": payment,
        "receipt_number": f"PAY-{payment.created_at.year}-{payment.pk:06d}",
    })


def _verified_receipt_payment(participant_token, payment_id):
    return get_object_or_404(
        Payment.objects.select_related(
            "submission__event_form__event",
            "verified_by",
        ),
        pk=payment_id,
        submission__participant_token=participant_token,
        submission__is_active=True,
        status=Payment.Status.VERIFIED,
    )


@require_http_methods(["GET"])
def payment_receipt_verification(request, participant_token, payment_id):
    payment = _verified_receipt_payment(participant_token, payment_id)
    return render(request, "forms_builder/payment_receipt_verification.html", {
        "payment": payment,
        "submission": payment.submission,
        "event": payment.submission.event_form.event,
        "receipt_number": f"PAY-{payment.created_at.year}-{payment.pk:06d}",
    })


@require_http_methods(["GET"])
def payment_receipt_qr(request, participant_token, payment_id):
    payment = _verified_receipt_payment(participant_token, payment_id)
    path = reverse(
        "forms_builder:payment_receipt_verification",
        kwargs={
            "participant_token": participant_token,
            "payment_id": payment.pk,
        },
    )
    verification_url = (
        f"{settings.PUBLIC_BASE_URL.rstrip('/')}{path}"
        if settings.PUBLIC_BASE_URL
        else request.build_absolute_uri(path)
    )
    response = HttpResponse(
        generate_qr_png(verification_url),
        content_type="image/png",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response

@require_http_methods(["GET", "POST"])
def registration_status(request):
    submission = None
    lookup_error = ""
    reference_number = request.GET.get("reference", "").strip().upper()

    if request.method == "POST":
        reference_number = (
            request.POST.get("reference_number", "").strip().upper()
        )
        contact = request.POST.get("contact", "").strip()
        candidate = (
            FormSubmission.objects
            .select_related("event_form__event")
            .filter(
                reference_number=reference_number,
                is_complete=True,
                event_form__form_type__in=[
                    EventForm.FormType.REGISTRATION,
                    EventForm.FormType.EXHIBITOR,
                    EventForm.FormType.SPEAKER,
                ],
            )
            .first()
        )

        email_matches = (
            candidate
            and candidate.submitter_email
            and candidate.submitter_email.casefold() == contact.casefold()
        )
        normalized_contact = "".join(contact.split())
        phone_matches = (
            candidate
            and candidate.submitter_phone
            and "".join(candidate.submitter_phone.split())
            == normalized_contact
        )

        if candidate and (email_matches or phone_matches):
            submission = candidate
        else:
            lookup_error = (
                "We could not verify a registration with those details."
            )

    return render(
        request,
        "forms_builder/registration_status.html",
        {
            "submission": submission,
            "lookup_error": lookup_error,
            "reference_number": reference_number,
        },
    )


def get_badge_submission(participant_token):
    return get_object_or_404(
        FormSubmission.objects.select_related(
            "event_form",
            "event_form__event",
            "event_form__event__venue",
        ),
        participant_token=participant_token,
        is_complete=True,
        is_active=True,
        event_form__event__badge_enabled=True,
        event_form__form_type__in=[
            EventForm.FormType.REGISTRATION,
            EventForm.FormType.EXHIBITOR,
            EventForm.FormType.SPEAKER,
        ],
    )


@require_http_methods(["GET"])
def participant_badge(request, participant_token):
    submission = get_badge_submission(participant_token)

    return render(
        request,
        "forms_builder/participant_badge.html",
        {
            "submission": submission,
            "event": submission.event_form.event,
        },
    )


@require_http_methods(["GET"])
def participant_certificate(request, participant_token):
    submission = get_object_or_404(
        FormSubmission.objects.select_related(
            "event_form",
            "event_form__event",
            "event_form__event__venue",
            "check_in",
            "certificate_record",
        ),
        participant_token=participant_token,
        review_status=FormSubmission.ReviewStatus.APPROVED,
        is_complete=True,
        is_active=True,
        event_form__event__certificate_enabled=True,
        check_in__isnull=False,
        certificate_record__status=CertificateRecord.Status.AUTHORIZED,
        event_form__form_type__in=[
            EventForm.FormType.REGISTRATION,
            EventForm.FormType.EXHIBITOR,
            EventForm.FormType.SPEAKER,
        ],
    )

    return render(
        request,
        "forms_builder/participant_certificate.html",
        {
            "submission": submission,
            "event": submission.event_form.event,
            "event_display_name": (
                submission.event_form.event.title_en
                if request.LANGUAGE_CODE == "en"
                else submission.event_form.event.title_sw
            ),
            "certificate_number": certificate_number(submission),
            "certificate_recipient_name": certificate_display_recipient_name(submission),
            "institution_certificate": certificate_is_for_institution(submission),
            "weuutz_event_sentence_html": weuutz_event_sentence_html(
                submission.event_form.event
            ),
            "event_date_range": event_date_range(
                submission.event_form.event,
                language=request.LANGUAGE_CODE,
            ),
            "verification_url": certificate_verification_url(
                submission,
                request=request,
                language=request.LANGUAGE_CODE,
            ),
        },
    )


def get_certificate_submission(participant_token):
    return get_object_or_404(
        FormSubmission.objects.select_related(
            "event_form",
            "event_form__event",
            "event_form__event__venue",
            "check_in",
            "certificate_record",
        ),
        participant_token=participant_token,
        review_status=FormSubmission.ReviewStatus.APPROVED,
        is_complete=True,
        is_active=True,
        event_form__event__certificate_enabled=True,
        check_in__isnull=False,
        certificate_record__status=CertificateRecord.Status.AUTHORIZED,
        event_form__form_type__in=[
            EventForm.FormType.REGISTRATION,
            EventForm.FormType.EXHIBITOR,
            EventForm.FormType.SPEAKER,
        ],
    )


@require_http_methods(["GET"])
def participant_certificate_qr(request, participant_token):
    submission = get_certificate_submission(participant_token)
    verification_url = certificate_verification_url(
        submission,
        request=request,
        language=submission.language,
    )
    response = HttpResponse(
        generate_qr_png(
            verification_url,
            logo_path=certificate_qr_logo_path(submission.event_form.event),
        ),
        content_type="image/png",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def participant_certificate_pdf(request, participant_token):
    submission = get_certificate_submission(participant_token)
    verification_url = certificate_verification_url(
        submission,
        request=request,
        language=request.LANGUAGE_CODE,
    )
    response = HttpResponse(
        generate_certificate_pdf(
            submission,
            verification_url,
            language=request.LANGUAGE_CODE,
        ),
        content_type="application/pdf",
    )
    disposition = "inline" if request.GET.get("view") == "1" else "attachment"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{submission.reference_number}-certificate.pdf"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def certificate_verification(request, participant_token):
    submission = get_certificate_submission(participant_token)
    event = submission.event_form.event
    return render(
        request,
        "forms_builder/certificate_verification.html",
        {
            "submission": submission,
            "event": event,
            "certificate_number": certificate_number(submission),
            "certificate_recipient_name": certificate_display_recipient_name(submission),
            "institution_certificate": certificate_is_for_institution(submission),
            "event_date_range": event_date_range(
                event,
                language=request.LANGUAGE_CODE,
            ),
        },
    )


@require_http_methods(["GET"])
def participant_badge_qr(request, participant_token):
    submission = get_badge_submission(participant_token)
    check_in_url = participant_check_in_url(
        submission,
        request=request,
        language=submission.language,
    )
    response = HttpResponse(
        generate_qr_png(check_in_url),
        content_type="image/png",
    )

    if request.GET.get("download") == "1":
        response["Content-Disposition"] = (
            "attachment; "
            f'filename="{submission.reference_number}-badge-qr.png"'
        )

    response["X-Content-Type-Options"] = "nosniff"
    return response
