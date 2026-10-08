"""Changing a payment plan's price and moving its subscriptions across.

Stripe is replaced by FakeStripe, an in-memory model of the prices and
subscriptions involved, rather than per-call stubs. The behaviour under test
depends on Stripe's state between calls: a resumed run must find only the
subscriptions an earlier run didn't move, and a sweep must find a
subscription that appeared mid-run.

The Celery task runs eagerly (settings_test), and is queued with on_commit,
so API tests that need the run to happen wrap the request in
django_capture_on_commit_callbacks(execute=True).
"""

import time
from datetime import timedelta

import pytest
import stripe
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from api_billing.models import PlanPriceChange
from api_billing.price_change import (
    CONSECUTIVE_FAILURE_LIMIT,
    run_price_change,
)
from profile.models import UserEventLog
from tests.factories import MemberTierFactory, PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db

Status = PlanPriceChange.Status

OLD_PRICE = "price_old"
PRODUCT = "prod_membership"


class FakeStripe:
    """Just enough of Stripe's Price and Subscription API for a price change.

    `fail` maps (method, object id) — or (method, None) for any id — to a list
    of exceptions raised one per call before the call is allowed to succeed.
    """

    def __init__(self):
        self.prices = {}
        self.subscriptions = {}
        self.calls = []
        self.fail = {}
        self.page_size = 100
        self.on_modify = None
        self._created_by_key = {}

    def add_price(self, price_id=OLD_PRICE, unit_amount=2000, **extra):
        self.prices[price_id] = {
            "id": price_id,
            "object": "price",
            "product": PRODUCT,
            "currency": "aud",
            "unit_amount": unit_amount,
            "active": True,
            "recurring": {"interval": "month", "interval_count": 1},
            "tax_behavior": None,
            **extra,
        }

    def add_subscription(self, sub_id, customer, price_id=OLD_PRICE, status="active"):
        self.subscriptions[sub_id] = {
            "id": sub_id,
            "object": "subscription",
            "customer": customer,
            "status": status,
            "items": {
                "object": "list",
                "data": [{"id": f"si_{sub_id}", "price": {"id": price_id}}],
            },
        }

    def price_of(self, sub_id):
        return self.subscriptions[sub_id]["items"]["data"][0]["price"]["id"]

    def modify_calls(self):
        return [
            kwargs for method, kwargs in self.calls if method == "Subscription.modify"
        ]

    def _call(self, method, object_id, kwargs):
        self.calls.append((method, {"id": object_id, **kwargs}))
        for key in ((method, object_id), (method, None)):
            queue = self.fail.get(key)
            if queue:
                raise queue.pop(0)

    @staticmethod
    def _obj(data):
        return stripe.StripeObject.construct_from(data, "sk_test")

    # --- Price

    def price_retrieve(self, price_id, **kwargs):
        self._call("Price.retrieve", price_id, kwargs)
        return self._obj(self.prices[price_id])

    def price_create(self, **kwargs):
        self._call("Price.create", None, kwargs)
        key = kwargs.pop("idempotency_key", None)
        if key in self._created_by_key:
            return self._obj(self.prices[self._created_by_key[key]])
        price_id = f"price_new{len(self.prices)}"
        self.prices[price_id] = {
            "id": price_id,
            "object": "price",
            "active": True,
            **kwargs,
        }
        self._created_by_key[key] = price_id
        return self._obj(self.prices[price_id])

    def price_modify(self, price_id, **kwargs):
        self._call("Price.modify", price_id, kwargs)
        kwargs.pop("idempotency_key", None)
        self.prices[price_id].update(kwargs)
        return self._obj(self.prices[price_id])

    # --- Subscription

    def subscription_list(self, **kwargs):
        self._call("Subscription.list", None, kwargs)
        matching = sorted(
            (
                s
                for s in self.subscriptions.values()
                if any(i["price"]["id"] == kwargs["price"] for i in s["items"]["data"])
                and s["status"] != "canceled"
            ),
            key=lambda s: s["id"],
        )
        after = kwargs.get("starting_after")
        if after:
            matching = [s for s in matching if s["id"] > after]
        page = matching[: min(kwargs.get("limit", 10), self.page_size)]
        return self._obj(
            {
                "object": "list",
                "data": page,
                "has_more": len(matching) > len(page),
            }
        )

    def subscription_modify(self, sub_id, **kwargs):
        self._call("Subscription.modify", sub_id, kwargs)
        subscription = self.subscriptions[sub_id]
        for change in kwargs["items"]:
            for item in subscription["items"]["data"]:
                if item["id"] == change["id"]:
                    item["price"] = {"id": change["price"]}
        if self.on_modify:
            self.on_modify(sub_id)
        return self._obj(subscription)


