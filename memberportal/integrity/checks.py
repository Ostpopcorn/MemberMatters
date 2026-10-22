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
