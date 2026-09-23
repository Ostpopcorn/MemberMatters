"""The email a member gets after adding a payment card, sent in the member
email language."""

import pytest

from tests.factories import ProfileFactory
from tests.helpers import subjects_to

pytestmark = pytest.mark.django_db


@pytest.fixture
def add_card(api_client, monkeypatch):
    monkeypatch.setattr("stripe.PaymentMethod.attach", lambda *a, **kw: {})
    monkeypatch.setattr(
        "stripe.PaymentMethod.retrieve",
        lambda _id: {"card": {"last4": "4242", "exp_month": 3, "exp_year": 2030}},
    )
    monkeypatch.setattr("stripe.Customer.modify", lambda *a, **kw: {})

    def _add():
        profile = ProfileFactory(stripe_customer_id="cus_test")
        api_client.force_authenticate(user=profile.user)
        response = api_client.post(
            "/api/billing/card/", {"paymentMethodId": "pm_test"}, format="json"
        )
        assert response.status_code == 200
        return profile

    return _add


@pytest.mark.override_config(SITE_OWNER="Makerspace")
def test_english(add_card, outbox):
    profile = add_card()

    assert subjects_to(outbox, profile) == [
        "You just added a payment card to your Makerspace account."
    ]


@pytest.mark.override_config(
    SITE_OWNER="Makerspace", SITE_NAME="Medlemsportalen", EMAIL_LANGUAGE="sv-SE"
)
def test_swedish(add_card, outbox):
    profile = add_card()

    [message] = outbox
    assert message["Subject"] == (
        "Du har lagt till ett betalkort på ditt konto hos Makerspace."
    )
    assert "ta bort kortet när som helst via Medlemsportalen." in message["HtmlBody"]
