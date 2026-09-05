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
    FormSubmission,
    QuestionOption,
)


class StyledModelForm(forms.ModelForm):
    """Small shared base for the department-facing questionnaire builder."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "builder-input")


def _has_visual_logic(instance, relation_name):
    if not instance.pk:
        return False
    try:
        group = getattr(instance, relation_name)
    except DisplayLogicGroup.DoesNotExist:
        return False
    return (
        group.rules.filter(is_active=True).exists()
        or group.child_groups.filter(is_active=True).exists()
    )


class QuestionnaireForm(StyledModelForm):
    class Meta:
        model = EventForm
        fields = (
            "name_en", "name_sw", "form_type", "introduction_en",
            "introduction_sw", "success_message_en", "success_message_sw",
            "opens_at", "closes_at", "requires_login",
            "requires_participant_registration", "allow_multiple_submissions",
            "show_event_summary", "qr_record_enabled",
            "advanced_expression_mode",
        )
        widgets = {
            "introduction_en": forms.Textarea(attrs={"rows": 3}),
            "introduction_sw": forms.Textarea(attrs={"rows": 3}),
            "success_message_en": forms.Textarea(attrs={"rows": 2}),
            "success_message_sw": forms.Textarea(attrs={"rows": 2}),
            "opens_at": forms.DateTimeInput(attrs={"type": "datetime-local", "onchange": "this.blur()"}),
            "closes_at": forms.DateTimeInput(attrs={"type": "datetime-local", "onchange": "this.blur()"}),
        }

    def clean(self):
        cleaned = super().clean()
        opens_at, closes_at = cleaned.get("opens_at"), cleaned.get("closes_at")
        if opens_at and closes_at and closes_at <= opens_at:
            self.add_error("closes_at", "The closing time must be after the opening time.")
        return cleaned


class SubmissionManagementForm(StyledModelForm):
    """Safe event-workspace fields; submitted answers remain immutable here."""

    class Meta:
        model = FormSubmission
        fields = (
            "badge_name", "badge_organization", "badge_title",
            "submitter_email", "submitter_phone",
            "review_status", "review_notes",
        )
        widgets = {
            "review_notes": forms.Textarea(attrs={"rows": 4}),
        }


class QuestionnaireExcelImportForm(forms.Form):
    excel_file = forms.FileField(
        label="Completed Excel template",
        help_text="Upload the .xlsx template generated for this form.",
    )

    def clean_excel_file(self):
        uploaded = self.cleaned_data["excel_file"]
        if not uploaded.name.lower().endswith(".xlsx"):
            raise ValidationError("Upload an Excel .xlsx file.")
        if uploaded.size > 10 * 1024 * 1024:
            raise ValidationError("The Excel file cannot exceed 10 MB.")
        return uploaded


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
            "is_repeatable", "minimum_repeats", "maximum_repeats",
            "repeat_label_en", "repeat_label_sw",
            "visibility_expression",
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
        self.fields["minimum_repeats"].required = False
        self.fields["maximum_repeats"].required = False
        if not event_form.advanced_expression_mode:
            self.fields.pop("visibility_expression", None)
        else:
            self.fields["visibility_expression"].help_text = (
                "Expert mode: a safe expression controlling this section. "
                "It cannot be combined with visual visibility rules."
            )

    def clean(self):
        cleaned = super().clean()
        cleaned["minimum_repeats"] = cleaned.get("minimum_repeats") or 1
        cleaned["maximum_repeats"] = cleaned.get("maximum_repeats") or 10
        if cleaned.get("calculation_decimal_places") is None:
            cleaned["calculation_decimal_places"] = 2
        controlling = cleaned.get("condition_question")
        expression = cleaned.get("visibility_expression")
        if expression and (
            controlling
            or _has_visual_logic(self.instance, "display_logic")
        ):
            self.add_error(
                "visibility_expression",
                "Remove the visual visibility rules before using an advanced expression.",
            )
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
            "calculation_expression", "calculation_decimal_places",
            "validation_expression", "validation_message_en",
            "validation_message_sw",
            "visibility_expression", "required_expression",
            "choice_filter_question",
            "condition_question", "condition_value",
        )

    def __init__(self, *args, section, **kwargs):
        self.section = section
        super().__init__(*args, event_form=section.event_form, **kwargs)
        self.fields["condition_question"].widget = forms.HiddenInput()
        self.fields["condition_value"].widget = forms.HiddenInput()
        preceding = FormQuestion.objects.filter(
            section__event_form=section.event_form,
            is_active=True,
            question_type__in=self.CHOICE_TYPES,
        ).exclude(pk=self.instance.pk if self.instance.pk else None).order_by(
            "section__display_order", "display_order", "pk"
        )
        self.fields["choice_filter_question"].queryset = preceding
        self.fields["choice_filter_question"].required = False
        self.fields["choice_filter_question"].empty_label = "Do not filter choices"
        expression_fields = (
            "calculation_expression", "calculation_decimal_places",
            "validation_expression",
            "visibility_expression", "required_expression",
        )
        if not section.event_form.advanced_expression_mode:
            for field_name in expression_fields:
                self.fields.pop(field_name, None)
        else:
            self.fields["calculation_expression"].help_text = (
                "Expert mode: use q12 references, arithmetic, SUM(...), COUNT(...), and "
                "IF(condition, true_value, false_value)."
            )
            self.fields["validation_expression"].help_text = (
                "Expert mode: a safe expression that must evaluate to true. "
                "Python/JavaScript calls are blocked."
            )
            self.fields["visibility_expression"].help_text = (
                "Expert mode: controls whether this question is shown. "
                "It cannot be combined with visual visibility rules."
            )
            self.fields["required_expression"].help_text = (
                "Expert mode: controls when this question is required. "
                "It cannot be combined with visual Required when rules."
            )

    def clean(self):
        cleaned = super().clean()
        controlling = cleaned.get("condition_question")
        visibility_expression = cleaned.get("visibility_expression")
        required_expression = cleaned.get("required_expression")
        if visibility_expression and (
            controlling
            or _has_visual_logic(self.instance, "display_logic")
        ):
            self.add_error(
                "visibility_expression",
                "Remove the visual visibility rules before using an advanced expression.",
            )
        if required_expression and (
            _has_visual_logic(self.instance, "required_logic")
        ):
            self.add_error(
                "required_expression",
                "Remove the visual Required when rules before using an advanced expression.",
            )
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
        filter_question = cleaned.get("choice_filter_question")
        if filter_question:
            filter_position = (
                filter_question.section.display_order,
                filter_question.display_order,
                filter_question.pk,
            )
            own_position = (
                self.section.display_order,
                self.instance.display_order if self.instance.pk else 10**9,
                self.instance.pk or 10**9,
            )
            if filter_position >= own_position:
                self.add_error(
                    "choice_filter_question",
                    "Choice filtering can only use a question displayed earlier in the form.",
                )
        return cleaned


class OptionForm(StyledModelForm):
    class Meta:
        model = QuestionOption
        fields = ("label_en", "label_sw", "value", "filter_values")

    def __init__(self, *args, question=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.question = question or getattr(self.instance, "question", None)
        controller = getattr(self.question, "choice_filter_question", None)
        if controller:
            options = ", ".join(
                f"{option.value} ({option.label_en})"
                for option in controller.options.filter(is_active=True)
            )
            self.fields["filter_values"].help_text = (
                "Show this choice when the controlling answer matches one of these "
                f"stored values: {options}. Separate multiple values with commas."
            )
        else:
            self.fields["filter_values"].widget = forms.HiddenInput()

    def clean_filter_values(self):
        values = [
            value.strip()
            for value in (self.cleaned_data.get("filter_values") or "").split(",")
            if value.strip()
        ]
        controller = getattr(self.question, "choice_filter_question", None)
        if not controller and values:
            raise ValidationError("Choose a filter question before assigning option filter values.")
        if controller:
            valid = set(controller.options.filter(is_active=True).values_list("value", flat=True))
            unknown = [value for value in values if value not in valid]
            if unknown:
                raise ValidationError(
                    "Unknown controlling value(s): " + ", ".join(unknown)
                )
        return ",".join(dict.fromkeys(values))

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
            "source_question", "operator", "comparison_question",
            "choice_value", "comparison_value", "comparison_value_end",
            "comparison_values",
        )
        labels = {
            "comparison_question": "Or compare with another question",
            "comparison_value": "Value",
            "comparison_value_end": "Upper value",
        }

    def __init__(self, *args, group, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)
        questions = FormQuestion.objects.filter(
            section__event_form=group.event_form,
            is_active=True,
        ).prefetch_related("options").order_by(
            "section__display_order", "display_order", "pk"
        )
        if isinstance(group.target, FormQuestion) and not group.root_group.target_validation_question_id:
            questions = questions.exclude(pk=group.target.pk)
        self.fields["source_question"].queryset = questions
        self.fields["comparison_question"].queryset = questions
        self.fields["comparison_question"].required = False
        self.fields["comparison_question"].empty_label = "Use a fixed value"
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
        self.fields["operator"].widget.attrs["data-between-operator"] = DisplayLogicRule.Operator.BETWEEN

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("source_question")
        operator = cleaned.get("operator")
        comparison_question = cleaned.get("comparison_question")
        if not source or not operator:
            return cleaned
        if comparison_question and comparison_question.pk == source.pk:
            self.add_error(
                "comparison_question",
                "Choose a different question to compare against.",
            )
        has_choices = source.options.filter(is_active=True).exists()
        if operator in NO_VALUE_OPERATORS:
            cleaned["comparison_value"] = ""
            cleaned["comparison_value_end"] = ""
            cleaned["comparison_values"] = []
            cleaned["comparison_question"] = None
        elif comparison_question:
            if operator in MULTI_VALUE_OPERATORS or operator == DisplayLogicRule.Operator.BETWEEN:
                self.add_error(
                    "comparison_question",
                    "This operator requires fixed comparison values.",
                )
            cleaned["comparison_value"] = ""
            cleaned["comparison_value_end"] = ""
            cleaned["comparison_values"] = []
        elif operator in MULTI_VALUE_OPERATORS:
            if not cleaned.get("comparison_values"):
                self.add_error("comparison_values", "Select at least one answer.")
            cleaned["comparison_value"] = ""
            cleaned["comparison_value_end"] = ""
        elif operator == DisplayLogicRule.Operator.BETWEEN:
            if not cleaned.get("comparison_value"):
                self.add_error("comparison_value", "Enter the lower value.")
            if not cleaned.get("comparison_value_end"):
                self.add_error("comparison_value_end", "Enter the upper value.")
            cleaned["comparison_values"] = []
        elif has_choices:
            choice = cleaned.get("choice_value")
            if not choice:
                self.add_error("choice_value", "Select an answer.")
            cleaned["comparison_value"] = choice
            cleaned["comparison_value_end"] = ""
            cleaned["comparison_values"] = []
        elif not cleaned.get("comparison_value"):
            self.add_error("comparison_value", "Enter a comparison value.")
        if isinstance(self.group.target, FormSection):
            if source.section.display_order >= self.group.target.display_order:
                self.add_error(
                    "source_question",
                    "A section can only depend on a question in an earlier section.",
                )
        is_self_validation = (
            self.group.root_group.target_validation_question_id
            and source.pk == self.group.root_group.target_validation_question_id
        )
        if "source_question" not in self.errors and not is_self_validation:
            try:
                validate_dependency_graph(
                    self.group.event_form,
                    pending_target=self.group.target,
                    pending_source=source,
                    ignored_rule=self.instance,
                )
                if comparison_question and "comparison_question" not in self.errors:
                    validate_dependency_graph(
                        self.group.event_form,
                        pending_target=self.group.target,
                        pending_source=comparison_question,
                        ignored_rule=self.instance,
                    )
            except ValidationError as error:
                self.add_error("source_question", error)
        return cleaned
