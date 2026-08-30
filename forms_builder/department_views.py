from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max, Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils import timezone

from events.access import events_visible_to
from events.department_views import can_manage_department_event

from .display_logic import create_group_from_legacy
from .management_forms import (
    LogicGroupForm,
    LogicRuleForm,
    OptionForm,
    QuestionnaireForm,
    QuestionForm,
    SectionForm,
    SubmissionManagementForm,
)
from .models import (
    DisplayLogicGroup,
    DisplayLogicRule,
    EventForm,
    FormQuestion,
    FormSection,
    FormSubmission,
    QuestionOption,
)
from .services import certificate_qr_logo_path, generate_qr_png


def _event(request, event_slug):
    event = get_object_or_404(events_visible_to(request.user), slug=event_slug)
    if not can_manage_department_event(request.user):
        raise PermissionDenied
    return event


def _form(event, form_id):
    return get_object_or_404(EventForm, pk=form_id, event=event, is_active=True)


def _audit_save(instance, user):
    if not instance.created_by_id:
        instance.created_by = user
    instance.updated_by = user
    instance.full_clean()
    instance.save()
    return instance


@login_required
def questionnaire_list(request, event_slug):
    event = _event(request, event_slug)
    forms = event.forms.filter(is_active=True).annotate(
        section_count=Count("sections", filter=Q(sections__is_active=True), distinct=True),
        response_count=Count("submissions", distinct=True),
    ).order_by("form_type", "name_en")
    return render(request, "forms_builder/management/questionnaire_list.html", {
        "event": event, "questionnaires": forms,
    })


@login_required
def questionnaire_create(request, event_slug):
    event = _event(request, event_slug)
    form = QuestionnaireForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        questionnaire = form.save(commit=False)
        questionnaire.event = event
        questionnaire.is_published = False
        _audit_save(questionnaire, request.user)
        messages.success(request, "Questionnaire created as a draft.")
        return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)
    return render(request, "forms_builder/management/edit.html", {
        "event": event, "form": form, "page_title": "Create questionnaire",
        "cancel_url": "forms_builder:questionnaire_list",
        "page_intro": (
            "First save the questionnaire settings. You will then go directly "
            "to the builder to add sections, questions, choices and display logic."
        ),
        "submit_label": "Create and open builder",
    })


@login_required
def questionnaire_edit(request, event_slug, form_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    form = QuestionnaireForm(request.POST or None, instance=questionnaire)
    if request.method == "POST" and form.is_valid():
        _audit_save(form.save(commit=False), request.user)
        messages.success(request, "Questionnaire settings updated.")
        return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)
    return render(request, "forms_builder/management/edit.html", {
        "event": event, "questionnaire": questionnaire, "form": form,
        "page_title": "Questionnaire settings",
    })


