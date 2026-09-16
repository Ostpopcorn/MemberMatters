"""Which language an email renders in.

Member emails follow the EMAIL_LANGUAGE constance key. Admin emails, and member
emails pinned to English, never change. None of them may follow Django's
LANGUAGE_CODE, which a Swedish install sets to sv-se through MM_LANGUAGE_CODE.
"""

import pytest
from django.utils.translation import gettext

from services.email_i18n import ENGLISH
from services.emails import send_email_to_admin

pytestmark = pytest.mark.django_db

ENGLISH_SIGN_OFF = "Cheers,"
SWEDISH_SIGN_OFF = "Vänliga hälsningar,"
ADMIN_ADDRESS = "admin@example.com"


@pytest.fixture
def swedish_default_language(settings):
    """Django's default language, set the way a Swedish install sets it."""
    settings.LANGUAGE_CODE = "sv-se"
    # Without this the tests below would pass whether or not the default leaks.
    assert gettext(ENGLISH_SIGN_OFF) == SWEDISH_SIGN_OFF


def body_to(outbox, address):
    [message] = [m for m in outbox if m["To"] == address]
    return message["HtmlBody"]


SENDS = {
    "without_button": lambda user: user.email_notification("Subject", "Message"),
    "with_button": lambda user: user.email_link(
        "Subject", "Title", "Message", "https://example.com", "Button"
    ),
    "password_reset": lambda user: user.email_password_reset("https://example.com"),
    "welcome": lambda user: user.email_welcome(),
}


@pytest.mark.parametrize("send", SENDS.values(), ids=SENDS.keys())
@pytest.mark.override_config(EMAIL_LANGUAGE="sv-SE")
def test_member_emails_follow_the_site_language(member, outbox, send):
    send(member.user)

    body = body_to(outbox, member.user.email)
    assert SWEDISH_SIGN_OFF in body
    assert "Skickat av" in body
    assert '<html lang="sv-se">' in body


def test_member_emails_ignore_the_default_language(
    member, outbox, swedish_default_language
):
    member.user.email_notification("Subject", "Message")

    body = body_to(outbox, member.user.email)
    assert ENGLISH_SIGN_OFF in body
    assert SWEDISH_SIGN_OFF not in body


@pytest.mark.override_config(EMAIL_LANGUAGE="sv-SE", EMAIL_ADMIN=ADMIN_ADDRESS)
def test_admin_emails_stay_english(outbox, swedish_default_language):
    send_email_to_admin(
        "Subject", template_vars={"title": "Subject", "message": "Message"}
    )

    body = body_to(outbox, ADMIN_ADDRESS)
    assert ENGLISH_SIGN_OFF in body
    assert SWEDISH_SIGN_OFF not in body


@pytest.mark.override_config(EMAIL_LANGUAGE="sv-SE")
def test_member_emails_pinned_to_english_stay_english(
    member, outbox, swedish_default_language
):
    member.user.email_notification("Subject", "Message", language=ENGLISH)

    body = body_to(outbox, member.user.email)
    assert ENGLISH_SIGN_OFF in body
    assert SWEDISH_SIGN_OFF not in body
