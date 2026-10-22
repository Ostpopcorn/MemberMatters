"""A whole run against a fake Stripe: what it records and resolves."""

import time
from datetime import timedelta

import pytest
import stripe
from constance.test import override_config
from django.forms.models import model_to_dict
from django.utils import timezone

from integrity import runner
from integrity.models import IntegrityIssue, IntegrityRun, Severity, Source
from profile.models import Profile
from tests.factories import PaymentPlanFactory, ProfileFactory


pytestmark = pytest.mark.django_db


def member(subscription_id="sub_anna", customer="cus_anna", **overrides):
    values = {
        "state": "active",
        "subscription_status": "active",
        "billing_method": "card",
        "stripe_customer_id": customer,
        "stripe_subscription_id": subscription_id,
        "membership_plan": PaymentPlanFactory(),
    }
    values.update(overrides)
    return ProfileFactory(**values)


def run():
    return runner.run(IntegrityRun.Trigger.SCHEDULE).run


def open_checks():
    return sorted(
        IntegrityIssue.objects.filter(resolved_at__isnull=True).values_list(
            "check_name", flat=True
        )
    )


@pytest.fixture
def in_sync(billing_on, fake_stripe):
    """A member whose subscription agrees with Stripe."""
    profile = member()
    fake_stripe.add("sub_anna", "cus_anna", profile.membership_plan.stripe_id)
    return profile


class TestEnabled:
    def test_is_off_without_membership_billing(self, db):
        assert runner.is_enabled() is False

    def test_is_on_with_billing_and_a_key(self, billing_on):
        assert runner.is_enabled() is True

    def test_can_be_switched_off(self, billing_on):
        with override_config(BILLING_AUDIT_ENABLED=False):
            assert runner.is_enabled() is False


class TestRun:
    def test_a_member_in_sync_raises_nothing(self, in_sync, fake_stripe):
        result = run()

        assert result.status == IntegrityRun.Status.COMPLETE
        assert result.members_checked == 1
        assert open_checks() == []

    def test_one_listing_covers_every_live_subscription(self, billing_on, fake_stripe):
        for n in range(5):
            profile = member(f"sub_{n}", f"cus_{n}")
            fake_stripe.add(f"sub_{n}", f"cus_{n}", profile.membership_plan.stripe_id)

        run()

        assert len(fake_stripe.calls_to("Subscription.list")) == 1
        assert fake_stripe.calls_to("Subscription.retrieve") == []

    def test_a_subscription_missing_from_the_listing_is_fetched_alone(
        self, billing_on, fake_stripe
    ):
        profile = member()
        fake_stripe.add(
            "sub_anna",
            "cus_anna",
            profile.membership_plan.stripe_id,
            status="canceled",
            canceled_at=1_600_000_000,
        )

        run()

        assert [call[1] for call in fake_stripe.calls_to("Subscription.retrieve")] == [
            ("sub_anna",)
        ]
        assert open_checks() == ["ended_in_stripe"]

    def test_records_drift_as_an_issue(self, billing_on, fake_stripe):
        profile = member()
        fake_stripe.add(
            "sub_anna",
            "cus_anna",
            profile.membership_plan.stripe_id,
            status="canceled",
            canceled_at=1_600_000_000,
        )

        result = run()

        issue = IntegrityIssue.objects.get()
        assert issue.check_name == "ended_in_stripe"
        assert issue.severity == Severity.CRITICAL
        assert issue.source == Source.LEGACY
        assert issue.profile == profile
        assert issue.stripe_ref == "sub_anna"
        assert issue.details["mm"] == "active"
        assert issue.details["stripe"].startswith("canceled on")
        assert result.new_issues == 1
        assert result.open_issues == 1

    def test_the_same_drift_next_run_updates_the_same_issue(
        self, billing_on, fake_stripe
    ):
        profile = member()
        fake_stripe.add(
            "sub_anna", "cus_anna", profile.membership_plan.stripe_id, status="unpaid"
        )

        run()
        run()

        issue = IntegrityIssue.objects.get()
        assert issue.occurrences == 2

    def test_drift_that_is_fixed_resolves(self, in_sync, fake_stripe):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"

        result = run()

        issue = IntegrityIssue.objects.get()
        assert issue.resolved_at is not None
        assert result.resolved_issues == 1

    def test_resolved_drift_that_returns_reopens_as_new(self, in_sync, fake_stripe):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()
        IntegrityIssue.objects.update(
            acknowledged_at=timezone.now(), notified_severity=Severity.WARNING
        )
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"

        result = run()

        issue = IntegrityIssue.objects.get()
        assert issue.resolved_at is None
        assert issue.occurrences == 1
        assert issue.acknowledged_at is None
        assert issue.notified_severity == ""
        assert result.new_issues == 1

    def test_a_recent_stripe_change_waits_for_the_next_run(
        self, billing_on, fake_stripe
    ):
        profile = member()
        fake_stripe.add(
            "sub_anna",
            "cus_anna",
            profile.membership_plan.stripe_id,
            status="canceled",
            canceled_at=int(time.time()) - 60,
            ended_at=int(time.time()) - 60,
        )

        run()

        assert open_checks() == []

    def test_a_recent_change_leaves_an_open_issue_open(self, in_sync, fake_stripe):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"
        fake_stripe.subscriptions["sub_anna"]["canceled_at"] = int(time.time()) - 60

        run()

        assert IntegrityIssue.objects.get().resolved_at is None

    def test_a_stripe_outage_fails_the_run_and_resolves_nothing(
        self, in_sync, fake_stripe
    ):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"
        fake_stripe.errors["Subscription.list"] = stripe.error.APIError("down")

        result = run()

        assert result.status == IntegrityRun.Status.FAILED
        assert "Couldn't read subscriptions" in result.error
        assert IntegrityIssue.objects.get().resolved_at is None

    def test_a_restricted_key_without_webhook_access_still_completes(
        self, in_sync, fake_stripe
    ):
        fake_stripe.errors["WebhookEndpoint.list"] = stripe.error.PermissionError(
            "no permission"
        )

        result = run()

        assert result.status == IntegrityRun.Status.COMPLETE
        assert [entry["check"] for entry in result.skipped_checks] == [
            "webhook_endpoint"
        ]

    def test_a_failed_price_fetch_makes_the_run_incomplete(self, in_sync, fake_stripe):
        fake_stripe.errors["Price.retrieve"] = stripe.error.APIError("down")

        result = run()

        assert result.status == IntegrityRun.Status.INCOMPLETE

    def test_refuses_to_start_while_another_run_is_running(self, in_sync):
        IntegrityRun.objects.create(trigger=IntegrityRun.Trigger.SCHEDULE)

        with pytest.raises(runner.AlreadyRunning):
            run()

    def test_a_run_that_died_is_marked_failed(self, in_sync):
        dead = IntegrityRun.objects.create(
            trigger=IntegrityRun.Trigger.SCHEDULE,
            started_at=timezone.now() - timedelta(hours=3),
        )

        run()

        dead.refresh_from_db()
        assert dead.status == IntegrityRun.Status.FAILED

    def test_counts_its_stripe_requests(self, in_sync, fake_stripe):
        result = run()

        assert result.stripe_requests == len(fake_stripe.calls)

    def test_a_dry_run_writes_nothing(self, billing_on, fake_stripe, outbox):
        profile = member()
        fake_stripe.add(
            "sub_anna", "cus_anna", profile.membership_plan.stripe_id, status="unpaid"
        )

        outcome = runner.run(IntegrityRun.Trigger.COMMAND, dry_run=True)

        assert IntegrityRun.objects.count() == 0
        assert IntegrityIssue.objects.count() == 0
        assert outbox == []
        [(_source, _ctx, results)] = outcome.checked
        assert results.findings[(Source.LEGACY, "unpaid_but_active")]


