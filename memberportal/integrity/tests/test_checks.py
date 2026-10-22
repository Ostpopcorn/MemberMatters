"""Each check against hand-written data: no database, no Stripe."""

from datetime import datetime, timedelta, timezone

import pytest

from integrity.checks import CHECKS, defer_unsettled, run_checks
from integrity.data import (
    CheckContext,
    LocalBilling,
    PlanInfo,
    StripeInvoice,
    StripePrice,
    StripeSnapshot,
    StripeSubscription,
    StripeWebhookEndpoint,
)
from integrity.models import Severity, Source

NOW = datetime(2026, 10, 21, 3, 15, tzinfo=timezone.utc)
LONG_AGO = NOW - timedelta(days=60)
RECENTLY = NOW - timedelta(minutes=5)
WEBHOOK = "https://portal.example.org/api/billing/stripe-webhook/"
HANDLED = (
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)

PLAN = PlanInfo(
    id=1,
    name="Monthly",
    stripe_id="price_monthly",
    cost=2000,
    currency="sek",
    interval="month",
    interval_count=1,
    visible=True,
)
PAID = StripeInvoice("in_1", "paid", "subscription_create", LONG_AGO)
OPEN = StripeInvoice("in_1", "open", "subscription_create", None)


def local(**overrides):
    values = dict(
        profile_id=1,
        name="Anna Svensson",
        customer_id="cus_anna",
        subscription_id="sub_anna",
        status="active",
        price_id="price_monthly",
        billing_method="card",
        member_state="active",
        state_locked=False,
    )
    values.update(overrides)
    return LocalBilling(**values)


def sub(**overrides):
    values = dict(
        id="sub_anna",
        customer="cus_anna",
        status="active",
        cancel_at_period_end=False,
        cancel_at=None,
        canceled_at=None,
        ended_at=None,
        created=LONG_AGO,
        collection_method="charge_automatically",
        price_ids=("price_monthly",),
        latest_invoice=PAID,
    )
    values.update(overrides)
    return StripeSubscription(**values)


def price(**overrides):
    values = dict(
        id="price_monthly",
        active=True,
        unit_amount=2000,
        currency="sek",
        interval="month",
        interval_count=1,
    )
    values.update(overrides)
    return StripePrice(**values)


ENDPOINT = StripeWebhookEndpoint("we_1", WEBHOOK, "enabled", ("*",))


def context(
    locals_=None,
    subs=None,
    missing=(),
    plans=(PLAN,),
    prices=None,
    endpoints=(ENDPOINT,),
    events=(),
    **overrides,
):
    snapshot = StripeSnapshot(
        taken_at=NOW,
        subscriptions={s.id: s for s in (subs if subs is not None else [sub()])},
        missing_subscriptions=set(missing),
        prices={p.id: p for p in (prices if prices is not None else [price()])},
        webhook_endpoints=list(endpoints),
        undelivered_events=list(events),
    )
    ctx = CheckContext(
        local=list(locals_ if locals_ is not None else [local()]),
        snapshot=snapshot,
        plans=list(plans),
        now=NOW,
        settle=timedelta(minutes=30),
        webhook_url=WEBHOOK,
        handled_events=HANDLED,
        **overrides,
    )
    defer_unsettled(ctx)
    return ctx


def found(ctx, name):
    check = next(check for check in CHECKS if check.name == name)
    return list(check.fn(ctx))


def all_findings(ctx):
    results = run_checks(ctx, Source.LEGACY)
    return {key: findings for key, findings in results.findings.items() if findings}


def test_a_member_in_sync_trips_no_check():
    assert all_findings(context()) == {}