@pytest.fixture
def fake_stripe(monkeypatch):
    fake = FakeStripe()
    for target, method in (
        ("Price.retrieve", fake.price_retrieve),
        ("Price.create", fake.price_create),
        ("Price.modify", fake.price_modify),
        ("Subscription.list", fake.subscription_list),
        ("Subscription.modify", fake.subscription_modify),
    ):
        cls, name = target.split(".")
        monkeypatch.setattr(f"stripe.{cls}.{name}", method)
    return fake


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Record retry backoff instead of waiting it out."""
    recorded = []
    monkeypatch.setattr(time, "sleep", recorded.append)
    return recorded


@pytest.fixture
def plan(fake_stripe):
    fake_stripe.add_price(OLD_PRICE, unit_amount=2000)
    return PaymentPlanFactory(
        name="Standard",
        stripe_id=OLD_PRICE,
        cost=2000,
        member_tier=MemberTierFactory(stripe_id=PRODUCT),
    )


def subscribe(fake_stripe, plan, n, **profile_fields):
    sub_id = f"sub_{n:03d}"
    customer = f"cus_{n:03d}"
    fake_stripe.add_subscription(sub_id, customer, price_id=plan.stripe_id)
    return ProfileFactory(
        active=True,
        subscription_active=True,
        membership_plan=plan,
        stripe_customer_id=customer,
        stripe_subscription_id=sub_id,
        **profile_fields,
    )


@pytest.fixture
def members(fake_stripe, plan):
    return [subscribe(fake_stripe, plan, n) for n in range(3)]


def make_job(plan, fake_stripe, new_cost=2500, **fields):
    """A price change as start_price_change leaves it, without the request."""
    fake_stripe.add_price("price_new", unit_amount=new_cost)
    job = PlanPriceChange.objects.create(
        plan=plan,
        old_price_id=OLD_PRICE,
        new_price_id="price_new",
        old_cost=2000,
        new_cost=new_cost,
        currency="aud",
        **fields,
    )
    plan.stripe_id = "price_new"
    plan.cost = new_cost
    plan.save()
    return job


def start(admin_client, plan, cost=2500):
    return admin_client.post(
        reverse("PlanPriceChanges", args=[plan.pk]), {"cost": cost}, format="json"
    )


def server_error():
    return stripe.error.APIError("Server error", http_status=500)


def rejected(message="This subscription is managed by a schedule."):
    return stripe.error.InvalidRequestError(message, param="items", http_status=400)


# --- Starting a price change -------------------------------------------------


class TestStart:
    def test_creates_a_matching_price_and_points_the_plan_at_it(
        self, admin_client, fake_stripe, plan, members
    ):
        fake_stripe.prices[OLD_PRICE]["tax_behavior"] = "inclusive"

        response = start(admin_client, plan, cost=2500)

        assert response.status_code == 202
        job = PlanPriceChange.objects.get()
        new_price = fake_stripe.prices[job.new_price_id]
        assert new_price["unit_amount"] == 2500
        assert new_price["product"] == PRODUCT
        assert new_price["currency"] == "aud"
        assert new_price["recurring"] == {"interval": "month", "interval_count": 1}
        assert new_price["tax_behavior"] == "inclusive"
        assert new_price["metadata"]["replaces_price"] == OLD_PRICE

        plan.refresh_from_db()
        assert plan.stripe_id == job.new_price_id
        assert plan.cost == 2500
        assert (job.old_price_id, job.old_cost, job.new_cost) == (OLD_PRICE, 2000, 2500)
        assert response.data["priceChange"]["id"] == job.pk

    def test_moves_every_subscription_once_the_request_commits(
        self,
        admin_client,
        fake_stripe,
        plan,
        members,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            start(admin_client, plan)

        job = PlanPriceChange.objects.get()
        assert job.status == Status.COMPLETED
        assert (job.migrated_count, job.remaining_count, job.failures) == (3, 0, [])
        for member in members:
            assert (
                fake_stripe.price_of(member.stripe_subscription_id) == job.new_price_id
            )
        # No mid-period charge or credit: the new price applies from renewal.
        assert {c["proration_behavior"] for c in fake_stripe.modify_calls()} == {"none"}
        assert fake_stripe.prices[OLD_PRICE]["active"] is False

    def test_logs_the_change_on_each_member_and_emails_the_admins(
        self,
        admin_client,
        admin_member,
        fake_stripe,
        plan,
        members,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            start(admin_client, plan)

        for member in members:
            log = UserEventLog.objects.get(user=member.user, logtype="stripe")
            assert "20.00 AUD to 25.00 AUD" in log.description
        assert UserEventLog.objects.filter(
            user=admin_member.user, logtype="admin", description__contains="Standard"
        ).exists()
        assert [m["Subject"] for m in outbox] == [
            "Price change for Standard (20.00 AUD -> 25.00 AUD) completed"
        ]

    def test_a_create_price_timeout_is_retried_with_the_same_idempotency_key(
        self, admin_client, fake_stripe, plan
    ):
        fake_stripe.fail[("Price.create", None)] = [
            stripe.error.APIConnectionError("timeout", should_retry=True)
        ]

        assert start(admin_client, plan).status_code == 202

        keys = [
            k["idempotency_key"] for m, k in fake_stripe.calls if m == "Price.create"
        ]
        assert len(keys) == 2 and keys[0] == keys[1]
        assert PlanPriceChange.objects.count() == 1

    def test_stripe_failing_throughout_leaves_the_plan_untouched(
        self, admin_client, fake_stripe, plan
    ):
        fake_stripe.fail[("Price.create", None)] = [server_error() for _ in range(5)]

        response = start(admin_client, plan)

        assert response.status_code == 503
        assert response.data["message"] == "billing.stripeError"
        plan.refresh_from_db()
        assert (plan.stripe_id, plan.cost) == (OLD_PRICE, 2000)
        assert not PlanPriceChange.objects.exists()

    def test_refuses_the_price_the_plan_already_has(self, admin_client, plan):
        response = start(admin_client, plan, cost=2000)

        assert response.status_code == 400
        assert response.data["message"] == "paymentPlans.priceUnchanged"

    def test_compares_against_stripe_not_a_stale_plan_row(
        self, admin_client, fake_stripe, plan
    ):
        """The old PUT let `cost` drift from Stripe. Setting the plan to what
        it displays must still fix what members are actually billed."""
        plan.cost = 2500
        plan.save()

        assert start(admin_client, plan, cost=2500).status_code == 202

    def test_refuses_a_price_it_cannot_copy(self, admin_client, fake_stripe, plan):
        fake_stripe.prices[OLD_PRICE]["recurring"] = None

        response = start(admin_client, plan)

        assert response.status_code == 400
        assert response.data["message"] == "paymentPlans.priceNotSupported"

    @pytest.mark.parametrize(
        "cost", [0, -100, "2500", 25.5, True, None, 100_000_000], ids=repr
    )
    def test_refuses_an_invalid_cost(self, admin_client, fake_stripe, plan, cost):
        response = start(admin_client, plan, cost=cost)

        assert response.status_code == 400
        assert response.data["message"] == "paymentPlans.invalidCost"
        assert fake_stripe.calls == []

    def test_refuses_while_an_earlier_change_is_unfinished(
        self, admin_client, fake_stripe, plan
    ):
        earlier = make_job(plan, fake_stripe, status=Status.PARTIAL)

        response = start(admin_client, plan, cost=3000)

        assert response.status_code == 409
        assert response.data["priceChange"]["id"] == earlier.pk
        assert PlanPriceChange.objects.count() == 1

    def test_allows_a_new_change_once_the_earlier_one_completed(
        self, admin_client, fake_stripe, plan
    ):
        make_job(plan, fake_stripe, status=Status.COMPLETED)

        assert start(admin_client, plan, cost=3000).status_code == 202

    @pytest.mark.override_config(ENABLE_STRIPE=False)
    def test_refuses_when_stripe_is_disabled(self, admin_client, fake_stripe, plan):
        response = start(admin_client, plan)

        assert response.status_code == 503
        assert fake_stripe.calls == []

    def test_is_admin_only(self, authed_client, fake_stripe, plan):
        response = start(authed_client, plan)

        assert response.status_code == 403
        assert fake_stripe.calls == []

    def test_an_unknown_plan_is_404(self, admin_client, fake_stripe):
        response = admin_client.post(
            reverse("PlanPriceChanges", args=[999]), {"cost": 2500}, format="json"
        )

        assert response.status_code == 404


# --- Moving subscriptions --------------------------------------------------


class TestRun:
    def test_a_rate_limited_subscription_is_retried_and_moved(
        self, fake_stripe, plan, members, sleeps
    ):
        job = make_job(plan, fake_stripe)
        target = members[1].stripe_subscription_id
        fake_stripe.fail[("Subscription.modify", target)] = [
            stripe.error.RateLimitError("slow down", http_status=429),
            stripe.error.RateLimitError("slow down", http_status=429),
        ]

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.COMPLETED
        assert fake_stripe.price_of(target) == "price_new"
        keys = {
            c["idempotency_key"]
            for c in fake_stripe.modify_calls()
            if c["id"] == target
        }
        assert keys == {f"plan-price-change-{job.pk}-run1-{target}"}
        assert len(sleeps) == 2 and min(sleeps) >= 1.0

    def test_a_refused_subscription_is_reported_and_the_rest_still_move(
        self, fake_stripe, plan, members
    ):
        job = make_job(plan, fake_stripe)
        refused = members[0]
        fake_stripe.fail[("Subscription.modify", refused.stripe_subscription_id)] = [
            rejected()
        ]

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.PARTIAL
        assert (job.migrated_count, job.remaining_count) == (2, 1)
        assert job.failures == [
            {
                "subscription": refused.stripe_subscription_id,
                "customer": refused.stripe_customer_id,
                "member": refused.get_full_name(),
                "memberId": refused.user_id,
                "error": "This subscription is managed by a schedule.",
            }
        ]
        # The old price still has a subscriber, so it stays active.
        assert fake_stripe.prices[OLD_PRICE]["active"] is True

    def test_a_resumed_run_moves_only_what_is_left(
        self,
        admin_client,
        fake_stripe,
        plan,
        members,
        django_capture_on_commit_callbacks,
    ):
        job = make_job(plan, fake_stripe)
        refused = members[0].stripe_subscription_id
        fake_stripe.fail[("Subscription.modify", refused)] = [rejected()]
        run_price_change(job.pk)
        fake_stripe.calls.clear()

        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post(
                reverse("PlanPriceChangeResume", args=[job.pk])
            )

        assert response.status_code == 202
        job.refresh_from_db()
        assert job.status == Status.COMPLETED
        assert (job.runs, job.migrated_count, job.remaining_count) == (2, 3, 0)
        assert job.failures == []
        assert [c["id"] for c in fake_stripe.modify_calls()] == [refused]
        # A fresh key, so Stripe doesn't replay the first run's refusal.
        assert fake_stripe.modify_calls()[0]["idempotency_key"].endswith(
            f"-run2-{refused}"
        )

    def test_stops_when_stripe_keeps_failing_instead_of_burning_through_everyone(
        self, fake_stripe, plan
    ):
        for n in range(CONSECUTIVE_FAILURE_LIMIT + 3):
            subscribe(fake_stripe, plan, n)
        job = make_job(plan, fake_stripe)
        fake_stripe.fail[("Subscription.modify", None)] = [
            server_error() for _ in range(100)
        ]

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.INTERRUPTED
        assert "in a row failed" in job.error
        attempted = {c["id"] for c in fake_stripe.modify_calls()}
        assert len(attempted) == CONSECUTIVE_FAILURE_LIMIT
        assert job.remaining_count == CONSECUTIVE_FAILURE_LIMIT + 3

        # Stripe recovers; resuming finishes the job.
        fake_stripe.fail.clear()
        run_price_change(job.pk)
        job.refresh_from_db()
        assert job.status == Status.COMPLETED
        assert job.migrated_count == CONSECUTIVE_FAILURE_LIMIT + 3

    def test_refusals_dont_count_as_stripe_being_down(self, fake_stripe, plan):
        """A run of subscriptions Stripe refuses on their own merits is not an
        outage. Stopping would leave the healthy ones after them unmoved."""
        for n in range(CONSECUTIVE_FAILURE_LIMIT + 2):
            subscribe(fake_stripe, plan, n)
        job = make_job(plan, fake_stripe)
        for n in range(CONSECUTIVE_FAILURE_LIMIT + 1):
            fake_stripe.fail[("Subscription.modify", f"sub_{n:03d}")] = [rejected()]

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.PARTIAL
        assert job.migrated_count == 1
        assert len(job.failures) == CONSECUTIVE_FAILURE_LIMIT + 1

    def test_a_rejected_api_key_stops_the_run_at_once(self, fake_stripe, plan, members):
        job = make_job(plan, fake_stripe)
        fake_stripe.fail[("Subscription.modify", None)] = [
            stripe.error.AuthenticationError("Invalid API key", http_status=401)
            for _ in range(3)
        ]

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.INTERRUPTED
        assert "API key" in job.error
        assert len(fake_stripe.modify_calls()) == 1

    def test_listing_failing_throughout_interrupts_the_run(
        self, fake_stripe, plan, members
    ):
        job = make_job(plan, fake_stripe)
        fake_stripe.fail[("Subscription.list", None)] = [
            server_error() for _ in range(5)
        ]

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.INTERRUPTED
        assert job.error.startswith("Stripe error:")
        assert fake_stripe.modify_calls() == []

    def test_pages_through_every_subscription(self, fake_stripe, plan):
        for n in range(5):
            subscribe(fake_stripe, plan, n)
        fake_stripe.page_size = 2
        job = make_job(plan, fake_stripe)

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.COMPLETED
        assert job.migrated_count == 5

    def test_a_signup_landing_on_the_old_price_mid_run_is_swept_up(
        self, fake_stripe, plan, members
    ):
        job = make_job(plan, fake_stripe)

        def late_signup(sub_id):
            if "sub_late" not in fake_stripe.subscriptions:
                fake_stripe.add_subscription("sub_late", "cus_late", price_id=OLD_PRICE)

        fake_stripe.on_modify = late_signup

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.COMPLETED
        assert fake_stripe.price_of("sub_late") == "price_new"
        assert job.migrated_count == 4

    def test_moves_a_subscription_the_portal_does_not_track(self, fake_stripe, plan):
        fake_stripe.add_subscription("sub_manual", "cus_manual")
        job = make_job(plan, fake_stripe)

        run_price_change(job.pk)

        assert fake_stripe.price_of("sub_manual") == "price_new"

    def test_skips_subscriptions_that_can_never_bill_again(self, fake_stripe, plan):
        fake_stripe.add_subscription(
            "sub_expired", "cus_x", status="incomplete_expired"
        )
        job = make_job(plan, fake_stripe)

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.COMPLETED
        assert fake_stripe.modify_calls() == []

    def test_a_failed_archive_still_completes_with_a_note(
        self, fake_stripe, plan, members
    ):
        job = make_job(plan, fake_stripe)
        fake_stripe.fail[("Price.modify", OLD_PRICE)] = [rejected("No such price")]

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.COMPLETED
        assert "archiving the old price" in job.error

    @pytest.mark.override_config(ENABLE_STRIPE=False)
    def test_stripe_disabled_interrupts_without_calling_it(
        self, fake_stripe, plan, members
    ):
        job = make_job(plan, fake_stripe)

        run_price_change(job.pk)

        job.refresh_from_db()
        assert job.status == Status.INTERRUPTED
        assert fake_stripe.calls == []


# --- Claiming a run --------------------------------------------------------


class TestClaim:
    def test_a_completed_job_is_not_run_again(self, fake_stripe, plan):
        job = make_job(plan, fake_stripe, status=Status.COMPLETED)

        assert run_price_change(job.pk) is None
        assert fake_stripe.calls == []

    def test_a_live_run_is_not_joined_by_a_second(self, fake_stripe, plan):
        job = make_job(plan, fake_stripe, status=Status.RUNNING)

        assert run_price_change(job.pk) is None
        assert fake_stripe.calls == []

    def test_a_run_whose_worker_died_can_be_taken_over(
        self, fake_stripe, plan, members
    ):
        job = make_job(plan, fake_stripe, status=Status.RUNNING)
        PlanPriceChange.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(hours=1)
        )

        assert run_price_change(job.pk) is not None
        job.refresh_from_db()
        assert job.status == Status.COMPLETED


class TestResumeAndStatus:
    @pytest.mark.parametrize("job_status", [Status.COMPLETED, Status.RUNNING])
    def test_resume_refuses_a_job_that_is_done_or_running(
        self, admin_client, fake_stripe, plan, job_status
    ):
        job = make_job(plan, fake_stripe, status=job_status)

        response = admin_client.post(reverse("PlanPriceChangeResume", args=[job.pk]))

        assert response.status_code == 409
        assert response.data["message"] == "paymentPlans.priceChangeNotResumable"

    def test_detail_reports_progress(self, admin_client, fake_stripe, plan):
        job = make_job(plan, fake_stripe, status=Status.PARTIAL, migrated_count=4)

        response = admin_client.get(reverse("PlanPriceChangeDetail", args=[job.pk]))

        assert response.status_code == 200
        assert response.data["status"] == "partial"
        assert response.data["migratedCount"] == 4

    def test_list_counts_subscribed_members(
        self, admin_client, fake_stripe, plan, members
    ):
        make_job(plan, fake_stripe, status=Status.COMPLETED)
        ProfileFactory(membership_plan=plan, stripe_subscription_id=None)

        response = admin_client.get(reverse("PlanPriceChanges", args=[plan.pk]))

        assert response.data["subscriptionCount"] == 3
        assert len(response.data["priceChanges"]) == 1


def test_editing_a_plan_no_longer_changes_its_cost(admin_client, plan):
    response = admin_client.put(
        reverse("ManageMembershipTierPlan", args=[plan.pk]),
        {"name": "Renamed", "description": "", "visible": True, "cost": 9900},
        format="json",
    )

    assert response.status_code == 200
    plan.refresh_from_db()
    assert (plan.name, plan.cost) == ("Renamed", 2000)


class TestManagementCommand:
    def test_runs_a_job_in_the_foreground(self, fake_stripe, plan, members, capsys):
        job = make_job(plan, fake_stripe)

        call_command("run_plan_price_change", job.pk)

        assert "completed" in capsys.readouterr().out
        job.refresh_from_db()
        assert job.status == Status.COMPLETED

    def test_an_unknown_job_is_an_error(self):
        with pytest.raises(CommandError):
            call_command("run_plan_price_change", 999)
