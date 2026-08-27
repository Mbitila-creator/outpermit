import json

from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from .display_logic import (
    MULTI_VALUE_OPERATORS,
    NO_VALUE_OPERATORS,
    validate_dependency_graph,
)
from .models import (
    DisplayLogicGroup,
    DisplayLogicRule,
    EventForm,
    FormQuestion,
    FormSection,
    QuestionOption,
)


class StyledModelForm(forms.ModelForm):
    """Small shared base for the department-facing questionnaire builder."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "builder-input")


class QuestionnaireForm(StyledModelForm):
    class Meta:
        model = EventForm
        fields = (
            "name_en", "name_sw", "form_type", "introduction_en",
            "introduction_sw", "success_message_en", "success_message_sw",
            "opens_at", "closes_at", "requires_login",
            "requires_participant_registration", "allow_multiple_submissions",
            "show_event_summary",
        )
        widgets = {
            "introduction_en": forms.Textarea(attrs={"rows": 3}),
            "introduction_sw": forms.Textarea(attrs={"rows": 3}),
            "success_message_en": forms.Textarea(attrs={"rows": 2}),
            "success_message_sw": forms.Textarea(attrs={"rows": 2}),
            "opens_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "closes_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean(self):
        cleaned = super().clean()
        opens_at, closes_at = cleaned.get("opens_at"), cleaned.get("closes_at")
        if opens_at and closes_at and closes_at <= opens_at:
            self.add_error("closes_at", "The closing time must be after the opening time.")
        return cleaned


class ConditionalManagementForm(StyledModelForm):
    condition_value = forms.ChoiceField(
        required=False,
        label="Show when answer is",
        choices=[("", "Always show")],
    )

    def __init__(self, *args, event_form, **kwargs):
        self.event_form = event_form
        super().__init__(*args, **kwargs)
        questions = FormQuestion.objects.filter(
            section__event_form=event_form,
            is_active=True,
            options__is_active=True,
        ).select_related("section").order_by(
            "section__display_order", "display_order", "pk"
        ).distinct()
        if self.instance.pk and isinstance(self.instance, FormQuestion):
            questions = questions.exclude(pk=self.instance.pk)
        self.fields["condition_question"].queryset = questions
        self.fields["condition_question"].required = False
        self.fields["condition_question"].empty_label = "Always show"

        question_id = self.data.get("condition_question") if self.is_bound else getattr(
            self.instance, "condition_question_id", None
        )
        choices = [("", "Select an answer")]
        if question_id:
            choices += list(
                QuestionOption.objects.filter(
                    question_id=question_id, is_active=True
                ).order_by("display_order", "pk").values_list("value", "label_en")
            )
        self.fields["condition_value"].choices = choices
        option_map = {
            str(question.pk): list(question.options.filter(is_active=True).values(
                "value", "label_en"
            ))
            for question in questions.prefetch_related("options")
        }
        self.fields["condition_question"].widget.attrs["data-answer-options"] = json.dumps(option_map)

    def clean(self):
        cleaned = super().clean()
        question = cleaned.get("condition_question")
        value = cleaned.get("condition_value")
        if bool(question) != bool(value):
            raise ValidationError(
                "Choose both a controlling question and its answer, or leave both blank."
            )
        if question and not question.options.filter(value=value, is_active=True).exists():
            self.add_error("condition_value", "Choose an active answer from the controlling question.")
        return cleaned


class SectionForm(ConditionalManagementForm):
    class Meta:
        model = FormSection
        fields = (
            "title_en", "title_sw", "description_en", "description_sw",
            "condition_question", "condition_value",
        )
        widgets = {
            "description_en": forms.Textarea(attrs={"rows": 2}),
            "description_sw": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, event_form, **kwargs):
        super().__init__(*args, event_form=event_form, **kwargs)
        self.fields["condition_question"].widget = forms.HiddenInput()
        self.fields["condition_value"].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        controlling = cleaned.get("condition_question")
        if controlling and self.instance.pk:
            if controlling.section.display_order >= self.instance.display_order:
                self.add_error(
                    "condition_question",
                    "A section can only depend on a question in an earlier section.",
                )
        return cleaned

class QuestionForm(ConditionalManagementForm):
    CHOICE_TYPES = {
        FormQuestion.QuestionType.SINGLE_CHOICE,
        FormQuestion.QuestionType.MULTIPLE_CHOICE,
        FormQuestion.QuestionType.DROPDOWN,
    }

    class Meta:
        model = FormQuestion
        fields = (
            "label_en", "label_sw", "question_type", "help_text_en",
            "help_text_sw", "placeholder_en", "placeholder_sw",
            "is_required", "minimum_length", "maximum_length",
            "minimum_value", "maximum_value",
            "condition_question", "condition_value",
        )

    def __init__(self, *args, section, **kwargs):
        self.section = section
        super().__init__(*args, event_form=section.event_form, **kwargs)
        self.fields["condition_question"].widget = forms.HiddenInput()
        self.fields["condition_value"].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        controlling = cleaned.get("condition_question")
        if controlling:
            controlling_position = (
                controlling.section.display_order,
                controlling.display_order,
                controlling.pk,
            )
            own_position = (
                self.section.display_order,
                self.instance.display_order if self.instance.pk else 10**9,
                self.instance.pk or 10**9,
            )
            if controlling_position >= own_position:
                self.add_error(
                    "condition_question",
                    "Skip logic can only depend on a question displayed earlier in the form.",
                )
        return cleaned


class OptionForm(StyledModelForm):
    class Meta:
        model = QuestionOption
        fields = ("label_en", "label_sw", "value")

    def clean_value(self):
        value = (self.cleaned_data.get("value") or "").strip()
        if not value:
            value = slugify(self.cleaned_data.get("label_en") or "").replace("-", "_").upper()
        if not value:
            raise ValidationError("Enter a stored value or an English option label.")
        return value


class LogicGroupForm(StyledModelForm):
    class Meta:
        model = DisplayLogicGroup
        fields = ("match_type",)


class LogicRuleForm(StyledModelForm):
    choice_value = forms.ChoiceField(required=False, label="Answer")
    comparison_values = forms.MultipleChoiceField(
        required=False,
        label="Answers",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = DisplayLogicRule
        fields = (
            "source_question", "operator", "choice_value", "comparison_value",
            "comparison_values",
        )
        labels = {"comparison_value": "Value"}

    def __init__(self, *args, group, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)
        questions = FormQuestion.objects.filter(
            section__event_form=group.event_form,
            is_active=True,
        ).prefetch_related("options").order_by(
            "section__display_order", "display_order", "pk"
        )
        if group.target_question_id:
            questions = questions.exclude(pk=group.target_question_id)
        self.fields["source_question"].queryset = questions
        source_id = self.data.get("source_question") if self.is_bound else (
            self.instance.source_question_id if self.instance.pk else None
        )
        source = next((item for item in questions if str(item.pk) == str(source_id)), None)
        choices = []
        if source:
            choices = [
                (option.value, option.label_en)
                for option in source.options.all() if option.is_active
            ]
        self.fields["choice_value"].choices = [("", "Select an answer")] + choices
        self.fields["comparison_values"].choices = choices
        if self.instance.pk:
            self.fields["choice_value"].initial = self.instance.comparison_value
        option_map = {
            str(question.pk): [
                {"value": option.value, "label": option.label_en}
                for option in question.options.all() if option.is_active
            ]
            for question in questions
        }
        self.fields["source_question"].widget.attrs["data-answer-options"] = json.dumps(option_map)
        self.fields["operator"].widget.attrs["data-no-value-operators"] = json.dumps(list(NO_VALUE_OPERATORS))
        self.fields["operator"].widget.attrs["data-multi-value-operators"] = json.dumps(list(MULTI_VALUE_OPERATORS))

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("source_question")
        operator = cleaned.get("operator")
        if not source or not operator:
            return cleaned
        has_choices = source.options.filter(is_active=True).exists()
        if operator in NO_VALUE_OPERATORS:
            cleaned["comparison_value"] = ""
            cleaned["comparison_values"] = []
        elif operator in MULTI_VALUE_OPERATORS:
            if not cleaned.get("comparison_values"):
                self.add_error("comparison_values", "Select at least one answer.")
            cleaned["comparison_value"] = ""
        elif has_choices:
            choice = cleaned.get("choice_value")
            if not choice:
                self.add_error("choice_value", "Select an answer.")
            cleaned["comparison_value"] = choice
            cleaned["comparison_values"] = []
        elif not cleaned.get("comparison_value"):
            self.add_error("comparison_value", "Enter a comparison value.")
        if self.group.target_section_id:
            if source.section.display_order >= self.group.target_section.display_order:
                self.add_error(
                    "source_question",
                    "A section can only depend on a question in an earlier section.",
                )
        if "source_question" not in self.errors:
            try:
                validate_dependency_graph(
                    self.group.event_form,
                    pending_target=self.group.target,
                    pending_source=source,
                    ignored_rule=self.instance,
                )
            except ValidationError as error:
                self.add_error("source_question", error)
        return cleaned
