from types import SimpleNamespace
from io import BytesIO
from io import StringIO
from tempfile import NamedTemporaryFile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.models import Country, Region
from events.models import Event, EventCategory
from .models import (
    DisplayLogicGroup,
    DisplayLogicRule,
    EventForm,
    FormAnswer,
    FormQuestion,
    FormSection,
    FormSubmission,
    QuestionOption,
)
from .display_logic import (
    group_spec, question_is_required, question_passes_visual_validation,
    rule_matches_values, target_is_visible,
)
from .management_forms import LogicRuleForm
from .admin import EventFormAdmin, FormSubmissionAdmin

from .services import (
    certificate_is_for_institution,
    certificate_display_recipient_name,
    certificate_recipient_name,
    generate_qr_png,
    weuutz_event_sentence,
    weuutz_event_sentence_html,
)
from .views import registration_identity_conflicts
from .expressions import ExpressionError, evaluate_expression, question_reference_ids
from .views import choice_option_is_available, expression_answer_values


class QuestionnaireAnalysisReportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="analysis-admin",
            email="analysis@example.test",
            password="safe-password",
        )
        category = EventCategory.objects.create(
            code="ANALYSIS_EVENT",
            name_en="Analysis event",
            name_sw="Tukio la uchambuzi",
        )
        now = timezone.now()
        event = Event.objects.create(
            category=category,
            code="ANALYSIS-2026",
            title_en="Questionnaire analysis",
            title_sw="Uchambuzi wa dodoso",
            starts_at=now,
            ends_at=now + timedelta(days=1),
        )
        self.form = EventForm.objects.create(
            event=event,
            name_en="Visitor evaluation",
            name_sw="Tathmini ya mgeni",
            form_type=EventForm.FormType.EVALUATION,
        )
        section = FormSection.objects.create(
            event_form=self.form,
            title_en="Feedback",
            title_sw="Maoni",
        )
        self.choice_question = FormQuestion.objects.create(
            section=section,
            label_en="How was the event?",
            label_sw="Tukio lilikuwaje?",
            question_type=FormQuestion.QuestionType.SINGLE_CHOICE,
            display_order=1,
        )
        self.good_option = QuestionOption.objects.create(
            question=self.choice_question,
            value="GOOD",
            label_en="Good",
            label_sw="Nzuri",
            display_order=1,
        )
        self.poor_option = QuestionOption.objects.create(
            question=self.choice_question,
            value="POOR",
            label_en="Poor",
            label_sw="Dhaifu",
            display_order=2,
        )
        self.score_question = FormQuestion.objects.create(
            section=section,
            label_en="Score",
            label_sw="Alama",
            question_type=FormQuestion.QuestionType.NUMBER,
            display_order=2,
        )
        self.comment_question = FormQuestion.objects.create(
            section=section,
            label_en="Comment",
            label_sw="Maoni",
            question_type=FormQuestion.QuestionType.LONG_TEXT,
            display_order=3,
        )

        for index, (option, score, comment) in enumerate((
            (self.good_option, Decimal("4"), "Helpful"),
            (self.good_option, Decimal("2"), "Helpful"),
            (self.poor_option, None, "Needs more time"),
        )):
            submission = FormSubmission.objects.create(
                event_form=self.form,
                is_complete=True,
                is_active=True,
                submitter_email=f"visitor-{index}@example.test",
            )
            choice_answer = FormAnswer.objects.create(
                submission=submission,
                question=self.choice_question,
            )
            choice_answer.selected_options.add(option)
            if score is not None:
                FormAnswer.objects.create(
                    submission=submission,
                    question=self.score_question,
                    number_value=score,
                )
            FormAnswer.objects.create(
                submission=submission,
                question=self.comment_question,
                text_value=comment,
            )

    def test_report_shows_histogram_and_table_for_each_question(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("forms_builder:evaluation_reports"),
            {"form": self.form.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["question_statistics"]), 3)
        choice_analysis, score_analysis, comment_analysis = response.context[
            "question_statistics"
        ]
        self.assertEqual(choice_analysis["answered_count"], 3)
        self.assertEqual(
            [(row["label"], row["count"]) for row in choice_analysis["rows"]],
            [("Good", 2), ("Poor", 1)],
        )
        self.assertEqual(score_analysis["answered_count"], 2)
        self.assertEqual(score_analysis["unanswered_count"], 1)
        self.assertEqual(score_analysis["numeric"], {
            "average": "3",
            "minimum": "2",
            "maximum": "4",
        })
        self.assertEqual(comment_analysis["rows"][0]["label"], "Helpful")
        self.assertEqual(comment_analysis["rows"][0]["count"], 2)
        self.assertContains(response, "Analysis by question")
        self.assertContains(response, "Response histogram", count=3)
        self.assertContains(response, "Individual submitted responses")
        self.assertContains(response, "histogram-bar color-1")
        self.assertContains(response, 'class="evaluation-rating-disclosure"')
        self.assertContains(response, "Rating per Question")
        self.assertContains(response, "Overall average rating")
        self.assertContains(response, 'id="print-question-analysis"')
        self.assertContains(response, "Print / Save analysis as PDF")
        self.assertContains(response, 'class="analysis-print-header"')
        self.assertContains(response, "@page analysis-report")
        self.assertContains(response, 'counter(page) " / " counter(pages)')


class QuestionnairePrintLanguageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="print-admin", email="print@example.test", password="safe-password"
        )
        category = EventCategory.objects.create(
            code="SEMINAR_PRINT", name_en="Seminar print", name_sw="Semina chapisho"
        )
        now = timezone.now()
        self.event = Event.objects.create(
            category=category, code="PRINT-2026",
            title_en="English Event", title_sw="Tukio la Kiswahili",
            starts_at=now, ends_at=now + timedelta(days=1),
        )
        self.form = EventForm.objects.create(
            event=self.event, name_en="English Registration", name_sw="Usajili wa Kiswahili",
            introduction_en="English introduction only.",
            introduction_sw="Utangulizi wa Kiswahili pekee.",
        )
        section = FormSection.objects.create(
            event_form=self.form, title_en="English Details", title_sw="Maelezo ya Kiswahili",
            description_en="English section description.",
            description_sw="Maelezo ya sehemu kwa Kiswahili.",
        )
        question = FormQuestion.objects.create(
            section=section, label_en="English question?", label_sw="Swali la Kiswahili?",
            help_text_en="English help.", help_text_sw="Msaada wa Kiswahili.",
            question_type=FormQuestion.QuestionType.SINGLE_CHOICE,
        )
        QuestionOption.objects.create(
            question=question, value="YES", label_en="English choice", label_sw="Chaguo la Kiswahili"
        )
        self.client.force_login(self.user)
        self.url = reverse(
            "forms_builder:questionnaire_print", args=(self.event.slug, self.form.pk)
        )

    def test_english_print_contains_no_kiswahili_form_content(self):
        response = self.client.get(self.url, {"language": "en"})
        self.assertContains(response, "English Registration")
        self.assertContains(response, "English introduction only.")
        self.assertContains(response, "English question?")
        self.assertContains(response, "English choice")
        self.assertContains(response, "© MoEST")
        self.assertContains(response, "position: fixed")
        self.assertContains(response, "bottom: 0")
        self.assertNotContains(response, "1. English Details")
        self.assertNotContains(response, "1. English question?")
        self.assertNotContains(response, "Generated from the OutPermit")
        self.assertNotContains(response, "Usajili wa Kiswahili")
        self.assertNotContains(response, "Utangulizi wa Kiswahili pekee.")
        self.assertNotContains(response, "Swali la Kiswahili?")
        self.assertNotContains(response, "Chaguo la Kiswahili")

    def test_kiswahili_print_contains_no_english_form_content(self):
        response = self.client.get(self.url, {"language": "sw"})
        self.assertContains(response, "Usajili wa Kiswahili")
        self.assertContains(response, "Utangulizi wa Kiswahili pekee.")
        self.assertContains(response, "Swali la Kiswahili?")
        self.assertContains(response, "Chaguo la Kiswahili")
        self.assertContains(response, "© WyEST")
        self.assertNotContains(response, "1. Maelezo ya Kiswahili")
        self.assertNotContains(response, "1. Swali la Kiswahili?")
        self.assertNotContains(response, "Imetengenezwa kupitia")
        self.assertNotContains(response, "English Registration")
        self.assertNotContains(response, "English introduction only.")
        self.assertNotContains(response, "English question?")
        self.assertNotContains(response, "English choice")


class QuestionnaireExpressionTests(SimpleTestCase):
    def test_arithmetic_boolean_and_references(self):
        answers = {12: Decimal("4"), 13: Decimal("6"), 14: Decimal("3")}
        self.assertEqual(evaluate_expression("q12 + q13 * 2", answers), Decimal("16"))
        self.assertTrue(evaluate_expression("q12 <= q13 and q14 > 0", answers))
        self.assertEqual(question_reference_ids("q12 + q13"), {12, 13})

    def test_count_and_conditional_functions(self):
        answers = {12: ["a", "b"], 13: Decimal("6"), 14: ""}
        self.assertEqual(evaluate_expression("COUNT(q12, q13, q14)", answers), Decimal("3"))
        self.assertEqual(evaluate_expression("SUM(q13, 4)", answers), Decimal("10"))
        self.assertEqual(evaluate_expression("IF(q13 >= 5, q13 * 2, 0)", answers), Decimal("12"))
        self.assertEqual(question_reference_ids("IF(q13 > 0, COUNT(q12), 0)"), {12, 13})

    def test_unsafe_or_unknown_syntax_is_rejected(self):
        with self.assertRaises(ExpressionError):
            evaluate_expression("__import__('os')", {})
        with self.assertRaises(ExpressionError):
            evaluate_expression("unknown + 1", {})


class ConditionalRequiredTests(TestCase):
    def test_advanced_visibility_and_required_expressions_match_server_answers(self):
        category = EventCategory.objects.create(name_en="Expert", name_sw="Mtaalamu")
        event = Event.objects.create(
            category=category, code="EXP-2027", title_en="Expert", title_sw="Mtaalamu",
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=1),
        )
        event_form = EventForm.objects.create(
            event=event, name_en="Expert form", name_sw="Fomu ya mtaalamu",
            advanced_expression_mode=True,
        )
        first_section = event_form.sections.create(
            title_en="First", title_sw="Kwanza", display_order=1,
        )
        source = first_section.questions.create(
            label_en="Record type", label_sw="Aina ya rekodi",
            question_type=FormQuestion.QuestionType.DROPDOWN, display_order=1,
        )
        source.options.create(value="SPECIAL", label_en="Special", label_sw="Maalum")
        target = first_section.questions.create(
            label_en="Details", label_sw="Maelezo",
            question_type=FormQuestion.QuestionType.SHORT_TEXT, display_order=2,
            visibility_expression=f"q{source.pk} == 'SPECIAL'",
            required_expression=f"q{source.pk} == 'SPECIAL'",
        )
        target.full_clean()
        later_section = event_form.sections.create(
            title_en="Later", title_sw="Baadaye", display_order=2,
            visibility_expression=f"q{source.pk} == 'SPECIAL'",
        )
        later_section.full_clean()

        matching = RequestFactory().post("/", {f"question_{source.pk}": "SPECIAL"})
        other = RequestFactory().post("/", {f"question_{source.pk}": "OTHER"})
        self.assertTrue(target_is_visible(matching, target))
        self.assertFalse(target_is_visible(other, target))
        self.assertTrue(question_is_required(matching, target))
        self.assertFalse(question_is_required(other, target))
        self.assertTrue(target_is_visible(matching, later_section))
        self.assertFalse(target_is_visible(other, later_section))

    def test_advanced_condition_cannot_reference_a_later_question(self):
        category = EventCategory.objects.create(name_en="Order", name_sw="Mpangilio")
        event = Event.objects.create(
            category=category, code="ORDER-2027", title_en="Order", title_sw="Mpangilio",
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=1),
        )
        event_form = EventForm.objects.create(event=event, name_en="Form", name_sw="Fomu")
        section = event_form.sections.create(title_en="Section", title_sw="Sehemu")
        target = section.questions.create(
            label_en="Target", label_sw="Lengwa", display_order=1,
        )
        later = section.questions.create(
            label_en="Later", label_sw="Baadaye", display_order=2,
        )
        target.visibility_expression = f"q{later.pk} == 'YES'"
        with self.assertRaisesMessage(ValidationError, "earlier questions"):
            target.full_clean()

    def test_required_group_is_enforced_only_when_rules_match(self):
        category = EventCategory.objects.create(name_en="Survey", name_sw="Dodoso")
        event = Event.objects.create(
            category=category, code="REQ-2027", title_en="Required", title_sw="Lazima",
            slug="required", starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=1),
        )
        event_form = EventForm.objects.create(event=event, name_en="Form", name_sw="Fomu")
        section = event_form.sections.create(title_en="Section", title_sw="Sehemu")
        source = section.questions.create(
            label_en="Needs details?", label_sw="Maelezo?",
            question_type=FormQuestion.QuestionType.YES_NO,
        )
        target = section.questions.create(
            label_en="Details", label_sw="Maelezo",
            question_type=FormQuestion.QuestionType.SHORT_TEXT,
        )
        group = DisplayLogicGroup.objects.create(
            event_form=event_form, target_required_question=target,
        )
        DisplayLogicRule.objects.create(
            group=group, source_question=source,
            operator=DisplayLogicRule.Operator.EQUALS,
            comparison_value="yes",
        )
        self.assertTrue(question_is_required(
            RequestFactory().post("/", {f"question_{source.pk}": "yes"}), target
        ))
        self.assertFalse(question_is_required(
            RequestFactory().post("/", {f"question_{source.pk}": "no"}), target
        ))

    def test_visual_validation_can_validate_the_target_answer(self):
        category = EventCategory.objects.create(name_en="Survey", name_sw="Dodoso")
        event = Event.objects.create(
            category=category, code="VAL-2027", title_en="Validation", title_sw="Uthibitishaji",
            slug="validation", starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=1),
        )
        event_form = EventForm.objects.create(event=event, name_en="Form", name_sw="Fomu")
        section = event_form.sections.create(title_en="Section", title_sw="Sehemu")
        target = section.questions.create(
            label_en="Age", label_sw="Umri", question_type=FormQuestion.QuestionType.NUMBER,
        )
        group = DisplayLogicGroup.objects.create(
            event_form=event_form, target_validation_question=target,
        )
        rule = DisplayLogicRule.objects.create(
            group=group, source_question=target,
            operator=DisplayLogicRule.Operator.GREATER_THAN_OR_EQUAL,
            comparison_value="18",
        )
        rule.full_clean()
        self.assertTrue(question_passes_visual_validation(
            RequestFactory().post("/", {f"question_{target.pk}": "20"}), target
        ))
        self.assertFalse(question_passes_visual_validation(
            RequestFactory().post("/", {f"question_{target.pk}": "17"}), target
        ))


