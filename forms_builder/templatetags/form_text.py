import re

from django import template
from django.utils.html import conditional_escape, linebreaks
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter
def simple_rich_text(value):
    """Render paragraphs and safe **bold** spans from administrator text."""
    escaped_value = str(conditional_escape(value or ""))
    bold_value = re.sub(
        r"\*\*(.+?)\*\*",
        r"<strong>\1</strong>",
        escaped_value,
    )
    return mark_safe(linebreaks(bold_value, autoescape=False))

