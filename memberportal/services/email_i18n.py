"""Which language an email is written in.

Every email renders under an explicit language rather than Django's active one.
LANGUAGE_CODE (MM_LANGUAGE_CODE) is the fallback for anything rendered outside a
translation.override, and on a non-English install it would otherwise leak into
admin emails, or into member emails before the site has opted in.
"""

from constance import config
from django.utils import translation

# The source language of every msgid. There is deliberately no English catalog,
# so rendering in it produces exactly the text written in the code.
ENGLISH = "en-AU"
ADMIN_EMAIL_LANGUAGE = ENGLISH


def member_email_language(user=None):
    """The language emails to this member are written in.

    Site-wide for now. Takes the recipient so that a per-member preference only
    has to change this function; None asks for the site default.
    """
    return config.EMAIL_LANGUAGE


def member_email_translation(user=None):
    return translation.override(member_email_language(user))