class RepeatableAnswerTests(TestCase):
    def test_same_question_can_store_multiple_repeat_entries(self):
        category = EventCategory.objects.create(name_en="Survey", name_sw="Dodoso")
        event = Event.objects.create(
            category=category, code="REP-2027", title_en="Repeat", title_sw="Rudia",
            slug="repeat", starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=1),
        )
        event_form = EventForm.objects.create(event=event, name_en="Form", name_sw="Fomu")
        section = event_form.sections.create(
            title_en="Representatives", title_sw="Wawakilishi", is_repeatable=True,
        )
        question = section.questions.create(
            label_en="Name", label_sw="Jina",
            question_type=FormQuestion.QuestionType.SHORT_TEXT,
        )
        submission = FormSubmission.objects.create(event_form=event_form)
        FormAnswer.objects.create(
            submission=submission, question=question, repeat_index=0, text_value="A",
        )
        FormAnswer.objects.create(
            submission=submission, question=question, repeat_index=1, text_value="B",
        )
        self.assertEqual(submission.answers.count(), 2)


class CalculatedAnswerTests(TestCase):
    def setUp(self):
        category = EventCategory.objects.create(name_en="Survey", name_sw="Dodoso")
        event = Event.objects.create(
            category=category, code="CALC-2027", title_en="Calculation",
            title_sw="Hesabu", slug="calculation", starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=1),
        )
        event_form = EventForm.objects.create(event=event, name_en="Form", name_sw="Fomu")
        section = event_form.sections.create(title_en="Numbers", title_sw="Namba")
        self.first = section.questions.create(
            label_en="First", label_sw="Kwanza",
            question_type=FormQuestion.QuestionType.NUMBER, display_order=1,
        )
        self.second = section.questions.create(
            label_en="Second", label_sw="Pili",
            question_type=FormQuestion.QuestionType.NUMBER, display_order=2,
        )
        self.total = section.questions.create(
            label_en="Total", label_sw="Jumla",
            question_type=FormQuestion.QuestionType.CALCULATED,
            calculation_expression=f"q{self.first.pk} + q{self.second.pk}",
            display_order=3,
        )

    def test_server_calculates_instead_of_trusting_posted_total(self):
        request = RequestFactory().post("/", {
            f"question_{self.first.pk}": "7.5",
            f"question_{self.second.pk}": "2.5",
            f"question_{self.total.pk}": "999",
        })
        values, unresolved = expression_answer_values(
            request, [self.first, self.second, self.total]
        )
        self.assertFalse(unresolved)
        self.assertEqual(values[self.total.pk], Decimal("10.00"))


class CascadingChoiceTests(TestCase):
    def setUp(self):
        category = EventCategory.objects.create(name_en="Survey", name_sw="Dodoso")
        event = Event.objects.create(
            category=category, code="CASCADE-2027", title_en="Cascade",
            title_sw="Mfuatano", slug="cascade", starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=1),
        )
        event_form = EventForm.objects.create(event=event, name_en="Form", name_sw="Fomu")
        section = event_form.sections.create(title_en="Location", title_sw="Mahali")
        self.country = section.questions.create(
            label_en="Country", label_sw="Nchi",
            question_type=FormQuestion.QuestionType.DROPDOWN, display_order=1,
        )
        self.country.options.create(value="TZ", label_en="Tanzania", label_sw="Tanzania")
        self.country.options.create(value="KE", label_en="Kenya", label_sw="Kenya")
        self.region = section.questions.create(
            label_en="Region", label_sw="Mkoa",
            question_type=FormQuestion.QuestionType.DROPDOWN,
            choice_filter_question=self.country, display_order=2,
        )
        self.tanga = self.region.options.create(
            value="TANGA", label_en="Tanga", label_sw="Tanga", filter_values="TZ"
        )
        self.nairobi = self.region.options.create(
            value="NAIROBI", label_en="Nairobi", label_sw="Nairobi", filter_values="KE"
        )
        self.other = self.region.options.create(
            value="OTHER", label_en="Other", label_sw="Nyingine", filter_values=""
        )

    def test_server_enforces_filtered_choices(self):
        request = RequestFactory().post("/", {
            f"question_{self.country.pk}": "TZ",
            f"question_{self.region.pk}": "NAIROBI",
        })
        self.assertFalse(choice_option_is_available(request, self.region, self.nairobi))
        self.assertTrue(choice_option_is_available(request, self.region, self.tanga))

    def test_unfiltered_option_is_always_available(self):
        request = RequestFactory().post("/", {
            f"question_{self.country.pk}": "KE",
        })
        self.assertTrue(choice_option_is_available(request, self.region, self.other))


