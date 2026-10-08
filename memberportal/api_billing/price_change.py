"""Change a payment plan's price and move its subscriptions to the new price.

Stripe prices are immutable, so changing what a plan costs takes two stages:

1. `start_price_change()` runs in the admin's request. It creates a new Stripe
   price on the same product and interval, points the plan at it so new
   signups get it straight away, and records a PlanPriceChange.
2. `run_price_change()` runs in a Celery worker (api_billing.tasks). It moves
   every subscription still on the old price to the new one, one Stripe call
   each, and then archives the old price.

Existing subscriptions switch with proration_behavior="none", so a member pays
the new amount from their next renewal, with no mid-period charge or credit.

Stripe is the record of progress: a run lists whatever is still on the old
price and moves that. Every call goes through `call_with_retry`, and a run that
stops early (one subscription refused, or Stripe failing outright) can be
resumed without redoing the subscriptions that already moved.
"""

import logging
import uuid
from datetime import timedelta

import stripe
from constance import config
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from sentry_sdk import capture_exception

from api_admin_tools.models import PaymentPlan
from profile.models import Profile
from services.emails import send_email_to_admin

from .models import PlanPriceChange
from .stripe_retry import DEFAULT_POLICY, call_with_retry, is_retryable

logger = logging.getLogger("billing")

Status = PlanPriceChange.Status

# Stripe's own upper bound on unit_amount.
MAX_UNIT_AMOUNT = 99_999_999

# Subscriptions in these states can't be modified and will never bill again.
TERMINAL_SUBSCRIPTION_STATUSES = {"canceled", "incomplete_expired"}

# After this many subscriptions in a row fail with errors that were still
# transient after their retries, stop the run. That pattern means Stripe
# itself is down; carrying on would spend every remaining subscription's
# retries against the same outage. The run is left INTERRUPTED to resume.
CONSECUTIVE_FAILURE_LIMIT = 5

# A bad or revoked key fails every call, so the run stops at the first one.
AUTH_ERRORS = (stripe.error.AuthenticationError, stripe.error.PermissionError)

# A run saves the job after every subscription, so a RUNNING job untouched
# for this long has lost its worker and may be claimed again.
STALE_RUN_AFTER = timedelta(minutes=10)

# New signups get the new price as soon as stage 1 commits, but one already in
# flight may have read the old price and create its subscription after this
# run listed the old price. Each sweep lists the old price again and moves
# what turned up; this bounds how many times.
MAX_SWEEPS = 3


class PriceChangeRefused(Exception):
    """The change can't be started. `code` is a frontend i18n key."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PriceChangeInProgress(Exception):
    """The plan already has a price change that hasn't finished."""

    def __init__(self, job):
        super().__init__(f"Price change {job.pk} has not finished.")
        self.job = job


class _NotMovable(Exception):
    """A subscription this run can't move, for a reason a retry won't fix."""


def format_amount(cents, currency):
    return f"{cents / 100:.2f} {currency.upper()}"


def _stale_cutoff():
    return timezone.now() - STALE_RUN_AFTER


def is_resumable(job):
    if job.status in (Status.PENDING, Status.PARTIAL, Status.INTERRUPTED):
        return True
    return job.status == Status.RUNNING and job.updated_at < _stale_cutoff()


def enqueue_price_change(job_id):
    """Queue a run once the current transaction commits."""

    def _enqueue():
        # Imported here: tasks imports this module.
        from .tasks import run_plan_price_change

        try:
            run_plan_price_change.delay(job_id)
        except Exception as e:
            # Broker unreachable. The job stays as it is and can be resumed
            # from the admin page once the broker is back.
            capture_exception(e)
            logger.error("Could not queue plan price change %s: %s", job_id, e)

    transaction.on_commit(_enqueue)


