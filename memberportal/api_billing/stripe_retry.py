"""Retry wrapper for Stripe API calls made in bulk.

A one-off Stripe call in a request handler can simply fail and let the admin
or member click again. A bulk job (moving every subscription on a plan to a
new price) makes hundreds of calls, and over that many a transient failure —
a rate limit, a lock timeout on a subscription Stripe is renewing at that
moment, a dropped connection — stops being unlikely. This module decides
which of those are worth another attempt and how long to wait before it.

stripe-python has its own retries (`stripe.max_network_retries`), but they are
off by default, cap the wait at 2s and never retry an ordinary 429, so they do
not cover this case. This wrapper follows the same rules Stripe documents and
adds a longer, jittered backoff with an overall cap.

Every write retried here must carry an `idempotency_key`, or a retry after a
timeout that Stripe had in fact processed would apply the change twice.
"""

import dataclasses
import logging
import random
import time

import stripe

logger = logging.getLogger("billing")


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    # Total attempts including the first. With the defaults the waits are
    # roughly 0.5, 1, 2 and 4s (each jittered down by up to half), so a call
    # gives up after at most ~8s.
    max_attempts: int = 5
    base_delay: float = 0.5
    max_delay: float = 30.0
    # Stripe's rate limiter works per second, so retrying a 429 sooner than
    # this mostly just spends another request against the same limit.
    rate_limit_min_delay: float = 1.0
    # A Retry-After longer than this is not honoured. The call fails instead
    # of holding a worker for minutes.
    max_retry_after: float = 60.0


DEFAULT_POLICY = RetryPolicy()


def _header(error, name):
    # stripe-python hands back the transport's headers object, which is
    # case-insensitive for the requests client but a plain dict otherwise.
    for key, value in (getattr(error, "headers", None) or {}).items():
        if key.lower() == name:
            return value
    return None


def is_retryable(error):
    """True when retrying `error` with the same idempotency key may succeed."""
    if not isinstance(error, stripe.error.StripeError):
        return False

    # Stripe says explicitly whether a retry can help, e.g. "true" on a lock
    # timeout and "false" where the retry would replay the same failure.
    should_retry = _header(error, "stripe-should-retry")
    if should_retry == "true":
        return True
    if should_retry == "false":
        return False

    if isinstance(error, stripe.error.RateLimitError):
        return True
    if isinstance(error, stripe.error.APIConnectionError):
        # stripe-python sets this for timeouts and connection errors, and
        # leaves it False for e.g. TLS failures, which a retry won't fix.
        return bool(getattr(error, "should_retry", False))
    if isinstance(error, stripe.error.IdempotencyError):
        # The key was reused with different parameters: a bug, not a blip.
        return False

    status = error.http_status or 0
    # 409 is a conflicting concurrent request on the same object.
    return status == 409 or status >= 500


def _retry_after_seconds(error):
    value = _header(error, "retry-after")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def backoff_delay(attempt, error, policy=DEFAULT_POLICY, rng=random.random):
    """Seconds to wait after the `attempt`-th failed try (1-based).

    Exponential with "equal jitter": between half and all of the exponential
    step. The jitter keeps two workers that failed together from retrying in
    lockstep; the floor keeps a retry from following straight on the failure.
    """
    step = min(policy.max_delay, policy.base_delay * 2 ** (attempt - 1))
    delay = step / 2 + rng() * step / 2

    if isinstance(error, stripe.error.RateLimitError):
        delay = max(delay, policy.rate_limit_min_delay)

    retry_after = _retry_after_seconds(error)
    if retry_after is not None and retry_after <= policy.max_retry_after:
        delay = max(delay, retry_after)

    return delay


def call_with_retry(
    fn,
    *args,
    policy=DEFAULT_POLICY,
    sleep=None,
    rng=random.random,
    **kwargs,
):
    """Call `fn(*args, **kwargs)`, retrying transient Stripe failures.

    Re-raises the last StripeError once attempts run out or on the first error
    that a retry would not fix, so callers keep their usual
    `except stripe.error.StripeError` handling.
    """
    sleep = sleep or time.sleep
    name = getattr(fn, "__qualname__", repr(fn))
    attempt = 1
    while True:
        try:
            return fn(*args, **kwargs)
        except stripe.error.StripeError as error:
            if attempt >= policy.max_attempts or not is_retryable(error):
                raise
            delay = backoff_delay(attempt, error, policy, rng)
            logger.warning(
                "Stripe %s failed (attempt %d/%d, %s); retrying in %.1fs.",
                name,
                attempt,
                policy.max_attempts,
                repr(error),
                delay,
            )
            sleep(delay)
            attempt += 1
