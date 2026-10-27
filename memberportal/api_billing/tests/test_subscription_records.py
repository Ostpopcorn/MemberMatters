"""The member's own plan changes write a Subscription row as well as the Profile
columns: signing up, resuming and cancelling, by each path."""

from types import SimpleNamespace

import pytest

from api_billing.views import PaymentPlanSignup
from profile.models import Profile
from subscriptions.models import Subscription
from tests.factories import PaymentPlanFactory, ProfileFactory

from .conftest import SUBSCRIPTION_ID

pytestmark = pytest.mark.django_db


@pytest.fixture
def stripe_creates(monkeypatch):
    def create_subscription(self, request, plan, billing_method, *args):
        return SimpleNamespace(id="sub_new", status="active"), None

    monkeypatch.setattr(PaymentPlanSignup, "create_subscription", create_subscription)


@pytest.fixture
def stripe_modifies(monkeypatch):
    monkeypatch.setattr(
        "stripe.Subscription.modify",
        lambda subscription_id, cancel_at_period_end: SimpleNamespace(
            cancel_at_period_end=cancel_at_period_end
        ),
    )


def member(**columns):
    columns.setdefault("stripe_subscription_id", SUBSCRIPTION_ID)
    return ProfileFactory(membership_plan=PaymentPlanFactory(), **columns)


def post(api_client, profile, path):
    api_client.force_authenticate(user=profile.user)
    return api_client.post(path, format="json")


def current(profile):
    return Profile.objects.get(pk=profile.pk).current_subscription


def test_signing_up_starts_a_subscription(api_client, stripe_creates):
    plan = PaymentPlanFactory()
    profile = ProfileFactory()

    response = post(api_client, profile, f"/api/billing/plans/{plan.pk}/signup/")

    assert response.data["success"] is True
    started = current(profile)
    assert started.external_ref == "sub_new"
    assert started.plan == plan
    assert started.billing_method == "card"
    assert started.legacy_status == "active"
    assert started.started_at is not None


def test_resuming_without_a_subscription_starts_a_new_one(api_client, stripe_creates):
    profile = member(stripe_subscription_id=None, subscription_status="inactive")
    plan = profile.membership_plan
    old = current(profile)

    response = post(api_client, profile, "/api/billing/myplan/resume/")

    assert response.data["success"] is True
    started = current(profile)
    assert started.external_ref == "sub_new"
    assert started.plan == plan
    old.refresh_from_db()
    assert old.state == Subscription.State.CANCELLED


def test_resuming_a_cancelling_plan_reactivates_it(api_client, stripe_modifies):
    profile = member(subscription_status="cancelling")

    response = post(api_client, profile, "/api/billing/myplan/resume/")

    assert response.data["success"] is True
    assert current(profile).state == Subscription.State.ACTIVE


def test_cancelling_a_pending_signup_ends_it(api_client, stripe_api):
    profile = member(subscription_status="pending", billing_method="invoice")
    subscription = current(profile)

    response = post(api_client, profile, "/api/billing/myplan/cancel/")

    assert response.data["success"] is True
    assert current(profile) is None
    subscription.refresh_from_db()
    assert subscription.state == Subscription.State.CANCELLED


def test_cancelling_an_active_plan_marks_it_cancelling(api_client, stripe_modifies):
    profile = member(subscription_status="active")

    response = post(api_client, profile, "/api/billing/myplan/cancel/")

    assert response.data["success"] is True
    assert current(profile).state == Subscription.State.CANCELLING