@login_required
@transaction.atomic
def questionnaire_delete(request, event_slug, form_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    if request.method == "POST":
        questionnaire.is_active = False
        questionnaire.is_published = False
        questionnaire.updated_by = request.user
        questionnaire.save(update_fields=[
            "is_active", "is_published", "updated_by", "updated_at",
        ])
        messages.success(
            request,
            f'Questionnaire "{questionnaire.name_en}" was removed from active lists.',
        )
        return redirect("forms_builder:questionnaire_list", event.slug)
    return render(request, "forms_builder/management/questionnaire_delete.html", {
        "event": event,
        "questionnaire": questionnaire,
        "response_count": questionnaire.submissions.count(),
    })


@login_required
def questionnaire_builder(request, event_slug, form_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    sections = questionnaire.sections.filter(is_active=True).prefetch_related(
        "display_logic__rules__source_question__options",
        "questions__options",
        "questions__condition_question__options",
        "questions__display_logic__rules__source_question__options",
        "questions__required_logic__rules__source_question__options",
        "questions__validation_logic__rules__source_question__options",
    ).order_by("display_order", "pk")
    return render(request, "forms_builder/management/builder.html", {
        "event": event, "questionnaire": questionnaire, "sections": sections,
        "has_responses": questionnaire.submissions.exists(),
    })


@login_required
def questionnaire_print(request, event_slug, form_id):
    """Render every active question in an A4-friendly administrator print view."""
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    sections = questionnaire.sections.filter(is_active=True).prefetch_related(
        "questions__options",
        "questions__display_logic",
        "questions__required_logic",
        "questions__validation_logic",
    ).order_by("display_order", "pk")
    return render(request, "forms_builder/management/questionnaire_print.html", {
        "event": event,
        "questionnaire": questionnaire,
        "sections": sections,
    })


@login_required
def event_submission_list(request, event_slug):
    event = _event(request, event_slug)
    forms = event.forms.filter(is_active=True).order_by("form_type", "name_en")
    submissions = FormSubmission.objects.filter(
        event_form__event=event,
        is_active=True,
    ).select_related("event_form", "submitted_by").order_by("-created_at")

    selected_form = request.GET.get("form", "").strip()
    if selected_form.isdigit():
        submissions = submissions.filter(event_form_id=selected_form)
    status = request.GET.get("status", "").strip()
    if status in FormSubmission.ReviewStatus.values:
        submissions = submissions.filter(review_status=status)
    completion = request.GET.get("completion", "").strip()
    if completion in {"complete", "draft"}:
        submissions = submissions.filter(is_complete=completion == "complete")
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))
    if date_from:
        submissions = submissions.filter(created_at__date__gte=date_from)
    if date_to:
        submissions = submissions.filter(created_at__date__lte=date_to)
    query = request.GET.get("q", "").strip()
    if query:
        submissions = submissions.filter(Q(
            reference_number__icontains=query,
        ) | Q(
            submitter_email__icontains=query,
        ) | Q(
            submitter_phone__icontains=query,
        ) | Q(
            badge_name__icontains=query,
        ) | Q(
            badge_organization__icontains=query,
        ) | Q(
            answers__text_value__icontains=query,
        ) | Q(
            answers__selected_options__label_en__icontains=query,
        ) | Q(
            answers__selected_options__label_sw__icontains=query,
        )).distinct()

    page = Paginator(submissions, 50).get_page(request.GET.get("page"))
    preserved_query = request.GET.copy()
    preserved_query.pop("page", None)
    return render(request, "forms_builder/management/submission_list.html", {
        "event": event,
        "forms": forms,
        "page": page,
        "selected_form": selected_form,
        "selected_status": status,
        "selected_completion": completion,
        "query": query,
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "preserved_query": preserved_query.urlencode(),
    })


@login_required
def event_submission_detail(request, event_slug, submission_id):
    event = _event(request, event_slug)
    submission = get_object_or_404(
        FormSubmission.objects.select_related(
            "event_form", "submitted_by", "reviewed_by"
        ).prefetch_related("answers__question__section", "answers__selected_options"),
        pk=submission_id,
        event_form__event=event,
        is_active=True,
    )
    from .views import localized_answer_value
    answers = [{
        "answer": answer,
        "value": localized_answer_value(answer, request.LANGUAGE_CODE),
    } for answer in submission.answers.all().order_by(
        "question__section__display_order", "question__display_order", "repeat_index"
    )]
    return render(request, "forms_builder/management/submission_detail.html", {
        "event": event,
        "submission": submission,
        "answers": answers,
    })


@login_required
@transaction.atomic
def event_submission_edit(request, event_slug, submission_id):
    event = _event(request, event_slug)
    submission = get_object_or_404(
        FormSubmission,
        pk=submission_id,
        event_form__event=event,
        is_active=True,
    )
    previous_status = submission.review_status
    form = SubmissionManagementForm(request.POST or None, instance=submission)
    if request.method == "POST" and form.is_valid():
        submission = form.save(commit=False)
        if submission.review_status != previous_status:
            if submission.review_status == FormSubmission.ReviewStatus.PENDING:
                submission.reviewed_by = None
                submission.reviewed_at = None
            else:
                submission.reviewed_by = request.user
                submission.reviewed_at = timezone.now()
        submission.updated_by = request.user
        submission.full_clean()
        submission.save()
        messages.success(request, "Submission details were updated.")
        return redirect(
            "forms_builder:event_submission_detail", event.slug, submission.pk
        )
    return render(request, "forms_builder/management/submission_edit.html", {
        "event": event,
        "submission": submission,
        "form": form,
    })