class AdvancedDisplayLogicTests(TestCase):
    def setUp(self):
        category = EventCategory.objects.create(name_en="Conference", name_sw="Mkutano")
        self.event = Event.objects.create(
            category=category,
            code="LOGIC-2027",
            title_en="Logic event",
            title_sw="Tukio la mantiki",
            slug="logic-event",
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=1),
        )
        self.event_form = EventForm.objects.create(
            event=self.event, name_en="Survey", name_sw="Dodoso"
        )
        self.section = self.event_form.sections.create(
            title_en="Questions", title_sw="Maswali", display_order=1
        )
        self.first = self.section.questions.create(
            label_en="Score", label_sw="Alama",
            question_type=FormQuestion.QuestionType.NUMBER,
            display_order=1,
        )
        self.second = self.section.questions.create(
            label_en="Reason", label_sw="Sababu",
            question_type=FormQuestion.QuestionType.SHORT_TEXT,
            display_order=2,
        )
        self.target = self.section.questions.create(
            label_en="Follow-up", label_sw="Ufuatiliaji",
            question_type=FormQuestion.QuestionType.SHORT_TEXT,
            display_order=3,
        )

    def test_all_and_any_groups_are_enforced_on_server(self):
        group = DisplayLogicGroup.objects.create(
            event_form=self.event_form,
            target_question=self.target,
            match_type=DisplayLogicGroup.MatchType.ALL,
        )
        DisplayLogicRule.objects.create(
            group=group, source_question=self.first,
            operator=DisplayLogicRule.Operator.GREATER_THAN,
            comparison_value="3",
        )
        DisplayLogicRule.objects.create(
            group=group, source_question=self.second,
            operator=DisplayLogicRule.Operator.CONTAINS,
            comparison_value="innovation",
        )
        request = RequestFactory().post("/", {
            f"question_{self.first.pk}": "5",
            f"question_{self.second.pk}": "Education innovation",
        })
        self.assertTrue(target_is_visible(request, self.target))
        request = RequestFactory().post("/", {
            f"question_{self.first.pk}": "2",
            f"question_{self.second.pk}": "Education innovation",
        })
        self.assertFalse(target_is_visible(request, self.target))
        group.match_type = DisplayLogicGroup.MatchType.ANY
        group.save(update_fields=["match_type"])
        self.assertTrue(target_is_visible(request, self.target))

    def test_extended_operators(self):
        rule = SimpleNamespace(
            operator=DisplayLogicRule.Operator.ANY_OF,
            comparison_value="",
            comparison_values=["A", "B"],
        )
        self.assertTrue(rule_matches_values(rule, ["B"]))
        rule.operator = DisplayLogicRule.Operator.NONE_OF
        self.assertFalse(rule_matches_values(rule, ["A"]))
        rule.operator = DisplayLogicRule.Operator.NOT_ANSWERED
        self.assertTrue(rule_matches_values(rule, []))
        rule.operator = DisplayLogicRule.Operator.DATE_BEFORE
        rule.comparison_value = "2027-01-01"
        self.assertTrue(rule_matches_values(rule, ["2026-12-31"]))

    def test_indirect_question_cycle_is_rejected(self):
        first_group = DisplayLogicGroup.objects.create(
            event_form=self.event_form, target_question=self.first
        )
        DisplayLogicRule.objects.create(
            group=first_group, source_question=self.second,
            operator=DisplayLogicRule.Operator.ANSWERED,
        )
        second_group = DisplayLogicGroup.objects.create(
            event_form=self.event_form, target_question=self.second
        )
        form = LogicRuleForm(
            {
                "source_question": self.first.pk,
                "operator": DisplayLogicRule.Operator.ANSWERED,
            },
            group=second_group,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("circular", str(form.errors).lower())

    def test_nested_groups_support_mixed_and_or_expression(self):
        root = DisplayLogicGroup.objects.create(
            event_form=self.event_form,
            target_question=self.target,
            match_type=DisplayLogicGroup.MatchType.ANY,
        )
        first_pair = DisplayLogicGroup.objects.create(
            event_form=self.event_form,
            parent_group=root,
            match_type=DisplayLogicGroup.MatchType.ALL,
        )
        second_pair = DisplayLogicGroup.objects.create(
            event_form=self.event_form,
            parent_group=root,
            match_type=DisplayLogicGroup.MatchType.ALL,
        )
        for group, minimum, word in (
            (first_pair, "5", "innovation"),
            (second_pair, "10", "research"),
        ):
            DisplayLogicRule.objects.create(
                group=group,
                source_question=self.first,
                operator=DisplayLogicRule.Operator.GREATER_THAN,
                comparison_value=minimum,
            )
            DisplayLogicRule.objects.create(
                group=group,
                source_question=self.second,
                operator=DisplayLogicRule.Operator.CONTAINS,
                comparison_value=word,
            )

        request = RequestFactory().post("/", {
            f"question_{self.first.pk}": "7",
            f"question_{self.second.pk}": "Innovation programme",
        })
        self.assertTrue(target_is_visible(request, self.target))
        request = RequestFactory().post("/", {
            f"question_{self.first.pk}": "11",
            f"question_{self.second.pk}": "No matching phrase",
        })
        self.assertFalse(target_is_visible(request, self.target))
        spec = group_spec(self.target)
        self.assertEqual(spec["match"], "ANY")
        self.assertEqual(len(spec["groups"]), 2)

    def test_question_to_question_numeric_comparison(self):
        group = DisplayLogicGroup.objects.create(
            event_form=self.event_form,
            target_question=self.target,
        )
        rule = DisplayLogicRule.objects.create(
            group=group,
            source_question=self.first,
            comparison_question=self.second,
            operator=DisplayLogicRule.Operator.GREATER_THAN,
        )
        request = RequestFactory().post("/", {
            f"question_{self.first.pk}": "8",
            f"question_{self.second.pk}": "5",
        })
        self.assertTrue(target_is_visible(request, self.target))
        request = RequestFactory().post("/", {
            f"question_{self.first.pk}": "3",
            f"question_{self.second.pk}": "5",
        })
        self.assertFalse(target_is_visible(request, self.target))
        self.assertIn("answer to", rule.summary_en)

    def test_new_range_text_and_selection_count_operators(self):
        rule = SimpleNamespace(
            operator=DisplayLogicRule.Operator.BETWEEN,
            comparison_value="5",
            comparison_value_end="10",
            comparison_values=[],
            comparison_question_id=None,
        )
        self.assertTrue(rule_matches_values(rule, ["7"]))
        rule.operator = DisplayLogicRule.Operator.GREATER_THAN_OR_EQUAL
        rule.comparison_value = "7"
        self.assertTrue(rule_matches_values(rule, ["7"]))
        rule.operator = DisplayLogicRule.Operator.STARTS_WITH
        rule.comparison_value = "Ministry"
        self.assertTrue(rule_matches_values(rule, ["MINISTRY of Education"]))
        rule.operator = DisplayLogicRule.Operator.SELECTION_COUNT_AT_LEAST
        rule.comparison_value = "2"
        self.assertTrue(rule_matches_values(rule, ["A", "B"]))


class RegistrationIdentityConflictTests(SimpleTestCase):
    def setUp(self):
        self.existing = SimpleNamespace(
            submitter_email="Participant@Example.com",
            submitter_phone="+255 712 345 678",
        )

    def test_matching_email_blocks_registration_even_with_different_phone(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                " participant@example.com ",
                "0755000000",
            )
        )
        self.assertIs(duplicate, self.existing)
        self.assertTrue(email_conflict)
        self.assertFalse(phone_conflict)

    def test_matching_phone_blocks_registration_even_with_different_email(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                "different@example.com",
                "0712-345-678",
            )
        )
        self.assertIs(duplicate, self.existing)
        self.assertFalse(email_conflict)
        self.assertTrue(phone_conflict)

    def test_different_email_and_phone_are_allowed(self):
        duplicate, email_conflict, phone_conflict = (
            registration_identity_conflicts(
                [self.existing],
                "different@example.com",
                "0755000000",
            )
        )
        self.assertIsNone(duplicate)
        self.assertFalse(email_conflict)
        self.assertFalse(phone_conflict)


