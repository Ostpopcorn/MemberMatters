"""The Stripe webhook's member emails, sent in the member email language.

test_stripe_webhook.py pins the English copy. Here each member email goes out
with EMAIL_LANGUAGE set to Swedish, and the admin alerts raised by the same
handlers are checked to stay English.
"""

from datetime import timedelta

import pytest
from django.utils import timezone, translation

from api_billing.stripe_utils import format_invoice_due_date
from api_billing.webhook_handlers import payment_failed_copy
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


# 2023-11-14 22:13 UTC and 2100-01-01 00:00 UTC. Dates are asserted with the
# site timezone pinned to UTC, so they don't move with MM_TIME_ZONE.
PAST = 1700000000
FUTURE = 4102444800
PAY_URL = "https://invoice.stripe.com/i/test"


@pytest.fixture
def utc(settings):
    settings.TIME_ZONE = "UTC"


class TestInvoiceDueDate:
    def test_it_names_the_month_in_the_active_language(self, utc):
        with translation.override("en-AU"):
            assert format_invoice_due_date({"due_date": PAST}) == "14 November 2023"
        with translation.override("sv-SE"):
            assert format_invoice_due_date({"due_date": PAST}) == "14 november 2023"


class TestPaymentFailedCopy:
    def overdue(self):
        return payment_failed_copy(
            ProfileFactory.build(billing_method="invoice"),
            {
                "amount_due": 5500,
                "currency": "aud",
                "due_date": PAST,
                "hosted_invoice_url": PAY_URL,
            },
        )

    def test_the_english_sentences_join_as_before(self, utc):
        _, message = self.overdue()

        assert message == (
            "A payment towards your membership invoice for 55.00 AUD didn't go "
            "through, and the invoice is now overdue. It was due on 14 November "
            "2023. Please pay it to keep your membership active. If you have "
            f"further questions, contact us. You can pay it here: {PAY_URL}"
        )

    @swedish()
    def test_an_overdue_invoice(self, utc):
        subject, message = self.overdue()

        assert subject == "Din medlemsfaktura är förfallen"
        assert message == (
            "En betalning av din medlemsfaktura på 55.00 AUD gick inte igenom, och "
            "fakturan är nu förfallen. Förfallodagen var 14 november 2023. Betala "
            "den för att behålla ditt medlemskap. Om du har fler frågor, kontakta "
            f"oss. Du kan betala den här: {PAY_URL}"
        )

    @swedish()
    def test_an_outstanding_invoice_without_a_link(self, utc):
        subject, message = payment_failed_copy(
            ProfileFactory.build(billing_method="invoice"),
            {"amount_due": 5500, "currency": "aud", "due_date": FUTURE},
        )

        assert subject == "Betalningen av din medlemsfaktura gick inte igenom"
        assert message == (
            "En betalning av din medlemsfaktura på 55.00 AUD gick inte igenom, så "
            "fakturan är fortfarande obetald. Förfallodagen är 1 januari 2100. "
            "Betala den före förfallodagen för att behålla ditt medlemskap."
        )

    @swedish()
    def test_a_card_payment_that_will_be_retried(self):
        subject, message = payment_failed_copy(
            ProfileFactory.build(billing_method="card"),
            {"amount_due": 5500, "currency": "aud", "next_payment_attempt": FUTURE},
        )

        assert subject == "Din medlemsbetalning misslyckades"
        assert "Vi försöker igen automatiskt" in message

    @swedish()
    def test_a_card_payment_out_of_retries(self):
        subject, message = payment_failed_copy(
            ProfileFactory.build(billing_method="card"),
            {"amount_due": 5500, "currency": "aud", "next_payment_attempt": None},
        )

        assert subject == "Åtgärd krävs: din medlemsbetalning misslyckades"
        assert "vårt sista automatiska försök" in message
        assert message.endswith("Om du har fler frågor, kontakta oss.")

    @swedish()
    def test_the_webhook_sends_it(
        self, send_webhook, subscribed_member, outbox, invoice_schema
    ):
        send_webhook(
            build_event(
                "invoice.payment_failed",
                build_invoice(invoice_schema, status="open", amount_due=5500),
            )
        )

        [message] = mail_to(outbox, subscribed_member)
        assert (
            message["Subject"] == "Betalningen av din medlemsfaktura gick inte igenom"
        )