@login_required
@transaction.atomic
def event_submission_delete(request, event_slug, submission_id):
    event = _event(request, event_slug)
    submission = get_object_or_404(
        FormSubmission,
        pk=submission_id,
        event_form__event=event,
        is_active=True,
    )
    if request.method == "POST":
        submission.is_active = False
        submission.updated_by = request.user
        submission.save(update_fields=["is_active", "updated_by", "updated_at"])
        messages.success(
            request,
            f"Submission {submission.reference_number} was removed from active lists.",
        )
        return redirect("forms_builder:event_submission_list", event.slug)
    return render(request, "forms_builder/management/submission_delete.html", {
        "event": event,
        "submission": submission,
    })


@login_required
def individual_qr_record_list(request, event_slug):
    event = _event(request, event_slug)
    forms = event.forms.filter(
        is_active=True,
        qr_record_enabled=True,
    ).order_by("form_type", "name_en")
    selected_form_id = request.GET.get("form", "").strip()
    selected_form = forms.filter(pk=selected_form_id).first() if selected_form_id.isdigit() else forms.first()
    submissions = FormSubmission.objects.none()
    query = request.GET.get("q", "").strip()
    if selected_form:
        submissions = selected_form.submissions.filter(
            is_active=True,
            is_complete=True,
        ).order_by("badge_name", "reference_number")
        if query:
            submissions = submissions.filter(Q(
                reference_number__icontains=query,
            ) | Q(
                badge_name__icontains=query,
            ) | Q(
                badge_organization__icontains=query,
            ) | Q(
                answers__text_value__icontains=query,
            )).distinct()
    page = Paginator(submissions, 50).get_page(request.GET.get("page"))
    return render(request, "forms_builder/management/individual_qr_record_list.html", {
        "event": event,
        "forms": forms,
        "selected_form": selected_form,
        "page": page,
        "query": query,
    })


@login_required
def individual_qr_record_print(request, event_slug, form_id):
    event = _event(request, event_slug)
    questionnaire = get_object_or_404(
        EventForm,
        pk=form_id,
        event=event,
        is_active=True,
        qr_record_enabled=True,
    )
    submissions = questionnaire.submissions.filter(
        is_active=True,
        is_complete=True,
    ).order_by("badge_name", "reference_number")
    return render(request, "forms_builder/management/individual_qr_record_print.html", {
        "event": event,
        "questionnaire": questionnaire,
        "submissions": submissions,
    })


def individual_qr_record(request, participant_token):
    submission = get_object_or_404(
        FormSubmission.objects.select_related(
            "event_form", "event_form__event", "event_form__event__owning_department"
        ).prefetch_related("answers__question__section", "answers__selected_options"),
        participant_token=participant_token,
        is_active=True,
        is_complete=True,
        event_form__is_active=True,
        event_form__qr_record_enabled=True,
        event_form__event__is_active=True,
    )
    from .views import localized_answer_value
    answers = [{
        "answer": answer,
        "value": localized_answer_value(answer, request.LANGUAGE_CODE),
    } for answer in submission.answers.all().order_by(
        "question__section__display_order", "question__display_order", "repeat_index"
    )]
    return render(request, "forms_builder/individual_qr_record.html", {
        "submission": submission,
        "event": submission.event_form.event,
        "answers": answers,
    })


