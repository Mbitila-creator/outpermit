from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render

from events.access import events_visible_to
from events.department_views import can_manage_department_event

from .management_forms import OptionForm, QuestionnaireForm, QuestionForm, SectionForm
from .models import EventForm, FormQuestion, FormSection, QuestionOption


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
def questionnaire_builder(request, event_slug, form_id):
    event = _event(request, event_slug)
    questionnaire = _form(event, form_id)
    sections = questionnaire.sections.filter(is_active=True).prefetch_related(
        "questions__options", "questions__condition_question__options"
    ).order_by("display_order", "pk")
    return render(request, "forms_builder/management/builder.html", {
        "event": event, "questionnaire": questionnaire, "sections": sections,
        "has_responses": questionnaire.submissions.exists(),
    })


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
    form = OptionForm(request.POST or None, instance=option)
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
        elif component == "option":
            FormQuestion.objects.filter(
                condition_question=item.question,
                condition_value=item.value,
            ).update(condition_question=None, condition_value="")
            FormSection.objects.filter(
                condition_question=item.question,
                condition_value=item.value,
            ).update(condition_question=None, condition_value="")
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
