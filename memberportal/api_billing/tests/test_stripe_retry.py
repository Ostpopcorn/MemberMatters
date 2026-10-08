"""call_with_retry: which Stripe failures get another attempt, and how long
it waits before each one.

No database and no network: the wrapped function is a stub that raises the
errors stripe-python would.
"""

import pytest
import stripe

from api_billing.stripe_retry import (
    RetryPolicy,
    backoff_delay,
    call_with_retry,
    is_retryable,
)


def rate_limited(headers=None):
    return stripe.error.RateLimitError(
        "Too many requests", http_status=429, headers=headers
    )


def connection_dropped():
    # stripe-python sets should_retry for timeouts and resets.
    return stripe.error.APIConnectionError("Connection reset", should_retry=True)


def server_error(status=500, headers=None):
    return stripe.error.APIError("Server error", http_status=status, headers=headers)


def invalid_request():
    return stripe.error.InvalidRequestError(
        "No such price", param="items", http_status=400
    )


TRANSIENT = [
    pytest.param(rate_limited, id="rate-limit"),
    pytest.param(connection_dropped, id="connection-dropped"),
    pytest.param(lambda: server_error(500), id="500"),
    pytest.param(lambda: server_error(503), id="503"),
    pytest.param(lambda: server_error(409), id="409-conflict"),
    pytest.param(
        lambda: stripe.error.InvalidRequestError(
            "Lock timeout",
            param=None,
            http_status=400,
            headers={"Stripe-Should-Retry": "true"},
        ),
        id="stripe-says-retry",
    ),
]

PERMANENT = [
    pytest.param(invalid_request, id="invalid-request"),
    pytest.param(
        lambda: stripe.error.CardError("Declined", param=None, code="card_declined"),
        id="card-declined",
    ),
    pytest.param(
        lambda: stripe.error.AuthenticationError("Bad key", http_status=401),
        id="bad-key",
    ),
    pytest.param(
        lambda: stripe.error.PermissionError("Forbidden", http_status=403),
        id="permission",
    ),
    pytest.param(
        lambda: stripe.error.IdempotencyError("Key reused", http_status=400),
        id="idempotency-key-reused",
    ),
    pytest.param(
        lambda: stripe.error.APIConnectionError("TLS failure", should_retry=False),
        id="connection-not-retryable",
    ),
    pytest.param(
        lambda: server_error(500, headers={"stripe-should-retry": "false"}),
        id="stripe-says-dont-retry",
    ),
]


class FlakyCall:
    """Raises each of `errors` in turn, then returns "ok"."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


class Sleeps(list):
    def sleep(self, seconds):
        self.append(seconds)


@pytest.fixture
def sleeper():
    return Sleeps()


@pytest.mark.parametrize("make_error", TRANSIENT)
def test_a_transient_failure_is_retried(make_error, sleeper):
    call = FlakyCall(make_error(), make_error())

    assert call_with_retry(call, sleep=sleeper.sleep) == "ok"
    assert len(call.calls) == 3
    assert len(sleeper) == 2


@pytest.mark.parametrize("make_error", PERMANENT)
def test_a_permanent_failure_is_raised_without_retrying(make_error, sleeper):
    error = make_error()
    call = FlakyCall(error)

    with pytest.raises(type(error)):
        call_with_retry(call, sleep=sleeper.sleep)
    assert len(call.calls) == 1
    assert sleeper == []


def test_gives_up_after_max_attempts_and_raises_the_last_error(sleeper):
    errors = [rate_limited() for _ in range(3)]
    call = FlakyCall(*errors)

    with pytest.raises(stripe.error.RateLimitError) as raised:
        call_with_retry(call, policy=RetryPolicy(max_attempts=3), sleep=sleeper.sleep)
    assert raised.value is errors[-1]
    assert len(call.calls) == 3
    assert len(sleeper) == 2


def test_every_attempt_sends_the_same_arguments_and_idempotency_key(sleeper):
    """The key is what makes retrying a write safe: a retry after a timeout
    Stripe had in fact processed returns the first result, not a second
    change."""
    call = FlakyCall(connection_dropped(), server_error())

    call_with_retry(
        call, "sub_1", items=[{"price": "p"}], idempotency_key="k1", sleep=sleeper.sleep
    )
    assert (
        call.calls
        == [(("sub_1",), {"items": [{"price": "p"}], "idempotency_key": "k1"})] * 3
    )


def test_errors_that_are_not_from_stripe_propagate_immediately(sleeper):
    call = FlakyCall(ValueError("bug"))

    with pytest.raises(ValueError):
        call_with_retry(call, sleep=sleeper.sleep)
    assert len(call.calls) == 1


def test_non_stripe_exceptions_are_not_retryable():
    assert is_retryable(ValueError()) is False


def test_backoff_doubles_each_attempt_within_its_jitter_band():
    policy = RetryPolicy(base_delay=0.5, max_delay=30)
    error = server_error()

    for attempt, step in [(1, 0.5), (2, 1.0), (3, 2.0), (4, 4.0)]:
        assert backoff_delay(attempt, error, policy, rng=lambda: 0.0) == step / 2
        assert backoff_delay(attempt, error, policy, rng=lambda: 1.0) == step


def test_backoff_is_capped_at_max_delay():
    policy = RetryPolicy(base_delay=0.5, max_delay=3)
    assert backoff_delay(10, server_error(), policy, rng=lambda: 1.0) == 3


def test_a_rate_limit_waits_at_least_the_rate_limit_floor():
    policy = RetryPolicy(base_delay=0.1, rate_limit_min_delay=1.0)
    assert backoff_delay(1, rate_limited(), policy, rng=lambda: 0.0) == 1.0


@pytest.mark.parametrize("header", ["Retry-After", "retry-after"])
def test_retry_after_is_honoured(header):
    policy = RetryPolicy(base_delay=0.5)
    error = rate_limited(headers={header: "7"})
    assert backoff_delay(1, error, policy, rng=lambda: 0.0) == 7


def test_an_excessive_retry_after_is_ignored_rather_than_blocking_the_worker():
    policy = RetryPolicy(base_delay=0.5, max_retry_after=60, rate_limit_min_delay=1)
    error = rate_limited(headers={"Retry-After": "3600"})
    assert backoff_delay(1, error, policy, rng=lambda: 0.0) == 1


def test_an_unparseable_retry_after_is_ignored():
    policy = RetryPolicy(base_delay=0.5)
    error = server_error(headers={"Retry-After": "soon"})
    assert backoff_delay(1, error, policy, rng=lambda: 0.0) == 0.25