# (check, local overrides, Stripe subscription overrides, expected severity)
MEMBER_CASES = [
    pytest.param(
        "ended_in_stripe",
        {},
        {"status": "canceled", "canceled_at": LONG_AGO, "ended_at": LONG_AGO},
        Severity.CRITICAL,
        id="ended-while-active",
    ),
    pytest.param(
        "ended_in_stripe",
        {"status": "pending"},
        {"status": "incomplete_expired"},
        Severity.CRITICAL,
        id="expired-while-pending",
    ),
    pytest.param(
        "ended_in_stripe",
        {"status": "inactive"},
        {"status": "canceled", "canceled_at": LONG_AGO},
        None,
        id="ended-and-inactive-here",
    ),
    pytest.param(
        "cancel_not_scheduled",
        {"status": "cancelling"},
        {},
        Severity.CRITICAL,
        id="cancelling-but-renews",
    ),
    pytest.param(
        "cancel_not_scheduled",
        {"status": "cancelling"},
        {"cancel_at_period_end": True, "cancel_at": NOW + timedelta(days=9)},
        None,
        id="cancelling-and-scheduled",
    ),
    pytest.param(
        "cancel_not_shown",
        {},
        {"cancel_at_period_end": True, "cancel_at": NOW + timedelta(days=9)},
        Severity.WARNING,
        id="scheduled-in-stripe-only",
    ),
    pytest.param(
        "paid_but_pending",
        {"status": "pending", "billing_method": "invoice"},
        {"collection_method": "send_invoice"},
        Severity.CRITICAL,
        id="paid-but-pending",
    ),
    pytest.param(
        "paid_but_pending",
        {"status": "pending", "billing_method": "invoice", "state_locked": True},
        {"collection_method": "send_invoice"},
        Severity.INFO,
        id="paid-but-pending-while-locked",
    ),
    pytest.param(
        "paid_but_pending",
        {"status": "pending", "billing_method": "invoice"},
        {"collection_method": "send_invoice", "latest_invoice": OPEN},
        None,
        id="pending-and-unpaid",
    ),
    pytest.param(
        "unpaid_but_active",
        {},
        {"status": "unpaid"},
        Severity.WARNING,
        id="unpaid",
    ),
    pytest.param("past_due", {}, {"status": "past_due"}, Severity.INFO, id="past-due"),
    pytest.param(
        "past_due",
        {"status": "pending", "billing_method": "invoice"},
        {"status": "past_due", "collection_method": "send_invoice"},
        None,
        id="overdue-first-invoice",
    ),
    pytest.param(
        "paused_or_incomplete",
        {},
        {"status": "paused"},
        Severity.WARNING,
        id="paused",
    ),
    pytest.param(
        "plan_mismatch",
        {},
        {"price_ids": ("price_yearly",)},
        Severity.WARNING,
        id="plan-changed-in-stripe",
    ),
    pytest.param(
        "billing_method_mismatch",
        {"billing_method": "invoice"},
        {},
        Severity.WARNING,
        id="invoice-here-card-in-stripe",
    ),
    pytest.param(
        "inactive_but_billed",
        {"member_state": "inactive"},
        {},
        Severity.WARNING,
        id="inactive-but-billed",
    ),
    pytest.param(
        "customer_mismatch",
        {},
        {"customer": "cus_erik"},
        Severity.CRITICAL,
        id="other-customer",
    ),
]


@pytest.mark.parametrize("check,local_overrides,sub_overrides,severity", MEMBER_CASES)
def test_member_checks(check, local_overrides, sub_overrides, severity):
    ctx = context([local(**local_overrides)], [sub(**sub_overrides)])

    findings = found(ctx, check)

    if severity is None:
        assert findings == []
    else:
        [finding] = findings
        assert finding.severity == severity
        assert finding.profile_id == 1
        assert finding.subject == "profile:1"
        assert finding.message and finding.cause and finding.action


def test_each_drift_trips_only_its_own_check():
    ctx = context([local()], [sub(status="unpaid")])

    assert list(all_findings(ctx)) == [(Source.LEGACY, "unpaid_but_active")]


class TestMissingSubscription:
    def test_is_critical_for_a_member_with_a_subscription(self):
        [finding] = found(
            context(subs=[], missing=["sub_anna"]), "subscription_missing"
        )

        assert finding.severity == Severity.CRITICAL
        assert finding.stripe == "No such subscription"

    def test_is_a_warning_for_a_left_over_id(self):
        ctx = context([local(status="inactive")], subs=[], missing=["sub_anna"])

        [finding] = found(ctx, "subscription_missing")

        assert finding.severity == Severity.WARNING


def test_a_status_without_a_subscription_id():
    [finding] = found(
        context([local(subscription_id=None)], subs=[]), "status_without_subscription"
    )

    assert finding.severity == Severity.WARNING


def test_an_active_member_without_any_subscription_is_never_a_finding():
    """Admin-activated, comped and billing-off members all look like this."""
    ctx = context(
        [local(customer_id=None, subscription_id=None, status="inactive")], subs=[]
    )

    assert all_findings(ctx) == {}


def test_a_shared_subscription_id_flags_every_member_sharing_it():
    ctx = context(
        [local(), local(profile_id=2, name="Erik Lund", customer_id="cus_erik")]
    )

    findings = found(ctx, "shared_subscription_id")

    assert {finding.profile_id for finding in findings} == {1, 2}
    assert all(finding.severity == Severity.CRITICAL for finding in findings)


class TestSettling:
    def test_a_recent_stripe_change_is_left_for_the_next_run(self):
        ctx = context(
            [local()], [sub(status="canceled", canceled_at=RECENTLY, ended_at=RECENTLY)]
        )

        assert all_findings(ctx) == {}
        assert ctx.is_deferred(profile_id=1)
        assert ctx.is_deferred(ref="sub_anna")

    def test_a_recently_paid_invoice_is_left_for_the_next_run(self):
        invoice = StripeInvoice("in_1", "paid", "subscription_create", RECENTLY)
        ctx = context([local(status="pending")], [sub(latest_invoice=invoice)])

        assert found(ctx, "paid_but_pending") == []

    def test_a_subscription_the_snapshot_lacks_is_deferred(self):
        ctx = context([local()], subs=[])

        assert all_findings(ctx) == {}
        assert ctx.is_deferred(profile_id=1)
