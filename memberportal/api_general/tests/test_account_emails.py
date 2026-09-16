"""The account emails: verify your address, book an induction, reset a password.

Each goes out in the site's member email language. The English assertions pin
the copy as written in the code, which is what an install sends by default.
"""

import pytest
from constance import config

from api_general.models import EmailVerificationToken
from api_general.views import _send_register_emails
from tests.factories import ProfileFactory
from tests.helpers import subjects_to

pytestmark = pytest.mark.django_db

# UserFactory's default.
PASSWORD = "test-password"
ADMIN_ADDRESS = "admin@example.com"
SWEDISH = pytest.mark.override_config(EMAIL_LANGUAGE="sv-SE")


@pytest.fixture(autouse=True)
def _throttle_rates(enable_throttling):
    # Login and password reset are throttle-scoped, and a scoped view can't run
    # without its rate.
    pass


def email_to(outbox, profile, subject):
    [message] = [
        m for m in outbox if m["To"] == profile.user.email and m["Subject"] == subject
    ]
    return message["HtmlBody"]


def register(profile, django_capture_on_commit_callbacks):
    token = EmailVerificationToken.objects.create(user=profile.user)
    with django_capture_on_commit_callbacks(execute=True):
        _send_register_emails(profile.user, profile, token)
    return token


class TestVerifyEmail:
    def test_an_unverified_login_is_sent_a_verification_link(
        self, api_client, outbox, django_capture_on_commit_callbacks
    ):
        profile = ProfileFactory(user__email_verified=False)

        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                "/api/login/",
                {"email": profile.user.email, "password": PASSWORD},
                format="json",
            )

        assert response.status_code == 403
        token = EmailVerificationToken.objects.get(user=profile.user)
        body = email_to(outbox, profile, "Action Required: Verify Email")
        assert "Please verify your email address to activate your account." in body
        assert "Verify Now" in body
        assert str(token.verification_token) in body

    @SWEDISH
    def test_it_is_sent_in_the_site_language(self, member, outbox):
        member.user.email_verification("https://portal.example.org/verify")

        body = email_to(outbox, member, "Åtgärd krävs: verifiera din e-postadress")
        assert "Verifiera din e-postadress för att aktivera ditt konto." in body
        assert "Verifiera nu" in body


@pytest.mark.override_config(
    ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=False, EMAIL_ADMIN=ADMIN_ADDRESS
)
class TestRegisterEmails:
    def test_a_new_member_is_asked_to_verify_and_book_an_induction(
        self, member, outbox, django_capture_on_commit_callbacks
    ):
        token = register(member, django_capture_on_commit_callbacks)

        induction_subject = f"Action Required: {config.SITE_OWNER} New Member Signup"
        assert subjects_to(outbox, member) == [
            "Action Required: Verify Email",
            induction_subject,
        ]
        assert str(token.verification_token) in email_to(
            outbox, member, "Action Required: Verify Email"
        )
        body = email_to(outbox, member, induction_subject)
        assert "Next Step: Register for an Induction" in body
        assert "Hi Test, thanks for signing up!" in body
        assert "Register for Induction" in body

    @pytest.mark.override_config(
        ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=False,
        EMAIL_ADMIN=ADMIN_ADDRESS,
        EMAIL_LANGUAGE="sv-SE",
    )
    def test_they_are_sent_in_the_site_language(
        self, member, outbox, django_capture_on_commit_callbacks
    ):
        register(member, django_capture_on_commit_callbacks)

        induction_subject = (
            f"Åtgärd krävs: ny medlemsregistrering hos {config.SITE_OWNER}"
        )
        assert subjects_to(outbox, member) == [
            "Åtgärd krävs: verifiera din e-postadress",
            induction_subject,
        ]
        body = email_to(outbox, member, induction_subject)
        assert "Nästa steg: anmäl dig till en introduktion" in body
        assert "Hej Test, tack för att du registrerade dig!" in body
        assert "Anmäl dig till introduktion" in body

    @pytest.mark.override_config(
        ENABLE_STRIPE_MEMBERSHIP_PAYMENTS=False,
        EMAIL_ADMIN=ADMIN_ADDRESS,
        EMAIL_LANGUAGE="sv-SE",
    )
    def test_the_admin_notification_stays_english(
        self, member, outbox, django_capture_on_commit_callbacks
    ):
        register(member, django_capture_on_commit_callbacks)

        [admin_email] = [m for m in outbox if m["To"] == ADMIN_ADDRESS]
        assert admin_email["Subject"].startswith("A new member signed up!")
        assert "Cheers," in admin_email["HtmlBody"]


class TestPasswordReset:
    def request_reset(self, api_client, member, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                "/api/password/reset/", {"email": member.user.email}, format="json"
            )
        assert response.data == {"success": True}

    def test_a_reset_request_sends_the_reset_link(
        self, api_client, member, outbox, django_capture_on_commit_callbacks
    ):
        self.request_reset(api_client, member, django_capture_on_commit_callbacks)

        member.user.refresh_from_db()
        body = email_to(outbox, member, f"Reset your {config.SITE_OWNER} password")
        assert str(member.user.password_reset_key) in body
        assert "Reset Password" in body

    @SWEDISH
    def test_it_is_sent_in_the_site_language(
        self, api_client, member, outbox, django_capture_on_commit_callbacks
    ):
        self.request_reset(api_client, member, django_capture_on_commit_callbacks)

        body = email_to(
            outbox, member, f"Återställ ditt lösenord hos {config.SITE_OWNER}"
        )
        assert "Lösenordsåterställning" in body
        assert "Återställ lösenord" in body