def individual_qr_record_qr(request, participant_token):
    submission = get_object_or_404(
        FormSubmission.objects.select_related("event_form__event"),
        participant_token=participant_token,
        is_active=True,
        is_complete=True,
        event_form__is_active=True,
        event_form__qr_record_enabled=True,
        event_form__event__is_active=True,
    )
    path = reverse(
        "forms_builder:individual_qr_record",
        kwargs={"participant_token": submission.participant_token},
    )
    url = f"{settings.PUBLIC_BASE_URL}{path}" if settings.PUBLIC_BASE_URL else request.build_absolute_uri(path)
    response = HttpResponse(
        generate_qr_png(url, logo_path=certificate_qr_logo_path(submission.event_form.event)),
        content_type="image/png",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _logic_target(questionnaire, target_type, target_id):
    if target_type == "section":
        return get_object_or_404(
            FormSection, pk=target_id, event_form=questionnaire, is_active=True
        )
    if target_type in {"question", "required", "validation"}:
        return get_object_or_404(
            FormQuestion,
            pk=target_id,
            section__event_form=questionnaire,
            is_active=True,
        )
    raise PermissionDenied


def _selected_logic_group(root_group, group_id):
    if not group_id:
        return root_group
    group = get_object_or_404(
        DisplayLogicGroup,
        pk=group_id,
        event_form=root_group.event_form,
        is_active=True,
    )
    if group.root_group.pk != root_group.pk:
        raise PermissionDenied
    return group


def _logic_editor_url(event, questionnaire, target_type, target, group=None):
    url = reverse(
        "forms_builder:logic_editor",
        args=(event.slug, questionnaire.pk, target_type, target.pk),
    )
    if group and group.parent_group_id:
        return f"{url}?group={group.pk}"
    return url


def _root_logic_group(target, target_type, user):
    return create_group_from_legacy(
        target,
        user,
        purpose=target_type if target_type in {"required", "validation"} else "visibility",
    )


@login_required
@transaction.atomic
def logic_editor(request, event_slug, form_id, target_type, target_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    target = _logic_target(questionnaire, target_type, target_id)
    root_group = _root_logic_group(target, target_type, request.user)
    group = _selected_logic_group(root_group, request.GET.get("group"))
    form = LogicGroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        logic_group = form.save(commit=False)
        logic_group.updated_by = request.user
        logic_group.full_clean()
        logic_group.save()
        messages.success(request, "AND/OR matching was updated.")
        return redirect(_logic_editor_url(
            event, questionnaire, target_type, target, group
        ))
    return render(request, "forms_builder/management/logic_editor.html", {
        "event": event,
        "questionnaire": questionnaire,
        "target": target,
        "target_type": target_type,
        "logic_group": group,
        "root_group": root_group,
        "parent_group": group.parent_group,
        "is_required_logic": target_type == "required",
        "is_validation_logic": target_type == "validation",
        "form": form,
        "rules": group.rules.filter(is_active=True).select_related(
            "source_question", "comparison_question"
        ).prefetch_related("source_question__options"),
        "child_groups": group.child_groups.filter(is_active=True),
    })


@login_required
def logic_rule_edit(
    request, event_slug, form_id, target_type, target_id, rule_id=None
):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    target = _logic_target(questionnaire, target_type, target_id)
    root_group = _root_logic_group(target, target_type, request.user)
    if rule_id:
        rule = get_object_or_404(
            DisplayLogicRule,
            pk=rule_id,
            group__event_form=questionnaire,
            is_active=True,
        )
        group = _selected_logic_group(root_group, rule.group_id)
    else:
        group = _selected_logic_group(root_group, request.GET.get("group"))
        rule = DisplayLogicRule(group=group)
    form = LogicRuleForm(request.POST or None, instance=rule, group=group)
    if request.method == "POST" and form.is_valid():
        rule = form.save(commit=False)
        rule.group = group
        if not rule.pk:
            rule.display_order = (group.rules.aggregate(
                value=Max("display_order")
            )["value"] or 0) + 1
        _audit_save(rule, request.user)
        messages.success(request, "Display rule saved.")
        return redirect(_logic_editor_url(
            event, questionnaire, target_type, target, group
        ))
    return render(request, "forms_builder/management/logic_rule_edit.html", {
        "event": event,
        "questionnaire": questionnaire,
        "target": target,
        "target_type": target_type,
        "rule": rule,
        "form": form,
        "logic_group": group,
    })


@login_required
def logic_rule_archive(request, event_slug, form_id, target_type, target_id, rule_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    target = _logic_target(questionnaire, target_type, target_id)
    root_group = _root_logic_group(target, target_type, request.user)
    if request.method != "POST":
        raise PermissionDenied
    rule = get_object_or_404(
        DisplayLogicRule,
        pk=rule_id,
        group__event_form=questionnaire,
        is_active=True,
    )
    group = _selected_logic_group(root_group, rule.group_id)
    rule.is_active = False
    rule.updated_by = request.user
    rule.save(update_fields=["is_active", "updated_by", "updated_at"])
    messages.success(request, "Display rule removed.")
    return redirect(_logic_editor_url(
        event, questionnaire, target_type, target, group
    ))


@login_required
@transaction.atomic
def logic_group_create(request, event_slug, form_id, target_type, target_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    target = _logic_target(questionnaire, target_type, target_id)
    root_group = _root_logic_group(target, target_type, request.user)
    parent = _selected_logic_group(root_group, request.GET.get("parent"))
    nested = DisplayLogicGroup(
        event_form=questionnaire,
        parent_group=parent,
        created_by=request.user,
        updated_by=request.user,
    )
    form = LogicGroupForm(request.POST or None, instance=nested)
    if request.method == "POST" and form.is_valid():
        nested = form.save(commit=False)
        nested.event_form = questionnaire
        nested.parent_group = parent
        _audit_save(nested, request.user)
        messages.success(request, "Nested condition group added.")
        return redirect(_logic_editor_url(
            event, questionnaire, target_type, target, nested
        ))
    return render(request, "forms_builder/management/logic_group_edit.html", {
        "event": event,
        "questionnaire": questionnaire,
        "target": target,
        "target_type": target_type,
        "parent_group": parent,
        "form": form,
    })


@login_required
def logic_group_archive(request, event_slug, form_id, target_type, target_id, group_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    target = _logic_target(questionnaire, target_type, target_id)
    root_group = _root_logic_group(target, target_type, request.user)
    group = _selected_logic_group(root_group, group_id)
    if request.method != "POST" or not group.parent_group_id:
        raise PermissionDenied
    parent = group.parent_group
    group.is_active = False
    group.updated_by = request.user
    group.save(update_fields=["is_active", "updated_by", "updated_at"])
    messages.success(request, "Nested condition group removed.")
    return redirect(_logic_editor_url(
        event, questionnaire, target_type, target, parent
    ))


@login_required
def questionnaire_publish(request, event_slug, form_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    if request.method != "POST":
        raise PermissionDenied
    if not questionnaire.is_published:
        active_sections = questionnaire.sections.filter(is_active=True)
        if not active_sections.exists() or not FormQuestion.objects.filter(
            section__in=active_sections, is_active=True
        ).exists():
            messages.error(request, "Add at least one active section and question before publishing.")
            return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)
    questionnaire.is_published = not questionnaire.is_published
    questionnaire.updated_by = request.user
    questionnaire.save(update_fields=["is_published", "updated_by", "updated_at"])
    messages.success(request, "Questionnaire publication status updated.")
    return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)


@login_required
def section_edit(request, event_slug, form_id, section_id=None):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    section = get_object_or_404(
        FormSection, pk=section_id, event_form=questionnaire, is_active=True
    ) if section_id else FormSection(event_form=questionnaire)
    form = SectionForm(request.POST or None, instance=section, event_form=questionnaire)
    if request.method == "POST" and form.is_valid():
        section = form.save(commit=False)
        section.event_form = questionnaire
        if not section.pk:
            section.display_order = (questionnaire.sections.aggregate(
                value=Max("display_order")
            )["value"] or 0) + 1
        _audit_save(section, request.user)
        messages.success(request, "Section saved.")
        return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)
    return render(request, "forms_builder/management/edit.html", {
        "event": event, "questionnaire": questionnaire, "form": form,
        "page_title": "Edit section" if section_id else "Add section",
    })


@login_required
def question_edit(request, event_slug, form_id, section_id, question_id=None):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    section = get_object_or_404(FormSection, pk=section_id, event_form=questionnaire, is_active=True)
    question = get_object_or_404(
        FormQuestion, pk=question_id, section=section, is_active=True
    ) if question_id else FormQuestion(section=section)
    form = QuestionForm(request.POST or None, instance=question, section=section)
    if request.method == "POST" and form.is_valid():
        question = form.save(commit=False)
        question.section = section
        if not question.pk:
            question.display_order = (section.questions.aggregate(
                value=Max("display_order")
            )["value"] or 0) + 1
        _audit_save(question, request.user)
        messages.success(request, "Question saved.")
        return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)
    return render(request, "forms_builder/management/edit.html", {
        "event": event, "questionnaire": questionnaire, "section": section,
        "form": form, "page_title": "Edit question" if question_id else "Add question",
        "condition_source_url": True,
    })


@login_required
def option_edit(request, event_slug, form_id, question_id, option_id=None):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    question = get_object_or_404(
        FormQuestion, pk=question_id, section__event_form=questionnaire, is_active=True
    )
    if not question.supports_options:
        messages.error(request, "This question type does not use answer choices.")
        return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)
    option = get_object_or_404(
        QuestionOption, pk=option_id, question=question, is_active=True
    ) if option_id else QuestionOption(question=question)
    form = OptionForm(request.POST or None, instance=option, question=question)
    if request.method == "POST" and form.is_valid():
        option = form.save(commit=False)
        option.question = question
        if not option.pk:
            option.display_order = (question.options.aggregate(
                value=Max("display_order")
            )["value"] or 0) + 1
        _audit_save(option, request.user)
        messages.success(request, "Answer choice saved.")
        return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)
    return render(request, "forms_builder/management/edit.html", {
        "event": event, "questionnaire": questionnaire, "question": question,
        "form": form, "page_title": "Edit answer choice" if option_id else "Add answer choice",
    })


