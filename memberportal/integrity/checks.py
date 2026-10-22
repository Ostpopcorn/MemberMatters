"""The checks: pure functions from a CheckContext to Findings.

Each check compares one thing MemberMatters records with what Stripe says.
None of them reads the database or calls Stripe; the runner gathers both
sides first. Adding a check is one function and one line in CHECKS.

A check reports drift and suggests a fix. It never repairs anything: an
automatic repair would hide the bug that caused the drift.
"""

import dataclasses
from collections import defaultdict
from typing import Callable

from django.utils import timezone

from .models import Severity, Source
from .data import SUBSCRIPTIONS, Finding, SkippedPart

# Subscription statuses after which Stripe never bills again.
ENDED = ("canceled", "incomplete_expired")

# Local statuses under which a member has, or is getting, a subscription.
HAS_SUBSCRIPTION = ("active", "cancelling", "pending")

RESEND_HINT = (
    "Resend the event from the Stripe dashboard under Developers → Events, "
    "if it is less than 30 days old."
)


def _day(moment):
    if moment is None:
        return "an unknown date"
    return timezone.localtime(moment).strftime("%d %b %Y").lstrip("0")


def _status_text(local):
    if local.status == "pending":
        return "pending (waiting for the first payment)"
    return local.status


def _plan_names(ctx):
    return {plan.stripe_id: plan.name for plan in ctx.plans if plan.stripe_id}


def _tracked(ctx):
    """Each member tracking a subscription, with Stripe's copy of it (None if
    Stripe answered 404). Members whose subscription changed too recently to
    judge are left out."""
    for local in ctx.local:
        if not local.subscription_id:
            continue
        if ctx.is_deferred(local.profile_id, local.subscription_id):
            continue
        yield local, ctx.snapshot.subscriptions.get(local.subscription_id)


def _finding(check, local, severity, message, **kwargs):
    """A finding about one member, keyed by that member."""
    kwargs.setdefault("stripe_ref", local.subscription_id or "")
    return Finding(
        check=check,
        severity=severity,
        subject=f"profile:{local.profile_id}",
        message=message,
        profile_id=local.profile_id,
        **kwargs,
    )


def shared_subscription_id(ctx):
    by_subscription = defaultdict(list)
    for local in ctx.local:
        if local.subscription_id:
            by_subscription[local.subscription_id].append(local)

    for subscription_id, members in by_subscription.items():
        if len(members) < 2:
            continue
        names = ", ".join(sorted(member.name for member in members))
        for local in members:
            yield Finding(
                check="shared_subscription_id",
                severity=Severity.CRITICAL,
                subject=f"{subscription_id}:{local.profile_id}",
                message="Subscription shared with another member",
                profile_id=local.profile_id,
                stripe_ref=subscription_id,
                mm=f"{len(members)} members track {subscription_id}: {names}",
                cause="The subscription ID was copied to another member by hand.",
                action=(
                    "Find whose subscription it is in Stripe, and clear the ID on "
                    "the other members in the Django admin."
                ),
            )


def status_without_subscription(ctx):
    for local in ctx.local:
        if local.subscription_id or local.status not in HAS_SUBSCRIPTION:
            continue
        if ctx.is_deferred(local.profile_id):
            continue
        yield _finding(
            "status_without_subscription",
            local,
            Severity.WARNING,
            f"Subscription is {local.status} with no subscription ID",
            mm=f"{_status_text(local)}, no subscription ID",
            cause=(
                "The subscription ID was cleared without resetting the status, "
                "by hand or by an interrupted signup."
            ),
            action=(
                "Look the member up in Stripe. If they have no subscription, set "
                "their subscription status to inactive in the Django admin."
            ),
        )


