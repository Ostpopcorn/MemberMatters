"""Each check against hand-written data: no database, no Stripe."""

from datetime import datetime, timedelta, timezone


from integrity.checks import CHECKS, run_checks
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
    return ctx


def found(ctx, name):
    check = next(check for check in CHECKS if check.name == name)
    return list(check.fn(ctx))


def all_findings(ctx):
    results = run_checks(ctx, Source.LEGACY)
    return {key: findings for key, findings in results.findings.items() if findings}


def test_a_member_in_sync_trips_no_check():
    assert all_findings(context()) == {}


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