class TestMemberRecheck:
    def test_fetches_only_that_members_customer(self, billing_on, fake_stripe):
        profile = member()
        fake_stripe.add("sub_anna", "cus_anna", profile.membership_plan.stripe_id)

        runner.run(IntegrityRun.Trigger.MEMBER, profile=profile)

        [listing] = fake_stripe.calls_to("Subscription.list")
        assert listing[2]["customer"] == "cus_anna"
        assert fake_stripe.calls_to("Price.retrieve") == []
        assert fake_stripe.calls_to("WebhookEndpoint.list") == []

    def test_resolves_only_that_members_issues(self, billing_on, fake_stripe):
        anna = member("sub_anna", "cus_anna")
        erik = member("sub_erik", "cus_erik")
        fake_stripe.add(
            "sub_anna", "cus_anna", anna.membership_plan.stripe_id, status="unpaid"
        )
        fake_stripe.add(
            "sub_erik", "cus_erik", erik.membership_plan.stripe_id, status="unpaid"
        )
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"
        fake_stripe.subscriptions["sub_erik"]["status"] = "active"

        runner.run(IntegrityRun.Trigger.MEMBER, profile=anna)

        assert IntegrityIssue.objects.get(profile=anna).resolved_at is not None
        assert IntegrityIssue.objects.get(profile=erik).resolved_at is None


class TestReadOnly:
    """A run must never change what it checks. A repair would hide the bug
    that caused the drift, and a buggy one would run unattended against
    membership and money."""

    def test_changes_no_member_and_writes_nothing_to_stripe(
        self, billing_on, fake_stripe
    ):
        drifted = [
            member("sub_a", "cus_a"),
            member("sub_b", "cus_b", subscription_status="cancelling"),
            member("sub_c", "cus_c", subscription_status="pending"),
            member("sub_d", "cus_d", state="inactive"),
        ]
        price = drifted[0].membership_plan.stripe_id
        fake_stripe.add("sub_a", "cus_a", price, status="canceled", canceled_at=1)
        fake_stripe.add("sub_b", "cus_b", drifted[1].membership_plan.stripe_id)
        fake_stripe.add("sub_c", "cus_c", drifted[2].membership_plan.stripe_id)
        fake_stripe.add("sub_d", "cus_d", drifted[3].membership_plan.stripe_id)
        fake_stripe.add("sub_orphan", "cus_gone", price)
        before = [model_to_dict(profile) for profile in Profile.objects.order_by("pk")]

        run()

        after = [model_to_dict(profile) for profile in Profile.objects.order_by("pk")]
        assert after == before
        assert fake_stripe.writes == []
        assert len(open_checks()) >= 5
