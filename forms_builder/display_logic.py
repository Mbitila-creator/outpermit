import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .models import DisplayLogicGroup, DisplayLogicRule, FormQuestion, FormSection


NO_VALUE_OPERATORS = {
    DisplayLogicRule.Operator.ANSWERED,
    DisplayLogicRule.Operator.NOT_ANSWERED,
}
MULTI_VALUE_OPERATORS = {
    DisplayLogicRule.Operator.ANY_OF,
    DisplayLogicRule.Operator.NONE_OF,
}


def request_answer_values(request, question_id):
    return [value.strip() for value in request.POST.getlist(
        f"question_{question_id}"
    ) if value.strip()]


def rule_matches_values(rule, values, comparison_values=None):
    operator = rule.operator
    expected = rule.comparison_value
    comparison_values = comparison_values or []
    if getattr(rule, "comparison_question_id", None):
        expected = comparison_values[0] if comparison_values else ""
    if operator == DisplayLogicRule.Operator.ANSWERED:
        return bool(values)
    if operator == DisplayLogicRule.Operator.NOT_ANSWERED:
        return not values
    if operator == DisplayLogicRule.Operator.EQUALS:
        return expected in values
    if operator == DisplayLogicRule.Operator.NOT_EQUALS:
        return expected not in values
    if operator == DisplayLogicRule.Operator.CONTAINS:
        return any(expected.casefold() in value.casefold() for value in values)
    if operator == DisplayLogicRule.Operator.NOT_CONTAINS:
        return not any(expected.casefold() in value.casefold() for value in values)
    if operator == DisplayLogicRule.Operator.ANY_OF:
        return bool(set(values) & set(map(str, rule.comparison_values)))
    if operator == DisplayLogicRule.Operator.NONE_OF:
        return not bool(set(values) & set(map(str, rule.comparison_values)))
    if operator == DisplayLogicRule.Operator.STARTS_WITH:
        return any(value.casefold().startswith(expected.casefold()) for value in values)
    if operator == DisplayLogicRule.Operator.ENDS_WITH:
        return any(value.casefold().endswith(expected.casefold()) for value in values)
    if operator in {
        DisplayLogicRule.Operator.SELECTION_COUNT_EQUALS,
        DisplayLogicRule.Operator.SELECTION_COUNT_AT_LEAST,
        DisplayLogicRule.Operator.SELECTION_COUNT_AT_MOST,
    }:
        try:
            target_count = int(expected)
        except (TypeError, ValueError):
            return False
        if operator == DisplayLogicRule.Operator.SELECTION_COUNT_EQUALS:
            return len(values) == target_count
        if operator == DisplayLogicRule.Operator.SELECTION_COUNT_AT_LEAST:
            return len(values) >= target_count
        return len(values) <= target_count
    if not values:
        return False
    if operator in {
        DisplayLogicRule.Operator.GREATER_THAN,
        DisplayLogicRule.Operator.GREATER_THAN_OR_EQUAL,
        DisplayLogicRule.Operator.LESS_THAN,
        DisplayLogicRule.Operator.LESS_THAN_OR_EQUAL,
        DisplayLogicRule.Operator.BETWEEN,
    }:
        try:
            actual, target = Decimal(values[0]), Decimal(expected)
        except (InvalidOperation, TypeError, ValueError):
            return False
        if operator == DisplayLogicRule.Operator.GREATER_THAN:
            return actual > target
        if operator == DisplayLogicRule.Operator.GREATER_THAN_OR_EQUAL:
            return actual >= target
        if operator == DisplayLogicRule.Operator.LESS_THAN:
            return actual < target
        if operator == DisplayLogicRule.Operator.LESS_THAN_OR_EQUAL:
            return actual <= target
        try:
            upper = Decimal(rule.comparison_value_end)
        except (InvalidOperation, TypeError, ValueError):
            return False
        return target <= actual <= upper
    if operator in {
        DisplayLogicRule.Operator.DATE_BEFORE,
        DisplayLogicRule.Operator.DATE_AFTER,
    }:
        try:
            actual, target = date.fromisoformat(values[0][:10]), date.fromisoformat(expected[:10])
        except (TypeError, ValueError):
            return False
        return actual < target if operator == DisplayLogicRule.Operator.DATE_BEFORE else actual > target
    return True


def logic_group_matches(group, answer_values):
    results = []
    for rule in group.rules.filter(is_active=True).select_related(
        "source_question", "comparison_question"
    ):
        compared = (
            answer_values(rule.comparison_question_id)
            if rule.comparison_question_id
            else None
        )
        results.append(
            rule_matches_values(
                rule,
                answer_values(rule.source_question_id),
                compared,
            )
        )
    results.extend(
        logic_group_matches(child, answer_values)
        for child in group.child_groups.filter(is_active=True)
    )
    if not results:
        return True
    return (
        all(results)
        if group.match_type == DisplayLogicGroup.MatchType.ALL
        else any(results)
    )


def target_is_visible(request, target):
    try:
        group = target.display_logic
    except DisplayLogicGroup.DoesNotExist:
        if not target.condition_question_id or not target.condition_value:
            return True
        return target.condition_value in request_answer_values(
            request, target.condition_question_id
        )
    return logic_group_matches(
        group,
        lambda question_id: request_answer_values(request, question_id),
    )