class InstitutionCertificateTests(SimpleTestCase):
    def submission(self, event_code="WEUUTZ-2026", organization="Innovation Institute"):
        event = SimpleNamespace(code=event_code)
        event_form = SimpleNamespace(event=event)
        return SimpleNamespace(
            event_form=event_form,
            badge_organization=organization,
            badge_display_name="Asha Representative",
        )

    def test_weuutz_certificate_is_awarded_to_institution(self):
        submission = self.submission()

        self.assertTrue(certificate_is_for_institution(submission))
        self.assertEqual(
            certificate_recipient_name(submission),
            "Innovation Institute",
        )
        self.assertEqual(submission.badge_display_name, "Asha Representative")

    def test_institution_abbreviation_case_is_preserved(self):
        submission = self.submission(
            organization="Moshi Co-operative University (MoCU)"
        )

        self.assertEqual(
            certificate_display_recipient_name(submission),
            "MOSHI CO-OPERATIVE UNIVERSITY (MoCU)",
        )

    def test_standalone_mixed_case_abbreviation_is_preserved(self):
        submission = self.submission(
            organization="Ministry of Education, Science and Technology MoEST"
        )

        self.assertEqual(
            certificate_display_recipient_name(submission),
            "MINISTRY OF EDUCATION, SCIENCE AND TECHNOLOGY MoEST",
        )

    def test_other_event_certificate_remains_awarded_to_participant(self):
        submission = self.submission(event_code="NESIF-2026")

        self.assertFalse(certificate_is_for_institution(submission))
        self.assertEqual(
            certificate_recipient_name(submission),
            "Asha Representative",
        )

    def test_weuutz_certificate_uses_approved_event_wording(self):
        event = SimpleNamespace(
            starts_at=timezone.make_aware(
                datetime(2026, 8, 15, 8, 0)
            ),
            ends_at=timezone.make_aware(
                datetime(2026, 8, 24, 17, 0)
            ),
            venue=None,
        )

        self.assertEqual(
            weuutz_event_sentence(event),
            "Participated in the National Education, Skills and Innovation "
            "Week 2026 Exhibitions which was held from 15th to 24th August, "
            "2026 in Tanga.",
        )
        self.assertIn(
            "15<sup>th</sup> to 24<sup>th</sup> August, 2026",
            str(weuutz_event_sentence_html(event)),
        )
        self.assertIn(
            "15ᵗʰ to 24ᵗʰ August, 2026",
            weuutz_event_sentence(event, superscript=True),
        )

    def test_qr_code_places_supplied_logo_at_center(self):
        with NamedTemporaryFile(suffix=".png") as logo_file:
            Image.new("RGB", (80, 80), "#d71920").save(logo_file, format="PNG")
            logo_file.flush()
            qr_png = generate_qr_png(
                "https://example.test/certificate/verify/",
                logo_path=logo_file.name,
            )

        qr_image = Image.open(BytesIO(qr_png)).convert("RGB")
        center = qr_image.getpixel((qr_image.width // 2, qr_image.height // 2))
        self.assertGreater(center[0], 180)
        self.assertLess(center[1], 80)
        self.assertLess(center[2], 80)

    def test_qr_code_places_default_system_logo_at_center(self):
        with NamedTemporaryFile(suffix=".png") as logo_file:
            Image.new("RGB", (80, 80), "#d71920").save(
                logo_file,
                format="PNG",
            )
            logo_file.flush()
            with patch(
                "forms_builder.services.finders.find",
                return_value=logo_file.name,
            ):
                qr_png = generate_qr_png("https://example.test/existing-link/")

        qr_image = Image.open(BytesIO(qr_png)).convert("RGB")
        center = qr_image.getpixel((qr_image.width // 2, qr_image.height // 2))
        self.assertGreater(center[0], 180)
        self.assertLess(center[1], 80)
        self.assertLess(center[2], 80)


class WEUUTzEvaluationSetupTests(TestCase):
    def setUp(self):
        category = EventCategory.objects.create(
            name_sw="Maonesho",
            name_en="Exhibition",
            code="EXHIBITION",
        )
        starts_at = timezone.now() + timedelta(days=1)
        self.event = Event.objects.create(
            category=category,
            code="WEUUTz-2026",
            title_sw="Wiki ya Elimu na Ubunifu",
            title_en="Education and Innovation Week",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(days=3),
        )
        self.form = EventForm.objects.create(
            event=self.event,
            name_sw="Tathmini",
            name_en="Exhibition Evaluation",
            form_type=EventForm.FormType.EVALUATION,
            is_published=True,
        )
        section = self.form.sections.create(
            title_sw="Maoni ya Washiriki",
            title_en="Participants Views",
        )
        self.original_question = section.questions.create(
            label_sw="Ni bidhaa gani iliyokuvutia?",
            label_en="Which product, technology, or exhibitor interested you most?",
            question_type=FormQuestion.QuestionType.SHORT_TEXT,
            is_required=True,
        )

    def test_command_requires_confirmation(self):
        with self.assertRaises(CommandError):
            call_command("setup_weuutz_evaluation")

    def test_registration_routing_is_removed_without_deleting_history(self):
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Fomu ya Usajili wa Waoneshaji",
            name_en="Exhibition Participant Registration Form",
            slug="exhibition-participant-registration-form",
            form_type=EventForm.FormType.EXHIBITOR,
            is_published=True,
        )
        institution = registration_form.sections.create(
            title_sw="Taarifa za Taasisi",
            title_en="Institution Information",
            display_order=1,
        )
        institution_name_question = institution.questions.create(
            label_sw="Jina la Taasisi",
            label_en="Institution Name",
            is_required=True,
        )
        representative = registration_form.sections.create(
            title_sw="Taarifa za Mwakilishi",
            title_en="Representative Information",
            display_order=2,
        )
        participation = registration_form.sections.create(
            title_sw="Aina ya Ushiriki",
            title_en="Participation Type",
            display_order=3,
        )
        participation_question = participation.questions.create(
            label_sw="Unakusudia kushiriki sehemu ipi?",
            label_en="In which part(s) of the event do you intend to participate?",
            question_type=FormQuestion.QuestionType.MULTIPLE_CHOICE,
            is_required=True,
        )
        exhibition_option = QuestionOption.objects.create(
            question=participation_question,
            value="EXHIBITION",
            label_sw="Maonesho",
            label_en="Exhibition",
        )
        booth_section = registration_form.sections.create(
            title_sw="Mabanda",
            title_en="Booths",
            display_order=4,
            condition_question=participation_question,
            condition_value="EXHIBITION",
        )
        conference_section = registration_form.sections.create(
            title_sw="Maeneo ya Kongamano",
            title_en="Conference Areas",
            display_order=5,
            condition_question=participation_question,
            condition_value="CONFERENCE",
        )
        conference_section.questions.create(
            label_sw="Chagua eneo la kongamano",
            label_en="Choose a conference area",
            is_required=True,
        )
        other_section = registration_form.sections.create(
            title_sw="Ushiriki Mwingine",
            title_en="Other Participation",
            display_order=6,
            condition_question=participation_question,
            condition_value="OTHER",
        )
        other_section.questions.create(
            label_sw="Taja ushiriki mwingine",
            label_en="Specify other participation",
            is_required=True,
        )
        submission = FormSubmission.objects.create(
            event_form=registration_form,
            is_complete=True,
        )
        historical_answer = FormAnswer.objects.create(
            submission=submission,
            question=participation_question,
        )
        historical_answer.selected_options.add(exhibition_option)

        call_command("setup_weuutz_registration", "--confirm")
        call_command("setup_weuutz_registration", "--confirm")

        self.assertTrue(FormAnswer.objects.filter(pk=historical_answer.pk).exists())
        submission.refresh_from_db()
        self.assertEqual(
            submission.review_status,
            FormSubmission.ReviewStatus.APPROVED,
        )
        participation.refresh_from_db()
        conference_section.refresh_from_db()
        other_section.refresh_from_db()
        booth_section.refresh_from_db()
        participation_question.refresh_from_db()
        institution_name_question.refresh_from_db()
        self.assertFalse(participation.is_active)
        self.assertFalse(participation_question.is_active)
        self.assertFalse(conference_section.is_active)
        self.assertFalse(other_section.is_active)
        self.assertIsNone(booth_section.condition_question_id)
        self.assertEqual(booth_section.condition_value, "")
        self.assertEqual(
            institution_name_question.placeholder_en,
            "e.g., University of Dar es Salaam (UDSM)",
        )
        self.assertEqual(
            institution_name_question.placeholder_sw,
            "mf., Chuo Kikuu cha Dar es Salaam (UDSM)",
        )
        self.assertEqual(
            list(
                registration_form.sections.filter(is_active=True)
                .order_by("display_order")
                .values_list("title_en", "display_order")
            ),
            [
                (institution.title_en, 1),
                (representative.title_en, 2),
                (booth_section.title_en, 3),
            ],
        )

    def test_registration_draft_is_saved_and_restored_by_private_token(self):
        self.event.status = self.event.Status.REGISTRATION_OPEN
        self.event.save(update_fields=["status", "updated_at"])
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Usajili wa Maonesho",
            name_en="Exhibition Registration",
            slug="resumable-exhibition-registration",
            form_type=EventForm.FormType.EXHIBITOR,
            is_published=True,
        )
        section = registration_form.sections.create(
            title_sw="Taarifa za Taasisi",
            title_en="Institution Information",
        )
        question = section.questions.create(
            label_sw="Jina la Taasisi",
            label_en="Institution Name",
            is_required=True,
        )
        registration_url = reverse(
            "forms_builder:public_event_form",
            kwargs={
                "event_slug": self.event.slug,
                "form_slug": registration_form.slug,
            },
        )

        initial_response = self.client.get(registration_url)
        self.assertContains(initial_response, 'data-draft-autosave="true"')
        save_response = self.client.post(
            registration_url,
            {
                "_save_draft": "1",
                f"question_{question.pk}": "University of Dodoma",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(save_response.status_code, 200)
        draft_token = save_response.json()["draft_token"]
        draft = FormSubmission.objects.get(
            event_form=registration_form,
            participant_token=draft_token,
            is_complete=False,
        )
        self.assertEqual(draft.answers.get().text_value, "University of Dodoma")
        restored_response = self.client.get(
            registration_url,
            {"draft": draft_token},
        )
        self.assertEqual(
            restored_response.context["draft_answer_values"],
            {str(question.pk): "University of Dodoma"},
        )
        self.assertContains(
            restored_response,
            f'data-draft-token="{draft_token}"',
        )

        complete_response = self.client.post(
            f"{registration_url}?draft={draft_token}",
            {
                "_draft_token": draft_token,
                f"question_{question.pk}": "University of Dodoma",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(complete_response.status_code, 200)
        self.assertTrue(complete_response.json()["success"])
        draft.refresh_from_db()
        self.assertTrue(draft.is_complete)
        self.assertEqual(
            draft.review_status,
            FormSubmission.ReviewStatus.APPROVED,
        )

    def test_admin_approval_skips_incomplete_drafts(self):
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Usajili wa Waoneshaji",
            name_en="Exhibitor Registration",
            form_type=EventForm.FormType.EXHIBITOR,
            is_published=True,
        )
        draft = FormSubmission.objects.create(
            event_form=registration_form,
            is_complete=False,
            review_status=FormSubmission.ReviewStatus.PENDING,
        )
        completed = FormSubmission.objects.create(
            event_form=registration_form,
            is_complete=True,
            review_status=FormSubmission.ReviewStatus.PENDING,
        )
        administrator = get_user_model().objects.create_superuser(
            username="draft-review-admin",
            email="draft-review@example.com",
            password="safe-test-password",
        )
        request = RequestFactory().post("/admin/forms-builder/")
        request.user = administrator
        SessionMiddleware(lambda response: response).process_request(request)
        request.session.save()
        MessageMiddleware(lambda response: response).process_request(request)
        model_admin = FormSubmissionAdmin(FormSubmission, admin.site)

        model_admin.approve_submissions(
            request,
            FormSubmission.objects.filter(pk__in=[draft.pk, completed.pk]),
        )

        draft.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(
            draft.review_status,
            FormSubmission.ReviewStatus.PENDING,
        )
        self.assertEqual(
            completed.review_status,
            FormSubmission.ReviewStatus.APPROVED,
        )
        self.assertEqual(
            model_admin.review_status_badge(draft),
            "Draft — not submitted",
        )
        warning_messages = [str(message) for message in messages.get_messages(request)]
        self.assertTrue(any("were not changed" in message for message in warning_messages))

    def test_command_improves_only_weuutz_form_and_is_idempotent(self):
        country = Country.objects.create(
            name_sw="Tanzania",
            name_en="Tanzania",
            code="TZ",
        )
        Region.objects.create(
            country=country,
            name_sw="Dodoma",
            name_en="Dodoma",
            code="01",
        )
        Region.objects.create(
            country=country,
            name_sw="Tanga",
            name_en="Tanga",
            code="02",
        )
        output = StringIO()
        call_command("setup_weuutz_evaluation", "--confirm", stdout=output)
        call_command("setup_weuutz_evaluation", "--confirm", stdout=output)

        self.event.refresh_from_db()
        self.form.refresh_from_db()
        self.original_question.refresh_from_db()
        questions = FormQuestion.objects.filter(section__event_form=self.form)

        self.assertTrue(self.event.evaluation_enabled)
        self.assertTrue(self.form.is_published)
        self.assertTrue(self.form.requires_participant_registration)
        self.assertFalse(self.form.show_event_summary)
        self.assertEqual(self.form.name_en, "Commemoration Evaluation Questionnaire")
        self.assertEqual(self.form.name_sw, "Dodoso la Tathmini ya Maadhimisho")
        self.assertEqual(questions.filter(is_active=True).count(), 39)
        self.assertFalse(self.original_question.is_active)
        self.assertEqual(
            self.form.sections.filter(is_active=True).count(),
            5,
        )
        self.assertEqual(
            list(
                self.form.sections.filter(is_active=True)
                .order_by("display_order")
                .values_list("title_en", flat=True)
            ),
            [
                "SECTION A: PARTICIPATION AND VISITOR RESPONSE",
                "SECTION B: EXHIBITION ORGANIZATION AND OPERATIONS",
                "SECTION C: PARTICIPATION BENEFITS AND OUTCOMES",
                "SECTION D: OVERALL EVALUATION",
                "SECTION E: ACHIEVEMENTS, CHALLENGES AND RECOMMENDATIONS",
            ],
        )
        section_b = self.form.sections.get(display_order=2, is_active=True)
        section_c = self.form.sections.get(display_order=3, is_active=True)
        self.assertEqual(
            section_b.description_en,
            "Please rate the following areas using the 1–5 scale, where "
            "1 = Very poor, 2 = Poor, 3 = Fair, 4 = Good, 5 = Very good.",
        )
        self.assertEqual(
            section_c.description_en,
            "To what extent did your institution's participation achieve the "
            "following outcomes? Where 1 = Not achieved, 2 = Slightly, "
            "3 = Moderate, 4 = Achieved, 5 = Highly achieved.",
        )
        expected_question_counts = {"A": 5, "B": 12, "C": 11, "D": 3, "E": 8}
        for section_letter, question_count in expected_question_counts.items():
            section = self.form.sections.get(
                display_order=ord(section_letter) - ord("A") + 1,
                is_active=True,
            )
            labels = list(
                section.questions.filter(is_active=True)
                .order_by("display_order", "pk")
                .values_list("label_en", flat=True)
            )
            self.assertEqual(len(labels), question_count)
            self.assertEqual(
                [label.split(".", 1)[0] for label in labels],
                [f"{section_letter}{number}" for number in range(1, question_count + 1)],
            )
        self.assertFalse(
            self.form.sections.filter(
                is_active=True,
                title_en="SECTION A: PARTICIPANT/INSTITUTION INFORMATION",
            ).exists()
        )
        self.assertFalse(
            questions.filter(
                is_active=True,
                label_en="Institution/organization name",
            ).exists()
        )
        other_fields = questions.filter(is_active=True, condition_value="OTHER")
        self.assertEqual(other_fields.count(), 2)
        self.assertTrue(all(question.is_required for question in other_fields))
        self.assertTrue(all(question.condition_question_id for question in other_fields))
        region_question = questions.get(
            is_active=True,
            label_en__startswith="E8. Which region",
        )
        self.assertEqual(
            region_question.question_type,
            FormQuestion.QuestionType.DROPDOWN,
        )
        self.assertTrue(region_question.is_required)
        self.assertEqual(
            region_question.help_text_sw,
            "Tafadhali chagua mkoa MMOJA tu.",
        )
        self.assertEqual(
            list(
                region_question.options.filter(is_active=True)
                .order_by("display_order")
                .values_list("label_sw", flat=True)
            ),
            ["Dodoma", "Tanga"],
        )

    def test_evaluation_is_available_only_through_linked_participant_portal(self):
        call_command("setup_weuutz_evaluation", "--confirm")
        self.event.refresh_from_db()
        evaluation_form = self.event.forms.get(
            form_type=EventForm.FormType.EVALUATION,
        )
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Usajili",
            name_en="Registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_published=True,
        )
        registration = FormSubmission.objects.create(
            event_form=registration_form,
            submitter_email="representative@example.com",
            submitter_phone="0712345678",
            is_complete=True,
        )
        evaluation_url = reverse(
            "forms_builder:public_event_form",
            kwargs={
                "event_slug": self.event.slug,
                "form_slug": evaluation_form.slug,
            },
        )

        direct_response = self.client.get(evaluation_url)
        self.assertRedirects(
            direct_response,
            reverse("forms_builder:registration_status"),
        )
        response = self.client.get(
            evaluation_url,
            {"participant": registration.participant_token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["participant_registration"], registration)
        self.assertContains(response, 'class="likert-table"', count=2)
        self.assertContains(response, 'class="likert-choice"', count=100)
        self.assertContains(response, 'class="questions-container likert-follow-up"')
        self.assertContains(
            response,
            "Were any important new collaborations, opportunities or contacts obtained?",
        )

        portal_url = reverse(
            "forms_builder:participant_portal",
            kwargs={"participant_token": registration.participant_token},
        )
        portal_response = self.client.get(portal_url)
        self.assertContains(
            portal_response,
            f"?participant={registration.participant_token}",
        )
        self.assertContains(
            response,
            f"?participant={registration.participant_token}",
            count=2,
        )

        language_response = self.client.post(
            reverse("set_language"),
            {
                "language": "sw",
                "next": (
                    f"{evaluation_url}?participant="
                    f"{registration.participant_token}"
                ),
            },
            follow=True,
        )
        self.assertContains(
            language_response,
            "Tafadhali jaza dodoso hili kwa niaba ya taasisi yako.",
        )
        self.assertContains(
            language_response,
            "SEHEMU A: USHIRIKI NA MWITIKIO WA WATEMBELEAJI",
        )
        self.assertContains(language_response, "Inayofuata")
        self.assertContains(language_response, "Wasilisha tathmini")
        self.client.post(
            reverse("set_language"),
            {"language": "en", "next": evaluation_url},
        )

        public_event_response = self.client.get(
            reverse(
                "events:event_detail",
                kwargs={"event_slug": self.event.slug},
            )
        )
        self.assertContains(
            public_event_response,
            evaluation_form.name_en,
        )
        self.assertContains(
            public_event_response,
            reverse("forms_builder:registration_status"),
        )
        self.assertContains(
            public_event_response,
            "Open participant portal",
        )
        self.assertNotContains(public_event_response, f'href="{evaluation_url}"')

        administrator = get_user_model().objects.create_superuser(
            username="evaluation-admin",
            email="evaluation-admin@example.com",
            password="safe-test-password",
        )
        self.client.force_login(administrator)
        administrator_response = self.client.get(
            reverse(
                "events:event_detail",
                kwargs={"event_slug": self.event.slug},
            )
        )
        self.assertContains(administrator_response, "Preview questions")
        self.assertContains(
            administrator_response,
            f'{evaluation_url}?preview=1',
        )

        admin_tools = str(
            EventFormAdmin(EventForm, admin.site).registration_tools(
                evaluation_form
            )
        )
        self.assertIn(f"{evaluation_url}?preview=1", admin_tools)
        self.assertIn("Preview form", admin_tools)
        self.assertNotIn("View QR", admin_tools)

    def test_participant_evaluation_draft_is_saved_and_restored(self):
        call_command("setup_weuutz_evaluation", "--confirm")
        evaluation_form = self.event.forms.get(
            form_type=EventForm.FormType.EVALUATION,
        )
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Usajili",
            name_en="Registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_published=True,
        )
        registration = FormSubmission.objects.create(
            event_form=registration_form,
            submitter_email="draft@example.com",
            is_complete=True,
        )
        first_question = (
            evaluation_form.sections.get(display_order=1)
            .questions.get(display_order=1, is_active=True)
        )
        selected_option = first_question.options.filter(is_active=True).first()
        evaluation_url = reverse(
            "forms_builder:public_event_form",
            kwargs={
                "event_slug": self.event.slug,
                "form_slug": evaluation_form.slug,
            },
        )
        participant_url = (
            f"{evaluation_url}?participant={registration.participant_token}"
        )

        save_response = self.client.post(
            participant_url,
            {
                "_save_draft": "1",
                f"question_{first_question.pk}": selected_option.value,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_response.json()["draft_saved"])
        draft = FormSubmission.objects.get(
            event_form=evaluation_form,
            registration_submission=registration,
            is_complete=False,
        )
        self.assertEqual(draft.answers.count(), 1)
        restored_response = self.client.get(participant_url)
        self.assertEqual(
            restored_response.context["draft_answer_values"],
            {str(first_question.pk): [selected_option.value]},
        )
        self.assertContains(restored_response, 'data-draft-autosave="true"')

    def test_pending_registration_can_access_badge_but_not_certificate(self):
        self.event.badge_enabled = True
        self.event.certificate_enabled = True
        self.event.save(update_fields=[
            "badge_enabled", "certificate_enabled", "updated_at",
        ])
        registration_form = EventForm.objects.create(
            event=self.event,
            name_sw="Usajili",
            name_en="Registration",
            form_type=EventForm.FormType.REGISTRATION,
            is_published=True,
        )
        registration = FormSubmission.objects.create(
            event_form=registration_form,
            review_status=FormSubmission.ReviewStatus.PENDING,
            is_complete=True,
        )

        badge_url = reverse(
            "forms_builder:participant_badge",
            kwargs={"participant_token": registration.participant_token},
        )
        self.assertEqual(self.client.get(badge_url).status_code, 200)

        portal_url = reverse(
            "forms_builder:participant_portal",
            kwargs={"participant_token": registration.participant_token},
        )
        portal_response = self.client.get(portal_url)
        certificate_url = reverse(
            "forms_builder:participant_certificate",
            kwargs={"participant_token": registration.participant_token},
        )
        self.assertNotContains(portal_response, certificate_url)
