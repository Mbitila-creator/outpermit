import ast
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

QUESTION_NAME = re.compile(r"q(?P<id>\d+)$")
ALLOWED_FUNCTIONS = {"COUNT", "IF", "SUM"}


class ExpressionError(ValueError):
    pass


def _number(value):
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExpressionError("A referenced answer is not numeric.") from exc


def question_reference_ids(expression):
    try:
        tree = ast.parse(expression or "", mode="eval")
    except SyntaxError as exc:
        raise ExpressionError("Enter a valid expression.") from exc
    references = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            match = QUESTION_NAME.fullmatch(node.id)
            if not match and node.id.upper() not in ALLOWED_FUNCTIONS:
                raise ExpressionError(f"Unknown reference: {node.id}.")
            if match:
                references.add(int(match.group("id")))
    return references


def evaluate_expression(expression, answers):
    try:
        tree = ast.parse(expression or "", mode="eval")
    except SyntaxError as exc:
        raise ExpressionError("Enter a valid expression.") from exc

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, bool, str)):
            if isinstance(node.value, bool) or isinstance(node.value, str):
                return node.value
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            match = QUESTION_NAME.fullmatch(node.id)
            if not match:
                raise ExpressionError(f"Unknown reference: {node.id}.")
            question_id = int(match.group("id"))
            if question_id not in answers or answers[question_id] in (None, "", []):
                raise ExpressionError(f"Question q{question_id} has no answer.")
            return answers[question_id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = node.func.id.upper()
            if node.keywords or function not in ALLOWED_FUNCTIONS:
                raise ExpressionError("This function is not supported.")
            if function == "IF":
                if len(node.args) != 3:
                    raise ExpressionError("IF requires a condition, true value, and false value.")
                return evaluate(node.args[1]) if bool(evaluate(node.args[0])) else evaluate(node.args[2])
            values = []
            for argument in node.args:
                if isinstance(argument, ast.Name) and QUESTION_NAME.fullmatch(argument.id):
                    values.append(answers.get(int(argument.id[1:]), ""))
                else:
                    values.append(evaluate(argument))
            if function == "SUM":
                flattened = []
                for value in values:
                    flattened.extend(value if isinstance(value, (list, tuple, set)) else [value])
                return sum((_number(value) for value in flattened if value not in (None, "")), Decimal("0"))
            return Decimal(sum(
                len(value) if isinstance(value, (list, tuple, set))
                else int(value not in (None, ""))
                for value in values
            ))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            value = evaluate(node.operand)
            if isinstance(node.op, ast.Not):
                return not bool(value)
            value = _number(value)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
            left, right = _number(evaluate(node.left)), _number(evaluate(node.right))
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
            return left % right
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [bool(evaluate(item)) for item in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            op = node.ops[0]
            if isinstance(op, ast.Eq): return left == right
            if isinstance(op, ast.NotEq): return left != right
            left, right = _number(left), _number(right)
            if isinstance(op, ast.Lt): return left < right
            if isinstance(op, ast.LtE): return left <= right
            if isinstance(op, ast.Gt): return left > right
            if isinstance(op, ast.GtE): return left >= right
        raise ExpressionError("This expression contains an unsupported operation.")

    try:
        return evaluate(tree)
    except ArithmeticError as exc:
        raise ExpressionError("The expression could not be calculated.") from exc


def validate_question_expression(expression, question, field_name):
    if not expression:
        return
    try:
        references = question_reference_ids(expression)
    except ExpressionError as exc:
        raise ValidationError({field_name: str(exc)}) from exc
    if question.pk in references:
        raise ValidationError({field_name: "A question cannot reference itself."})
    if question.section_id:
        valid_ids = set(question.section.event_form.sections.values_list("questions__id", flat=True))
        invalid = references - valid_ids
        if invalid:
            raise ValidationError({field_name: f"Unknown question reference(s): {sorted(invalid)}."})
    if field_name == "calculation_expression" and question.pk and question.section_id:
        dependencies = {}
        queryset = question.section.event_form.sections.values_list(
            "questions__id", "questions__calculation_expression"
        )
        for question_id, formula in queryset:
            if not question_id or not formula:
                continue
            dependencies[question_id] = question_reference_ids(formula)
        dependencies[question.pk] = references

        def reaches_origin(question_id, trail):
            if question_id == question.pk:
                return True
            if question_id in trail:
                return False
            return any(
                reaches_origin(dependency, trail | {question_id})
                for dependency in dependencies.get(question_id, set())
            )

        if any(reaches_origin(item, set()) for item in references):
            raise ValidationError({field_name: "This calculation would create a circular dependency."})