def question_is_required(request, question):
    if question.is_required:
        return True
    try:
        group = question.required_logic
    except DisplayLogicGroup.DoesNotExist:
        return False
    return logic_group_matches(
        group,
        lambda question_id: request_answer_values(request, question_id),
    )


def logic_group_spec(group):
    rules = [{
        "question": rule.source_question_id,
        "comparison_question": rule.comparison_question_id,
        "operator": rule.operator,
        "value": rule.comparison_value,
        "value_end": rule.comparison_value_end,
        "values": rule.comparison_values,
    } for rule in group.rules.filter(is_active=True)]
    children = [
        logic_group_spec(child)
        for child in group.child_groups.filter(is_active=True)
    ]
    return {
        "match": group.match_type,
        "rules": rules,
        "groups": children,
    }


def group_spec(target):
    try:
        group = target.display_logic
    except DisplayLogicGroup.DoesNotExist:
        if target.condition_question_id and target.condition_value:
            return {
                "match": "ALL",
                "rules": [{
                    "question": target.condition_question_id,
                    "operator": "EQUALS",
                    "value": target.condition_value,
                    "values": [],
                }],
            }
        return None
    spec = logic_group_spec(group)
    return spec if spec["rules"] or spec["groups"] else None


def group_spec_json(target):
    spec = group_spec(target)
    return json.dumps(spec, separators=(",", ":")) if spec else ""


def required_group_spec_json(question):
    try:
        group = question.required_logic
    except DisplayLogicGroup.DoesNotExist:
        return ""
    spec = logic_group_spec(group)
    return json.dumps(spec, separators=(",", ":")) if spec["rules"] or spec["groups"] else ""


def validation_group_spec_json(question):
    try:
        group = question.validation_logic
    except DisplayLogicGroup.DoesNotExist:
        return ""
    spec = logic_group_spec(group)
    return json.dumps(spec, separators=(",", ":")) if spec["rules"] or spec["groups"] else ""


def question_passes_visual_validation(request, question):
    try:
        group = question.validation_logic
    except DisplayLogicGroup.DoesNotExist:
        return True
    return logic_group_matches(
        group, lambda question_id: request_answer_values(request, question_id)
    )


def validate_dependency_graph(event_form, *, pending_target=None, pending_source=None, ignored_rule=None):
    """Reject cycles across question rules, section rules, and section membership."""
    graph = {}
    questions = FormQuestion.objects.filter(
        section__event_form=event_form, is_active=True
    ).select_related("condition_question")
    for question in questions:
        question_node = ("question", question.pk)
        section_node = ("section", question.section_id)
        graph.setdefault(question_node, set()).add(section_node)
        graph.setdefault(section_node, set())
        if question.condition_question_id:
            graph[question_node].add(("question", question.condition_question_id))
    sections = event_form.sections.filter(is_active=True)
    for section in sections:
        section_node = ("section", section.pk)
        graph.setdefault(section_node, set())
        if section.condition_question_id:
            graph[section_node].add(("question", section.condition_question_id))
    rules = DisplayLogicRule.objects.filter(
        group__event_form=event_form,
        is_active=True,
    ).select_related("group")
    if ignored_rule and ignored_rule.pk:
        rules = rules.exclude(pk=ignored_rule.pk)
    for rule in rules:
        root = rule.group.root_group
        target_question_id = (
            root.target_question_id or root.target_required_question_id
            or root.target_validation_question_id
        )
        target_node = (
            ("question", target_question_id)
            if target_question_id
            else ("section", root.target_section_id)
        )
        graph.setdefault(target_node, set())
        if not (
            root.target_validation_question_id
            and root.target_validation_question_id == rule.source_question_id
        ):
            graph[target_node].add(("question", rule.source_question_id))
        if rule.comparison_question_id:
            graph[target_node].add(("question", rule.comparison_question_id))
    if pending_target and pending_source:
        target_node = (
            ("section", pending_target.pk)
            if isinstance(pending_target, FormSection)
            else ("question", pending_target.pk)
        )
        graph.setdefault(target_node, set()).add(("question", pending_source.pk))

    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            raise ValidationError("This rule creates a circular question dependency.")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, ()):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def create_group_from_legacy(target, user, *, purpose="visibility"):
    target_kw = (
        {"target_section": target}
        if isinstance(target, FormSection)
        else {
            (
                "target_required_question" if purpose == "required"
                else "target_validation_question" if purpose == "validation"
                else "target_question"
            ): target
        }
    )
    event_form = target.event_form if hasattr(target, "event_form") else target.section.event_form
    group, created = DisplayLogicGroup.objects.get_or_create(
        event_form=event_form,
        defaults={"created_by": user, "updated_by": user},
        **target_kw,
    )
    if created and purpose == "visibility" and target.condition_question_id and target.condition_value:
        DisplayLogicRule.objects.create(
            group=group,
            source_question=target.condition_question,
            operator=DisplayLogicRule.Operator.EQUALS,
            comparison_value=target.condition_value,
            display_order=1,
            created_by=user,
            updated_by=user,
        )
        target.condition_question = None
        target.condition_value = ""
        target.updated_by = user
        target.save(update_fields=[
            "condition_question", "condition_value", "updated_by", "updated_at"
        ])
    return group