def subscription_missing(ctx):
    for local, subscription in _tracked(ctx):
        if local.subscription_id not in ctx.snapshot.missing_subscriptions:
            continue
        yield _finding(
            "subscription_missing",
            local,
            (
                Severity.CRITICAL
                if local.status in HAS_SUBSCRIPTION
                else Severity.WARNING
            ),
            "Subscription not found in Stripe",
            mm=f"{_status_text(local)}, tracks {local.subscription_id}",
            stripe="No such subscription",
            cause=(
                "The ID belongs to another Stripe account or mode (test or live), "
                "or was edited by hand."
            ),
            action=(
                "Look the member up in Stripe, then correct or clear the "
                "subscription ID in the Django admin."
            ),
        )


def customer_mismatch(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or subscription.customer == (local.customer_id or None):
            continue
        yield _finding(
            "customer_mismatch",
            local,
            Severity.CRITICAL,
            "Subscription belongs to another Stripe customer",
            mm=f"customer {local.customer_id or '(none)'}",
            stripe=f"{subscription.id} belongs to {subscription.customer}",
            cause=(
                "Webhooks are matched to members by customer, so the events for "
                "this subscription go to someone else or nowhere."
            ),
            action=(
                "Check in Stripe which customer is right, and correct the member's "
                "customer or subscription ID in the Django admin."
            ),
        )


def ended_in_stripe(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or subscription.status not in ENDED:
            continue
        if local.status not in HAS_SUBSCRIPTION:
            continue
        ended = subscription.ended_at or subscription.canceled_at
        yield _finding(
            "ended_in_stripe",
            local,
            Severity.CRITICAL,
            f"Cancelled in Stripe, still {local.status} here",
            mm=_status_text(local),
            stripe=f"{subscription.status} on {_day(ended)}",
            cause="The customer.subscription.deleted webhook was missed or failed.",
            action=(
                f"{RESEND_HINT} Otherwise cancel the membership immediately on the "
                "member's Billing tab."
            ),
        )


def cancel_not_scheduled(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or local.status != "cancelling":
            continue
        if subscription.status in ENDED or subscription.cancel_scheduled:
            continue
        yield _finding(
            "cancel_not_scheduled",
            local,
            Severity.CRITICAL,
            "Cancelling here, but Stripe will renew it",
            mm="cancelling",
            stripe=f"{subscription.status}, renews automatically",
            cause=(
                "The cancellation was undone in Stripe, or never reached it. The "
                "member expects no more charges."
            ),
            action=(
                "Schedule the cancellation at period end in Stripe. If the member "
                "changed their mind, they can resume the membership instead."
            ),
        )


def paid_but_pending(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or local.status != "pending":
            continue
        invoice = subscription.latest_invoice
        if invoice is None or invoice.status != "paid":
            continue
        if local.state_locked:
            severity = Severity.INFO
            cause = (
                "The member is locked, so the payment is held until an admin "
                "unlocks them."
            )
            action = "Unlock the member on their Profile tab when they should start."
        else:
            severity = Severity.CRITICAL
            cause = "The invoice.paid webhook was missed or failed."
            action = RESEND_HINT
        yield _finding(
            "paid_but_pending",
            local,
            severity,
            "Paid in Stripe, still pending here",
            mm=_status_text(local),
            stripe=f"invoice {invoice.id} paid on {_day(invoice.paid_at)}",
            cause=cause,
            action=action,
        )


def cancel_not_shown(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or local.status != "active":
            continue
        if subscription.status in ENDED or not subscription.cancel_scheduled:
            continue
        if subscription.cancel_at is not None:
            stripe_says = f"cancels on {_day(subscription.cancel_at)}"
        else:
            stripe_says = "cancels at the end of the period"
        yield _finding(
            "cancel_not_shown",
            local,
            Severity.WARNING,
            "Cancellation scheduled in Stripe, not shown here",
            mm="active",
            stripe=stripe_says,
            cause=(
                "The cancellation was made in the Stripe dashboard, which "
                "MemberMatters doesn't hear about until the subscription ends."
            ),
            action=(
                "Nothing breaks: the membership ends when the subscription does. "
                "Undo the cancellation in Stripe if it was a mistake."
            ),
        )


def unpaid_but_active(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or subscription.status != "unpaid":
            continue
        if local.status not in ("active", "cancelling"):
            continue
        yield _finding(
            "unpaid_but_active",
            local,
            Severity.WARNING,
            f"Unpaid in Stripe, still {local.status} here",
            mm=local.status,
            stripe="unpaid: every payment retry failed",
            cause=(
                "Stripe kept the subscription as unpaid instead of cancelling it, "
                "so no webhook ends the membership."
            ),
            action=(
                "Cancel the membership on the member's Billing tab, and check what "
                "Stripe does after the last retry under Billing → Revenue recovery."
            ),
        )


def paused_or_incomplete(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None:
            continue
        if subscription.status not in ("paused", "incomplete"):
            continue
        if local.status not in HAS_SUBSCRIPTION:
            continue
        if subscription.status == "paused":
            cause = (
                "The subscription was paused in Stripe, so the member isn't "
                "billed but keeps their membership here."
            )
            action = "Resume the subscription in Stripe, or cancel the membership."
        else:
            cause = (
                "The first payment needs action from the member, such as "
                "confirming their card."
            )
            action = (
                "Ask the member to finish the payment, or cancel the subscription "
                "in Stripe."
            )
        yield _finding(
            "paused_or_incomplete",
            local,
            Severity.WARNING,
            f"Subscription is {subscription.status} in Stripe",
            mm=_status_text(local),
            stripe=subscription.status,
            cause=cause,
            action=action,
        )


def past_due(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or subscription.status != "past_due":
            continue
        if local.status not in ("active", "cancelling"):
            continue
        yield _finding(
            "past_due",
            local,
            Severity.INFO,
            "Payment failed, Stripe is retrying",
            mm=local.status,
            stripe="past_due",
            cause=(
                "The latest payment failed or is overdue. Stripe retries it and "
                "cancels the subscription if every retry fails."
            ),
            action="Nothing to do unless the member asks for help.",
        )


def plan_mismatch(ctx):
    names = _plan_names(ctx)
    for local, subscription in _tracked(ctx):
        if subscription is None or subscription.status in ENDED:
            continue
        if not local.price_id or not subscription.price_ids:
            continue
        if local.price_id in subscription.price_ids:
            continue
        stripe_plans = ", ".join(
            names.get(price_id, price_id) for price_id in subscription.price_ids
        )
        yield _finding(
            "plan_mismatch",
            local,
            Severity.WARNING,
            "Plan differs from Stripe",
            mm=names.get(local.price_id, local.price_id),
            stripe=stripe_plans,
            cause="The subscription's price was changed in the Stripe dashboard.",
            action=(
                "Change the price back in Stripe, or set the member's plan here to "
                "what they pay, in the Django admin."
            ),
        )


def billing_method_mismatch(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or subscription.status in ENDED:
            continue
        expected = (
            "send_invoice"
            if local.billing_method == "invoice"
            else "charge_automatically"
        )
        if not subscription.collection_method:
            continue
        if subscription.collection_method == expected:
            continue
        yield _finding(
            "billing_method_mismatch",
            local,
            Severity.WARNING,
            "Billing method differs from Stripe",
            mm=f"pays by {local.billing_method}",
            stripe=f"collection method {subscription.collection_method}",
            cause="The collection method was changed in the Stripe dashboard.",
            action=(
                "Change it back in Stripe, or update the member's billing method in "
                "the Django admin. It decides which reminders the member gets and "
                "whether their invoices show under Pending Invoices."
            ),
        )


def inactive_but_billed(ctx):
    for local, subscription in _tracked(ctx):
        if subscription is None or subscription.status != "active":
            continue
        if local.member_state != "inactive":
            continue
        if local.status not in ("active", "cancelling"):
            continue
        yield _finding(
            "inactive_but_billed",
            local,
            Severity.WARNING,
            "Inactive member is still billed",
            mm=f"member inactive, subscription {local.status}",
            stripe="active",
            cause="The member was deactivated without cancelling their subscription.",
            action=(
                "Cancel the membership on the member's Billing tab if they shouldn't "
                "be charged."
            ),
        )


def _untracked_live_subscriptions(ctx):
    """Live membership subscriptions in Stripe that no member tracks.

    An incomplete subscription is left out: it charges nothing and Stripe
    expires it within a day, and a signup whose first payment needed
    authentication leaves exactly that behind.
    """
    membership_prices = {plan.stripe_id for plan in ctx.plans if plan.stripe_id}
    tracked = {local.subscription_id for local in ctx.local if local.subscription_id}

    for subscription in ctx.snapshot.subscriptions.values():
        if subscription.id in tracked:
            continue
        if subscription.status in ENDED or subscription.status == "incomplete":
            continue
        if not membership_prices & set(subscription.price_ids):
            continue
        if ctx.is_deferred(ref=subscription.id):
            continue
        yield subscription


def untracked_subscription(ctx):
    by_customer = {local.customer_id: local for local in ctx.local if local.customer_id}
    for subscription in _untracked_live_subscriptions(ctx):
        local = by_customer.get(subscription.customer)
        if local is None or ctx.is_deferred(local.profile_id):
            continue

        tracked = ctx.snapshot.subscriptions.get(local.subscription_id or "")
        if tracked is not None and tracked.status not in ENDED:
            message = "Second live subscription in Stripe"
            cause = (
                "Two signups raced, or a subscription was created in the Stripe "
                "dashboard. The member may be charged twice."
            )
        else:
            message = "Billed in Stripe, no subscription here"
            cause = (
                "A subscription was created in the Stripe dashboard, or the signup "
                "failed after Stripe created it. The member is charged but "
                "MemberMatters doesn't know."
            )
        yield Finding(
            check="untracked_subscription",
            severity=Severity.CRITICAL,
            subject=subscription.id,
            message=message,
            profile_id=local.profile_id,
            stripe_ref=subscription.id,
            mm=(
                f"{_status_text(local)}, tracks {local.subscription_id}"
                if local.subscription_id
                else _status_text(local)
            ),
            stripe=f"{subscription.id} is {subscription.status}",
            cause=cause,
            action=(
                "Cancel the extra subscription in Stripe and refund if needed, or "
                "ask a developer to link it to the member."
            ),
        )


def orphan_subscription(ctx):
    customers = {local.customer_id for local in ctx.local if local.customer_id}
    for subscription in _untracked_live_subscriptions(ctx):
        if subscription.customer in customers:
            continue
        yield Finding(
            check="orphan_subscription",
            severity=Severity.CRITICAL,
            subject=subscription.id,
            message="Billed in Stripe for no member",
            stripe_ref=subscription.id,
            mm=f"no member has customer {subscription.customer}",
            stripe=f"{subscription.id} is {subscription.status}",
            cause=(
                "The member was deleted, or their customer ID was changed, while "
                "the subscription kept running."
            ),
            action=(
                "Find the customer in Stripe. Cancel the subscription, or restore "
                "the customer ID on the right member in the Django admin."
            ),
        )


@dataclasses.dataclass(frozen=True)
class Check:
    name: str
    fn: Callable
    # Snapshot parts the check reads. If one couldn't be fetched, the check
    # is skipped and its open issues are left alone.
    needs: tuple = ()
    # False for checks that don't read a member's subscription (plans, the
    # webhook endpoint). Those run once, under Source.ACCOUNT, rather than
    # once per local source.
    per_source: bool = True
    # Skipped on a member re-check, which fetches only that member's customer.
    full_only: bool = False


CHECKS = (
    Check("shared_subscription_id", shared_subscription_id, full_only=True),
    Check("status_without_subscription", status_without_subscription),
    Check("subscription_missing", subscription_missing, (SUBSCRIPTIONS,)),
    Check("customer_mismatch", customer_mismatch, (SUBSCRIPTIONS,)),
    Check("ended_in_stripe", ended_in_stripe, (SUBSCRIPTIONS,)),
    Check("cancel_not_scheduled", cancel_not_scheduled, (SUBSCRIPTIONS,)),
    Check("paid_but_pending", paid_but_pending, (SUBSCRIPTIONS,)),
    Check("cancel_not_shown", cancel_not_shown, (SUBSCRIPTIONS,)),
    Check("unpaid_but_active", unpaid_but_active, (SUBSCRIPTIONS,)),
    Check("paused_or_incomplete", paused_or_incomplete, (SUBSCRIPTIONS,)),
    Check("past_due", past_due, (SUBSCRIPTIONS,)),
    Check("plan_mismatch", plan_mismatch, (SUBSCRIPTIONS,)),
    Check("billing_method_mismatch", billing_method_mismatch, (SUBSCRIPTIONS,)),
    Check("inactive_but_billed", inactive_but_billed, (SUBSCRIPTIONS,)),
    Check("untracked_subscription", untracked_subscription, (SUBSCRIPTIONS,)),
    Check(
        "orphan_subscription",
        orphan_subscription,
        (SUBSCRIPTIONS,),
        full_only=True,
    ),
)


def defer_unsettled(ctx):
    """Mark what changed too recently to judge, or couldn't be fetched.

    A subscription Stripe changed within the settle window may still have its
    webhook in flight, so neither side is trusted yet. A member tracking a
    subscription the snapshot doesn't hold (created after the listing, or a
    failed fetch) can't be judged either. Checks skip deferred members and
    subscriptions, and the store neither updates nor resolves their issues.
    """
    cutoff = ctx.now - ctx.settle
    by_customer = {local.customer_id: local for local in ctx.local if local.customer_id}

    for subscription in ctx.snapshot.subscriptions.values():
        changed = subscription.last_changed
        if changed is None or changed <= cutoff:
            continue
        ctx.deferred_refs.add(subscription.id)
        owner = by_customer.get(subscription.customer)
        if owner is not None:
            ctx.deferred_profiles.add(owner.profile_id)

    if not ctx.snapshot.has(SUBSCRIPTIONS):
        return
    for local in ctx.local:
        subscription_id = local.subscription_id
        if not subscription_id:
            continue
        if subscription_id in ctx.snapshot.subscriptions:
            continue
        if subscription_id in ctx.snapshot.missing_subscriptions:
            continue
        ctx.deferred_profiles.add(local.profile_id)
        ctx.deferred_refs.add(subscription_id)


@dataclasses.dataclass
class CheckResults:
    # Findings of every check that ran, keyed by (source, check name). A check
    # that ran and found nothing maps to an empty list, which is what lets its
    # old issues resolve.
    findings: dict = dataclasses.field(default_factory=dict)
    # SkippedPart of every check that didn't run, keyed the same way.
    skipped: dict = dataclasses.field(default_factory=dict)


def run_checks(ctx, source, checks=CHECKS, include_account=True, on_error=None):
    """Run every applicable check against one local source.

    Checks that don't read a local source run under Source.ACCOUNT, and only
    when `include_account` is set, so a second source doesn't repeat them. A
    check that raises is skipped, not fatal.
    """
    results = CheckResults()
    for check in checks:
        if check.full_only and ctx.member_scope:
            continue
        if not check.per_source and not include_account:
            continue
        key = (source if check.per_source else Source.ACCOUNT, check.name)

        missing = [part for part in check.needs if not ctx.snapshot.has(part)]
        if missing:
            parts = [ctx.snapshot.skipped[part] for part in missing]
            results.skipped[key] = SkippedPart(
                reason="; ".join(part.reason for part in parts),
                incomplete=any(part.incomplete for part in parts),
            )
            continue
        try:
            results.findings[key] = list(check.fn(ctx))
        except Exception as error:
            if on_error is not None:
                on_error(error)
            results.skipped[key] = SkippedPart(reason=f"the check failed: {error}")
    return results
