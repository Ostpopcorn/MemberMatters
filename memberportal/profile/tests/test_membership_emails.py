"""The membership emails: application submitted, welcome, and site access
enabled or disabled.

Each goes out in the site's member email language. The English assertions pin
the copy as written in the code, which is what an install sends by default.
"""

import pytest
from constance import config

from tests.helpers import subjects_to

pytestmark = pytest.mark.django_db

ADMIN_ADDRESS = "admin@example.com"
SWEDISH = pytest.mark.override_config(EMAIL_LANGUAGE="sv-SE")


def email_to(outbox, profile):
    [message] = [m for m in outbox if m["To"] == profile.user.email]
    return message


# (send, English subject, English body, Swedish subject, Swedish body).
# {owner} is SITE_OWNER; the member's first name is the factory's "Test".
ACCESS_EMAILS = {
    "enabled": (
        lambda user: user.email_enable_member_access(),
        "Your {owner} site access has been enabled.",
        "Great news Test, your {owner} site access has been enabled.",
        "Din åtkomst till {owner} har aktiverats.",
        "Goda nyheter, Test! Din åtkomst till {owner} har aktiverats.",
    ),
    "disabled": (
        lambda user: user.email_disable_member_access(),
        "Your {owner} site access has been disabled.",
        "Your access to {owner} has been disabled. If this is unexpected, please "
        "let us know.",
        "Din åtkomst till {owner} har inaktiverats.",
        "Din åtkomst till {owner} har inaktiverats. Hör av dig till oss om det "
        "kommer oväntat.",
    ),
    "subscription_ended": (
        lambda user: user.email_subscription_ended(),
        "Your {owner} site access has been disabled.",
        "Your access to {owner} has been disabled because your membership "
        "subscription has ended. This is usually due to a failed membership "
        "payment. If this is unexpected, please let us know.",
        "Din åtkomst till {owner} har inaktiverats.",
        "Din åtkomst till {owner} har inaktiverats eftersom din "
        "medlemsprenumeration har upphört. Det beror oftast på en misslyckad "
        "medlemsbetalning. Hör av dig till oss om det kommer oväntat.",
    ),
}


class TestAccessEmails:
    @pytest.mark.parametrize(
        "send, subject, body, _sv_subject, _sv_body",
        ACCESS_EMAILS.values(),
        ids=ACCESS_EMAILS.keys(),
    )
    def test_english(self, member, outbox, send, subject, body, _sv_subject, _sv_body):
        send(member.user)

        message = email_to(outbox, member)
        assert message["Subject"] == subject.format(owner=config.SITE_OWNER)
        assert body.format(owner=config.SITE_OWNER) in message["HtmlBody"]

    @SWEDISH
    @pytest.mark.parametrize(
        "send, _subject, _body, sv_subject, sv_body",
        ACCESS_EMAILS.values(),
        ids=ACCESS_EMAILS.keys(),
    )
    def test_swedish(self, member, outbox, send, _subject, _body, sv_subject, sv_body):
        send(member.user)

        message = email_to(outbox, member)
        assert message["Subject"] == sv_subject.format(owner=config.SITE_OWNER)
        assert sv_body.format(owner=config.SITE_OWNER) in message["HtmlBody"]


@pytest.mark.override_config(
    ENABLE_MEMBERSHIP_APPLICATION_USER_EMAIL=True, EMAIL_ADMIN=ADMIN_ADDRESS
)
class TestApplicationEmail:
    def test_english(self, member, outbox):
        member.user.email_membership_application()

        message = email_to(outbox, member)
        assert message["Subject"] == "Your membership application has been submitted"
        body = message["HtmlBody"]
        assert "Thanks for submitting your membership application!" in body

    @pytest.mark.override_config(
        ENABLE_MEMBERSHIP_APPLICATION_USER_EMAIL=True,
        EMAIL_ADMIN=ADMIN_ADDRESS,
        EMAIL_LANGUAGE="sv-SE",
    )
    def test_swedish_with_the_admin_copy_in_english(self, member, outbox):
        member.user.email_membership_application()

        message = email_to(outbox, member)
        assert message["Subject"] == "Din medlemsansökan har skickats in"
        body = message["HtmlBody"]
        assert "Tack för att du skickade in din medlemsansökan!" in body
        [admin_email] = [m for m in outbox if m["To"] == ADMIN_ADDRESS]
        assert admin_email["Subject"].startswith("A new person just completed signup")
        assert "Cheers," in admin_email["HtmlBody"]


class TestWelcomeEmail:
    def test_english(self, member, outbox):
        member.user.email_welcome()

        assert subjects_to(outbox, member) == [f"Welcome to {config.SITE_OWNER}"]

    @SWEDISH
    def test_swedish(self, member, outbox):
        member.user.email_welcome()

        message = email_to(outbox, member)
        assert message["Subject"] == f"Välkommen till {config.SITE_OWNER}"
        body = message["HtmlBody"]
        assert "Tack för att du har genomfört din introduktion" in body

    @SWEDISH
    def test_the_admin_preview_shows_the_site_language(self, admin_client):
        response = admin_client.get("/api/admin/signup-preview/")

        html = response.data["welcomeEmailHtml"]
        assert f"Välkommen till {config.SITE_OWNER}" in html
        assert "Vänliga hälsningar," in html