def start_price_change(plan_id, new_cost, actor, policy=DEFAULT_POLICY):
    """Create the new price, repoint the plan and queue the subscription move.

    Raises PriceChangeRefused, PriceChangeInProgress, or the StripeError that
    survived its retries. Nothing is written locally if Stripe fails.
    """
    with transaction.atomic():
        # Lock so two admins can't each create a price for the same plan.
        plan = PaymentPlan.objects.select_for_update().get(pk=plan_id)

        unfinished = plan.price_changes.exclude(status=Status.COMPLETED).first()
        if unfinished:
            # A second change would strand the subscriptions the first one
            # hasn't moved yet on a price no job is tracking any more.
            raise PriceChangeInProgress(unfinished)

        # The current Stripe price, not the plan row, is what members pay
        # today, so compare against it and copy its terms.
        old_price = call_with_retry(
            stripe.Price.retrieve, plan.stripe_id, policy=policy
        )
        recurring = old_price.get("recurring")
        if not recurring or old_price.get("unit_amount") is None:
            raise PriceChangeRefused("paymentPlans.priceNotSupported")
        if old_price["unit_amount"] == new_cost:
            raise PriceChangeRefused("paymentPlans.priceUnchanged")

        params = {
            "product": old_price["product"],
            "currency": old_price["currency"],
            "unit_amount": new_cost,
            "recurring": {
                "interval": recurring["interval"],
                "interval_count": recurring["interval_count"],
            },
            "metadata": {
                "membermatters_plan_id": str(plan.pk),
                "replaces_price": old_price["id"],
            },
        }
        # Fixed once a price is created, so a change of price must not
        # silently turn tax-inclusive pricing into tax-exclusive.
        if old_price.get("tax_behavior"):
            params["tax_behavior"] = old_price["tax_behavior"]

        new_price = call_with_retry(
            stripe.Price.create,
            **params,
            # One key per admin request, shared by its retries, so a timeout
            # that Stripe did process doesn't leave a second price behind.
            idempotency_key=f"plan-price-change-{plan.pk}-{uuid.uuid4().hex}",
            policy=policy,
        )

        job = PlanPriceChange.objects.create(
            plan=plan,
            old_price_id=old_price["id"],
            new_price_id=new_price["id"],
            old_cost=old_price["unit_amount"],
            new_cost=new_cost,
            currency=old_price["currency"],
            created_by=actor,
        )

        plan.stripe_id = new_price["id"]
        plan.cost = new_cost
        plan.save(update_fields=["stripe_id", "cost"])

        enqueue_price_change(job.pk)

    logger.info(
        "Plan %s price change %s queued: %s -> %s.",
        plan.pk,
        job.pk,
        job.old_price_id,
        job.new_price_id,
    )
    return job


def _claim(job_id):
    """Mark the job RUNNING for this run, or return None if another run has it.

    A conditional UPDATE rather than a row lock, so the claim holds for the
    whole run without keeping a transaction open across Stripe calls.
    """
    claimable = Q(status__in=[Status.PENDING, Status.PARTIAL, Status.INTERRUPTED]) | Q(
        status=Status.RUNNING, updated_at__lt=_stale_cutoff()
    )
    claimed = PlanPriceChange.objects.filter(claimable, pk=job_id).update(
        status=Status.RUNNING,
        runs=F("runs") + 1,
        failures=[],
        error="",
        # QuerySet.update() skips auto_now.
        updated_at=timezone.now(),
    )
    if not claimed:
        return None
    return PlanPriceChange.objects.select_related("plan").get(pk=job_id)


def _subscriptions_on_price(price_id, policy, sleep):
    """Every live subscription billed at `price_id`, fetched page by page so
    each page gets its own retries."""
    subscriptions = []
    params = {"price": price_id, "limit": 100}
    while True:
        page = call_with_retry(
            stripe.Subscription.list, **params, policy=policy, sleep=sleep
        )
        subscriptions.extend(
            s for s in page["data"] if s["status"] not in TERMINAL_SUBSCRIPTION_STATUSES
        )
        if not page["has_more"] or not page["data"]:
            return subscriptions
        params["starting_after"] = page["data"][-1]["id"]


def _profiles_for(subscriptions):
    """Map subscription id -> Profile, falling back to the customer id for a
    subscription the portal doesn't track as the member's current one."""
    sub_ids = [s["id"] for s in subscriptions]
    customer_ids = [s["customer"] for s in subscriptions if s.get("customer")]
    profiles = list(
        Profile.objects.filter(
            Q(stripe_subscription_id__in=sub_ids)
            | Q(stripe_customer_id__in=customer_ids)
        ).select_related("user")
    )
    by_subscription = {p.stripe_subscription_id: p for p in profiles}
    by_customer = {p.stripe_customer_id: p for p in profiles}
    return {
        s["id"]: by_subscription.get(s["id"]) or by_customer.get(s.get("customer"))
        for s in subscriptions
    }


def _move_subscription(job, subscription, policy, sleep):
    items = (subscription.get("items") or {}).get("data") or []
    item = next(
        (i for i in items if (i.get("price") or {}).get("id") == job.old_price_id),
        None,
    )
    if item is None:
        raise _NotMovable("No item on this subscription uses the old price.")

    call_with_retry(
        stripe.Subscription.modify,
        subscription["id"],
        items=[{"id": item["id"], "price": job.new_price_id}],
        proration_behavior="none",
        # Shared by this run's retries; a resumed run uses a new key so a
        # failure cached against the old one isn't replayed back to it.
        idempotency_key=(
            f"plan-price-change-{job.pk}-run{job.runs}-{subscription['id']}"
        ),
        policy=policy,
        sleep=sleep,
    )


def _save_progress(job, **fields):
    for name, value in fields.items():
        setattr(job, name, value)
    job.save(update_fields=[*fields, "updated_at"])


