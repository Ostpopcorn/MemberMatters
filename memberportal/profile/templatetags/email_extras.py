from django import template
from django.utils.safestring import mark_safe

from services.sanitize import clean_html

register = template.Library()


@register.filter
def sanitize_html(value):
    return mark_safe(clean_html(value))