@login_required
@transaction.atomic
def component_action(request, event_slug, form_id, component, component_id, action):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    if request.method != "POST":
        raise PermissionDenied
    model, parent_filter = {
        "section": (FormSection, {"event_form": questionnaire}),
        "question": (FormQuestion, {"section__event_form": questionnaire}),
        "option": (QuestionOption, {"question__section__event_form": questionnaire}),
    }.get(component, (None, None))
    if not model:
        raise PermissionDenied
    item = get_object_or_404(model, pk=component_id, is_active=True, **parent_filter)
    if action == "archive":
        if component == "question":
            FormQuestion.objects.filter(condition_question=item).update(
                condition_question=None, condition_value=""
            )
            FormSection.objects.filter(condition_question=item).update(
                condition_question=None, condition_value=""
            )
            DisplayLogicRule.objects.filter(source_question=item).update(
                is_active=False,
                updated_by=request.user,
            )
        elif component == "option":
            FormQuestion.objects.filter(
                condition_question=item.question,
                condition_value=item.value,
            ).update(condition_question=None, condition_value="")
            FormSection.objects.filter(
                condition_question=item.question,
                condition_value=item.value,
            ).update(condition_question=None, condition_value="")
            for rule in DisplayLogicRule.objects.filter(
                source_question=item.question,
                is_active=True,
            ):
                if rule.operator in {
                    DisplayLogicRule.Operator.ANY_OF,
                    DisplayLogicRule.Operator.NONE_OF,
                } and item.value in rule.comparison_values:
                    rule.comparison_values = [
                        value for value in rule.comparison_values
                        if value != item.value
                    ]
                    if not rule.comparison_values:
                        rule.is_active = False
                    rule.updated_by = request.user
                    rule.save(update_fields=[
                        "comparison_values", "is_active", "updated_by", "updated_at"
                    ])
                elif rule.comparison_value == item.value:
                    rule.is_active = False
                    rule.updated_by = request.user
                    rule.save(update_fields=["is_active", "updated_by", "updated_at"])
        item.is_active = False
        item.updated_by = request.user
        item.save(update_fields=["is_active", "updated_by", "updated_at"])
        messages.success(request, "Item archived. Existing responses were preserved.")
    elif action in {"up", "down"}:
        siblings = model.objects.filter(is_active=True, **parent_filter)
        if component == "question":
            siblings = siblings.filter(section=item.section)
        elif component == "option":
            siblings = siblings.filter(question=item.question)
        ordered = list(siblings.order_by("display_order", "pk"))
        index = ordered.index(item)
        swap_index = index - 1 if action == "up" else index + 1
        if 0 <= swap_index < len(ordered):
            other = ordered[swap_index]
            item.display_order, other.display_order = other.display_order, item.display_order
            if item.display_order == other.display_order:
                item.display_order, other.display_order = swap_index + 1, index + 1
            item.updated_by = other.updated_by = request.user
            item.save(update_fields=["display_order", "updated_by", "updated_at"])
            other.save(update_fields=["display_order", "updated_by", "updated_at"])
    return redirect("forms_builder:questionnaire_builder", event.slug, questionnaire.pk)
