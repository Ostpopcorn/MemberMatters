from constance import config
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from services.sanitize import clean_html

register = template.Library()


@register.filter
def sanitize_html(value):
    return mark_safe(clean_html(value))


@register.simple_tag
def site_link():
    """The footer's link to the portal, kept out of the translated sentence so a
    translation can't break the markup."""
    return format_html('<a href="{}">{}</a>', config.SITE_URL, config.SITE_NAME)
