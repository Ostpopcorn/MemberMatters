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


from .models import Severity, Source
from .data import Finding, SkippedPart

# Local statuses under which a member has, or is getting, a subscription.
HAS_SUBSCRIPTION = ("active", "cancelling", "pending")


def _status_text(local):
    if local.status == "pending":
        return "pending (waiting for the first payment)"
    return local.status


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
)


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