def _migrate(job, policy, sleep):
    """Move subscriptions until none are left on the old price or the run has
    to stop. Returns (status, error)."""
    failures = {}
    consecutive_failures = 0
    old = format_amount(job.old_cost, job.currency)
    new = format_amount(job.new_cost, job.currency)

    for sweep in range(MAX_SWEEPS + 1):
        pending = [
            s
            for s in _subscriptions_on_price(job.old_price_id, policy, sleep)
            if s["id"] not in failures
        ]
        if not pending:
            break
        if sweep == MAX_SWEEPS:
            _save_progress(job, remaining_count=len(pending) + len(failures))
            return (
                Status.PARTIAL,
                "New subscriptions kept appearing on the old price; resume to "
                "move the rest.",
            )

        _save_progress(job, remaining_count=len(pending) + len(failures))
        profiles = _profiles_for(pending)

        for subscription in pending:
            profile = profiles.get(subscription["id"])
            try:
                _move_subscription(job, subscription, policy, sleep)
            except (stripe.error.StripeError, _NotMovable) as e:
                if isinstance(e, stripe.error.StripeError):
                    capture_exception(e)
                if isinstance(e, AUTH_ERRORS):
                    # Every remaining call would be refused the same way.
                    return Status.INTERRUPTED, f"Stripe refused the API key: {e}"
                # Only a failure that was still transient after its retries
                # says anything about Stripe being down. A refusal of this one
                # subscription is Stripe answering normally.
                if is_retryable(e):
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                failures[subscription["id"]] = {
                    "subscription": subscription["id"],
                    "customer": subscription.get("customer"),
                    "member": profile.get_full_name() if profile else None,
                    "memberId": profile.user_id if profile else None,
                    "error": getattr(e, "user_message", None) or str(e),
                }
                _save_progress(job, failures=list(failures.values()))
                if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    return (
                        Status.INTERRUPTED,
                        f"Stopped after {consecutive_failures} subscriptions in "
                        "a row failed. Stripe may be unavailable; resume to "
                        "try the rest again.",
                    )
                continue

            consecutive_failures = 0
            _save_progress(
                job,
                migrated_count=job.migrated_count + 1,
                remaining_count=job.remaining_count - 1,
            )
            if profile:
                profile.user.log_event(
                    f"Subscription moved from {old} to {new} for plan "
                    f"{job.plan.name}, effective from the next renewal "
                    f"(price change #{job.pk}).",
                    "stripe",
                )

    if failures:
        return Status.PARTIAL, ""

    # Nothing is left on the old price. Archive it so it can't be picked for
    # a new subscription by hand in the Stripe dashboard. Not fatal: the plan
    # no longer points at it, so no signup through the portal can use it.
    try:
        call_with_retry(
            stripe.Price.modify,
            job.old_price_id,
            active=False,
            idempotency_key=f"plan-price-change-{job.pk}-archive",
            policy=policy,
            sleep=sleep,
        )
    except stripe.error.StripeError as e:
        capture_exception(e)
        return (
            Status.COMPLETED,
            f"All subscriptions moved, but archiving the old price "
            f"{job.old_price_id} failed: {e.user_message or e}",
        )
    return Status.COMPLETED, ""


def run_price_change(job_id, policy=DEFAULT_POLICY, sleep=None):
    """One run of a price change. Returns the job, or None if it wasn't
    claimable (finished, or another run is active)."""
    job = _claim(job_id)
    if job is None:
        logger.info("Plan price change %s not claimable; skipping.", job_id)
        return None

    if not config.ENABLE_STRIPE:
        status, error = Status.INTERRUPTED, "Stripe is disabled."
    else:
        # Web requests set this in StripeAPIView; a worker has to do it.
        stripe.api_key = config.STRIPE_SECRET_KEY
        try:
            status, error = _migrate(job, policy, sleep)
        except stripe.error.StripeError as e:
            # Listing the old price failed even after retries.
            capture_exception(e)
            status = Status.INTERRUPTED
            error = f"Stripe error: {e.user_message or e}"
        except Exception as e:
            capture_exception(e)
            status = Status.INTERRUPTED
            error = f"Unexpected error: {e}"

    _save_progress(job, status=status, error=error, finished_at=timezone.now())
    _email_admin_summary(job)
    return job


def _email_admin_summary(job):
    old = format_amount(job.old_cost, job.currency)
    new = format_amount(job.new_cost, job.currency)
    headline = {
        Status.COMPLETED: "completed",
        Status.PARTIAL: "finished with failures",
        Status.INTERRUPTED: "was interrupted",
    }.get(job.status, job.status)
    subject = f"Price change for {job.plan.name} ({old} -> {new}) {headline}"

    lines = [
        f"{job.migrated_count} subscription(s) moved to the new price "
        f"{job.new_price_id}.",
    ]
    if job.remaining_count:
        lines.append(
            f"{job.remaining_count} still on the old price {job.old_price_id}."
        )
    lines.extend(
        f"{f['member'] or f['customer']} ({f['subscription']}): {f['error']}"
        for f in job.failures
    )
    if job.error:
        lines.append(job.error)
    if job.status != Status.COMPLETED:
        lines.append("Resume it from the plan's page in the admin tools.")

    try:
        send_email_to_admin(
            subject=subject,
            template_vars={"title": subject, "message": " ".join(lines)},
        )
    except Exception as e:
        capture_exception(e)
