"""The Stripe webhook's member emails, sent in the member email language.

test_stripe_webhook.py pins the English copy. Here each member email goes out
with EMAIL_LANGUAGE set to Swedish, and the admin alerts raised by the same
handlers are checked to stay English.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from tests.factories import PaymentPlanFactory, ProfileFactory

from .conftest import CUSTOMER_ID, SUBSCRIPTION_ID, build_event, build_invoice

pytestmark = pytest.mark.django_db

# Signup requirements off, as in test_stripe_webhook.py, with Swedish member
# emails on top.
SWEDISH = {
    "TERMS_ACCEPTANCE_CARDS": "[]",
    "ENABLE_STRIPE_MEMBERSHIP_PAYMENTS": True,
    "MOODLE_INDUCTION_ENABLED": False,
    "CANVAS_INDUCTION_ENABLED": False,
    "REQUIRE_ACCESS_CARD": False,
    "EMAIL_LANGUAGE": "sv-SE",
}


def swedish(**overrides):
    return pytest.mark.override_config(**{**SWEDISH, **overrides})


def mail_to(outbox, profile):
    return [m for m in outbox if m["To"] == profile.user.email]


@pytest.fixture
def send_webhook(post_webhook, stripe_event, django_capture_on_commit_callbacks):
    def _send(event):
        stripe_event(event=event)
        with django_capture_on_commit_callbacks(execute=True):
            assert post_webhook().status_code == 200

    return _send


class TestInvoicePaid:
    @pytest.fixture
    def renewing_member(self, db):
        return ProfileFactory(
            active=True,
            subscription_active=True,
            billing_method="invoice",
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
            subscription_first_created=timezone.now() - timedelta(days=365),
        )

    @swedish()
    def test_a_renewal_receipt(self, send_webhook, renewing_member, outbox):
        send_webhook(
            build_event("invoice.paid", build_invoice(amount_paid=5500, currency="aud"))
        )

        [message] = mail_to(outbox, renewing_member)
        assert message["Subject"] == "Ditt medlemskap har förnyats"
        assert (
            "Tack – vi har tagit emot din medlemsbetalning på 55.00 AUD och ditt "
            "medlemskap fortsätter som vanligt." in message["HtmlBody"]
        )

    @swedish()
    def test_a_leaving_members_final_receipt(
        self, send_webhook, renewing_member, outbox
    ):
        renewing_member.subscription_status = "cancelling"
        renewing_member.save(update_fields=["subscription_status"])

        send_webhook(build_event("invoice.paid", build_invoice()))

        [message] = mail_to(outbox, renewing_member)
        assert message["Subject"] == "Din sista medlemsbetalning"
        assert "din nuvarande faktureringsperiod" in message["HtmlBody"]

    @swedish()
    def test_an_off_cycle_receipt_with_no_amount(
        self, send_webhook, renewing_member, outbox
    ):
        send_webhook(
            build_event(
                "invoice.paid", build_invoice(billing_reason="subscription_create")
            )
        )

        [message] = mail_to(outbox, renewing_member)
        assert message["Subject"] == "Vi har tagit emot din medlemsbetalning"
        assert "din medlemsbetalning på din medlemsavgift." in message["HtmlBody"]

    @swedish()
    def test_a_payment_that_activates_the_member(
        self, send_webhook, subscribed_member, outbox
    ):
        send_webhook(build_event("invoice.paid", build_invoice()))

        subjects = [m["Subject"] for m in mail_to(outbox, subscribed_member)]
        assert subjects[0] == "Din betalning har genomförts."

    @swedish(MOODLE_INDUCTION_ENABLED=True, EMAIL_ADMIN="admin@example.com")
    def test_a_payment_with_steps_left_and_its_admin_alert(self, send_webhook, outbox):
        profile = ProfileFactory(
            inactive=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )

        send_webhook(build_event("invoice.paid", build_invoice()))

        [message] = mail_to(outbox, profile)
        assert message["Subject"] == "Vi har tagit emot din betalning – fler steg krävs"
        assert "slutför introduktionssteget" in message["HtmlBody"]
        [alert] = [m for m in outbox if m["To"] == "admin@example.com"]
        assert alert["Subject"] == "Action Required: Verify returning member"
        assert "Cheers," in alert["HtmlBody"]
