"""The cancellation and resume emails: a member resumes or cancels their plan,
or an admin cancels it.

Each goes out in the site's member email language, and the admin notice sent
with it stays English.
"""

from types import SimpleNamespace

import pytest

from tests.factories import PaymentPlanFactory, ProfileFactory
from tests.helpers import subjects_to

from .conftest import SUBSCRIPTION_ID

pytestmark = pytest.mark.django_db

ADMIN_ADDRESS = "admin@example.com"


def member_posts(path):
    def send(client, profile):
        client.force_authenticate(user=profile.user)
        return client.post(path)

    return send


def admin_cancels(timing):
    def send(client, profile):
        client.force_authenticate(user=ProfileFactory(user__staff_user=True).user)
        return client.post(
            f"/api/admin/members/{profile.user.id}/cancel-membership/",
            {"timing": timing},
            format="json",
        )

    return send


# (subscription status, send, English subject, Swedish subject, Swedish phrase)
EMAILS = {
    "member_resumes": (
        "cancelling",
        member_posts("/api/billing/myplan/resume/"),
        "Your membership has been resumed",
        "Ditt medlemskap har återupptagits",
        "fortsätter att faktureras som vanligt",
    ),
    "member_cancels_a_pending_signup": (
        "pending",
        member_posts("/api/billing/myplan/cancel/"),
        "Your pending membership signup has been cancelled.",
        "Din påbörjade medlemsregistrering har avbrutits.",
        "Ingen betalning har dragits.",
    ),
    "member_cancels_at_period_end": (
        "active",
        member_posts("/api/billing/myplan/cancel/"),
        "You've requested to cancel your membership plan.",
        "Du har begärt att säga upp ditt medlemskap.",
        "avslutas automatiskt",
    ),
    "admin_cancels_at_period_end": (
        "active",
        admin_cancels("at_period_end"),
        "Your membership cancellation is scheduled",
        "Uppsägningen av ditt medlemskap är schemalagd",
        "Din åtkomst gäller fram till dess.",
    ),
    "admin_cancels_immediately": (
        "active",
        admin_cancels("immediately"),
        "Your membership has been cancelled",
        "Ditt medlemskap har avslutats",
        "med omedelbar verkan",
    ),
}


@pytest.fixture
def send_email(api_client, stripe_api, monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr(
        "stripe.Subscription.modify",
        lambda subscription_id, cancel_at_period_end: SimpleNamespace(
            cancel_at_period_end=cancel_at_period_end
        ),
    )

    def _send(status, send):
        profile = ProfileFactory(
            subscription_status=status,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        with django_capture_on_commit_callbacks(execute=True):
            assert send(api_client, profile).data["success"] is True
        return profile

    return _send


@pytest.mark.override_config(EMAIL_ADMIN=ADMIN_ADDRESS)
@pytest.mark.parametrize(
    "status, send, subject, _sv_subject, _sv_phrase",
    EMAILS.values(),
    ids=EMAILS.keys(),
)
def test_english(send_email, outbox, status, send, subject, _sv_subject, _sv_phrase):
    profile = send_email(status, send)

    assert subject in subjects_to(outbox, profile)


@pytest.mark.override_config(EMAIL_ADMIN=ADMIN_ADDRESS, EMAIL_LANGUAGE="sv-SE")
@pytest.mark.parametrize(
    "status, send, _subject, sv_subject, sv_phrase",
    EMAILS.values(),
    ids=EMAILS.keys(),
)
def test_swedish_with_the_admin_notice_in_english(
    send_email, outbox, status, send, _subject, sv_subject, sv_phrase
):
    profile = send_email(status, send)

    [message] = [
        m
        for m in outbox
        if m["To"] == profile.user.email and m["Subject"] == sv_subject
    ]
    assert sv_phrase in message["HtmlBody"]
    admin_emails = [m for m in outbox if m["To"] == ADMIN_ADDRESS]
    assert admin_emails
    assert all("Cheers," in m["HtmlBody"] for m in admin_emails)
