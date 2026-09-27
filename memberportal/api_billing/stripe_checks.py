"""Checks behind the Stripe card on the admin Payment Overview page.

Each check is a row with the same shape as the admin Email delivery page uses:
key, label, status (ok, warning, error, info or unknown), value and detail.

The static checks only read MemberMatters' own settings. The connection test
calls Stripe with read-only requests: it never creates or changes anything
there, so it is safe to run against a live account.
"""

from urllib.parse import urlsplit

import stripe
from constance import config
from django.conf import settings
from django.urls import reverse

from api_billing.webhook_handlers import HANDLERS
from profile.models import Profile

OK, WARNING, ERROR, INFO, UNKNOWN = "ok", "warning", "error", "info", "unknown"
_SEVERITY = {OK: 0, INFO: 0, UNKNOWN: 1, WARNING: 2, ERROR: 3}

STRIPE_TIMEOUT_SECONDS = 10

HANDLED_EVENTS = sorted(HANDLERS)

SECRET_KEY_PREFIXES = {
    "sk_live_": ("Standard", "live"),
    "sk_test_": ("Standard", "test"),
    "rk_live_": ("Restricted", "live"),
    "rk_test_": ("Restricted", "test"),
}
PUBLISHABLE_KEY_PREFIXES = {"pk_live_": "live", "pk_test_": "test"}

# One cheap list call per Stripe resource MemberMatters uses, to find resources
# the key has no access to. Payment methods are left out: listing them needs a
# customer id.
PERMISSION_PROBES = [
    ("Customers", "customers"),
    ("Subscriptions", "subscriptions"),
    ("Invoices", "invoices"),
    ("Products", "products"),
    ("Prices", "prices"),
    ("Payment Intents", "payment_intents"),
    ("Setup Intents", "setup_intents"),
]

SKIPPED = "Skipped because the connection to Stripe failed."


def _row(key, label, status, value="", detail=""):
    return {
        "key": key,
        "label": label,
        "status": status,
        "value": value,
        "detail": detail,
    }


def _worst(rows):
    return max((row["status"] for row in rows), key=_SEVERITY.get, default=OK)


def _secret_key():
    """(kind, mode) of STRIPE_SECRET_KEY, or None if it isn't a secret key."""
    key = config.STRIPE_SECRET_KEY or ""
    for prefix, kind_and_mode in SECRET_KEY_PREFIXES.items():
        if key.startswith(prefix):
            return kind_and_mode
    return None


def _publishable_key_mode():
    key = config.STRIPE_PUBLISHABLE_KEY or ""
    for prefix, mode in PUBLISHABLE_KEY_PREFIXES.items():
        if key.startswith(prefix):
            return mode
    return None


def webhook_url():
    return config.SITE_URL.rstrip("/") + reverse("StripeWebhook")


def _webhooks_needed():
    """Webhooks drive membership payments, including subscriptions that are
    still running after membership payments were switched off."""
    return (
        config.ENABLE_STRIPE_MEMBERSHIP_PAYMENTS
        or Profile.objects.exclude(stripe_subscription_id__isnull=True)
        .exclude(stripe_subscription_id="")
        .exists()
    )


def _not_needed(rows):
    """Downgrade webhook problems to info when nothing uses webhooks."""
    for row in rows:
        if row["status"] in (WARNING, ERROR):
            row["status"] = INFO
            row["detail"] = (
                f"{row['detail']} Webhooks are only needed for membership "
                "payments, which are off, and no member has a Stripe "
                "subscription."
            ).strip()
    return rows


def _check_secret_key():
    label = "Secret key"
    key = config.STRIPE_SECRET_KEY or ""
    if not key:
        return _row(
            "secret_key",
            label,
            ERROR,
            "Not set",
            "STRIPE_SECRET_KEY is not set, so MemberMatters can't talk to Stripe.",
        )

    kind_and_mode = _secret_key()
    if kind_and_mode is None:
        detail = "Stripe secret keys start with rk_ (restricted) or sk_."
        if key.startswith("pk_"):
            detail = f"This is a publishable key. {detail}"
        return _row("secret_key", label, ERROR, "Not a Stripe secret key", detail)

    kind, mode = kind_and_mode
    value = f"{kind} key, {mode} mode"
    if kind == "Standard":
        return _row(
            "secret_key",
            label,
            WARNING,
            value,
            "A standard key can do anything in the Stripe account. Use a "
            "restricted key with only the permissions MemberMatters needs.",
        )
    return _row("secret_key", label, OK, value)


def _check_publishable_key():
    label = "Publishable key"
    key = config.STRIPE_PUBLISHABLE_KEY or ""
    if not key:
        return _row(
            "publishable_key",
            label,
            ERROR,
            "Not set",
            "STRIPE_PUBLISHABLE_KEY is not set, so members can't enter card "
            "details.",
        )

    mode = _publishable_key_mode()
    if mode is None:
        return _row(
            "publishable_key",
            label,
            ERROR,
            "Not a Stripe publishable key",
            "Stripe publishable keys start with pk_live_ or pk_test_.",
        )

    secret = _secret_key()
    if secret is not None and secret[1] != mode:
        return _row(
            "publishable_key",
            label,
            ERROR,
            f"{mode.capitalize()} mode",
            f"The secret key is in {secret[1]} mode. Both keys must come from "
            "the same mode, or card payments fail.",
        )
    return _row("publishable_key", label, OK, f"{mode.capitalize()} mode")


def _check_webhook_secret():
    label = "Webhook signing secret"
    secret = config.STRIPE_WEBHOOK_SECRET or ""
    if not secret:
        return _row(
            "webhook_secret",
            label,
            ERROR,
            "Not set",
            "STRIPE_WEBHOOK_SECRET is not set, so every webhook from Stripe "
            "is rejected.",
        )
    if not secret.startswith("whsec_"):
        return _row(
            "webhook_secret",
            label,
            WARNING,
            "Set",
            "Stripe signing secrets start with whsec_. Copy it from the "
            "webhook endpoint in the Stripe dashboard.",
        )
    return _row("webhook_secret", label, OK, "Set")


def _check_webhook_url():
    label = "Webhook URL"
    site_url = config.SITE_URL or ""
    if not site_url:
        return _row(
            "webhook_url",
            label,
            ERROR,
            "Unknown",
            "SITE_URL is not set, so the webhook address can't be worked out.",
        )

    url = webhook_url()
    if site_url.rstrip("/") == settings.CONSTANCE_CONFIG["SITE_URL"][0].rstrip("/"):
        return _row(
            "webhook_url",
            label,
            WARNING,
            url,
            "SITE_URL is still the default. Set it to the address this site "
            "is reached on.",
        )
    if urlsplit(url).scheme != "https":
        return _row(
            "webhook_url",
            label,
            WARNING,
            url,
            "Stripe only sends live mode webhooks to https addresses.",
        )
    return _row(
        "webhook_url",
        label,
        OK,
        url,
        "The Stripe webhook endpoint should point here.",
    )


def get_static_checks():
    """Checks that only read MemberMatters' settings; no call to Stripe."""
    if not config.ENABLE_STRIPE:
        return {
            "checks": [
                _row(
                    "stripe",
                    "Stripe",
                    INFO,
                    "Off",
                    "ENABLE_STRIPE is off, so MemberMatters doesn't use Stripe.",
                )
            ],
            "canTest": False,
        }

    webhook_rows = [_check_webhook_secret(), _check_webhook_url()]
    if not _webhooks_needed():
        _not_needed(webhook_rows)

    return {
        "checks": [
            _check_secret_key(),
            _check_publishable_key(),
            *webhook_rows,
            _row(
                "api_version",
                "API version",
                INFO,
                f"Enforced {settings.STRIPE_API_VERSION}",
                "MemberMatters sends this version with every Stripe request.",
            ),
        ],
        "canTest": _secret_key() is not None,
    }


def _http_client():
    return stripe.RequestsClient(timeout=STRIPE_TIMEOUT_SECONDS)


def _stripe_client():
    return stripe.StripeClient(
        config.STRIPE_SECRET_KEY,
        stripe_version=settings.STRIPE_API_VERSION,
        max_network_retries=0,
        http_client=_http_client(),
    )


def _error_text(error):
    return error.user_message or str(error) or type(error).__name__


def _check_connection(client, mode):
    """The connection row, and whether the rest of the test can go on."""
    label = "Connection"
    try:
        products = client.products.list(params={"limit": 1})
    except stripe.AuthenticationError as e:
        return (
            _row(
                "connection",
                label,
                ERROR,
                "Key rejected",
                f"Stripe rejected the secret key: {_error_text(e)}",
            ),
            False,
        )
    except stripe.PermissionError:
        # Authenticated, just not allowed to list products; the permissions
        # row reports that.
        return _row("connection", label, OK, f"Connected, {mode} mode"), True
    except stripe.APIConnectionError as e:
        return (
            _row(
                "connection",
                label,
                ERROR,
                "Can't reach Stripe",
                f"Could not connect to Stripe: {_error_text(e)}",
            ),
            False,
        )
    except stripe.StripeError as e:
        return (
            _row(
                "connection",
                label,
                ERROR,
                "Error",
                f"Stripe returned an error: {_error_text(e)}",
            ),
            False,
        )

    value = f"Connected, {mode} mode"
    headers = products.last_response.headers if products.last_response else {}
    answered = headers.get("Stripe-Version")
    if answered and answered != settings.STRIPE_API_VERSION:
        return (
            _row(
                "connection",
                label,
                WARNING,
                value,
                f"MemberMatters asked for API version "
                f"{settings.STRIPE_API_VERSION}, but Stripe answered in "
                f"{answered}.",
            ),
            True,
        )
    return _row("connection", label, OK, value), True


def _check_permissions(client):
    label = "Permissions"
    missing, unchecked = [], []
    for name, resource in PERMISSION_PROBES:
        try:
            getattr(client, resource).list(params={"limit": 1})
        except stripe.PermissionError:
            missing.append(name)
        except stripe.StripeError:
            unchecked.append(name)

    note = (
        "Only read access can be checked from here; MemberMatters also needs "
        "write access, and access to Payment Methods."
    )
    if missing:
        return _row(
            "permissions",
            label,
            ERROR,
            f"No access to {', '.join(missing)}",
            f"Give the key access to these in the Stripe dashboard. {note}",
        )
    if unchecked:
        return _row(
            "permissions",
            label,
            UNKNOWN,
            f"Couldn't check {', '.join(unchecked)}",
            f"Stripe returned an error for these. {note}",
        )
    return _row(
        "permissions",
        label,
        OK,
        f"Read access to all {len(PERMISSION_PROBES)} resources",
        note,
    )


def _near_miss(url, expected):
    """Why `url` is close to, but not, the webhook address; None if it isn't."""
    got, want = urlsplit(url), urlsplit(expected)
    same_host = got.netloc.lower() == want.netloc.lower()
    if same_host and got.scheme == want.scheme and got.path == want.path.rstrip("/"):
        return (
            f"{url} is missing the trailing slash. This site only takes "
            "webhooks at the address with the slash, so every delivery fails."
        )
    if same_host and got.path == want.path:
        return f"{url} uses {got.scheme} instead of {want.scheme}."
    if got.path == want.path:
        return (
            f"{url} points at {got.netloc}, but SITE_URL is {want.netloc}. "
            "One of them is wrong."
        )
    return None


def _webhook_version_row(endpoint):
    label = "Webhook API version"
    ours = settings.STRIPE_API_VERSION
    theirs = endpoint.api_version
    if not theirs:
        return _row(
            "webhook_api_version",
            label,
            WARNING,
            f"Enforced {ours}, endpoint sends the account default",
            "The endpoint isn't pinned to a version, so Stripe uses the "
            "account's default version, which changes when the account is "
            "upgraded in the Stripe dashboard.",
        )
    value = f"Enforced {ours}, endpoint sends {theirs}"
    if theirs != ours:
        return _row(
            "webhook_api_version",
            label,
            WARNING,
            value,
            "Webhook events arrive in a different API version than "
            "MemberMatters uses. An endpoint's version is set when it's "
            "created, so changing it means creating a new endpoint (with a "
            "new signing secret).",
        )
    return _row("webhook_api_version", label, OK, value)


def _check_endpoint(endpoint, duplicates):
    rows = []

    if duplicates:
        rows.append(
            _row(
                "webhook_endpoint_url",
                "Endpoint URL",
                WARNING,
                f"Found {duplicates + 1} endpoints",
                "Stripe sends every event to each of them, signed with each "
                "one's own secret, so only one can match STRIPE_WEBHOOK_SECRET "
                "and the others' deliveries are rejected. Delete the extras.",
            )
        )
    else:
        rows.append(_row("webhook_endpoint_url", "Endpoint URL", OK, "Found"))

    if endpoint.status == "enabled":
        rows.append(_row("webhook_endpoint_status", "Endpoint status", OK, "Enabled"))
    else:
        rows.append(
            _row(
                "webhook_endpoint_status",
                "Endpoint status",
                ERROR,
                endpoint.status.capitalize(),
                "Stripe isn't sending events to it. Enable it in the Stripe "
                "dashboard; Stripe can disable an endpoint whose deliveries "
                "keep failing.",
            )
        )

    enabled = set(endpoint.enabled_events or [])
    if "*" in enabled:
        rows.append(
            _row(
                "webhook_events",
                "Events",
                OK,
                "All events",
                f"MemberMatters uses {len(HANDLED_EVENTS)} of them and ignores "
                "the rest.",
            )
        )
    else:
        missing = [event for event in HANDLED_EVENTS if event not in enabled]
        if missing:
            rows.append(
                _row(
                    "webhook_events",
                    "Events",
                    ERROR,
                    f"Missing {len(missing)} of {len(HANDLED_EVENTS)}",
                    f"Add these events to the endpoint: {', '.join(missing)}.",
                )
            )
        else:
            extra = len(enabled) - len(HANDLED_EVENTS)
            rows.append(
                _row(
                    "webhook_events",
                    "Events",
                    OK,
                    f"All {len(HANDLED_EVENTS)} used by MemberMatters",
                    (
                        f"It also sends {extra} that MemberMatters ignores."
                        if extra
                        else ""
                    ),
                )
            )

    rows.append(_webhook_version_row(endpoint))
    return rows


def _webhook_verdict(rows):
    label = "Webhook setup"
    if not config.STRIPE_WEBHOOK_SECRET:
        return _row(
            "webhook",
            label,
            ERROR,
            "Signing secret missing",
            "The endpoint is there, but STRIPE_WEBHOOK_SECRET is not set, so "
            "every webhook is rejected.",
        )

    worst = _worst(rows)
    if worst == ERROR:
        return _row(
            "webhook", label, ERROR, "Not set up correctly", "See the rows below."
        )
    if worst == WARNING:
        return _row(
            "webhook",
            label,
            WARNING,
            "Set up, with warnings",
            "See the rows below.",
        )
    return _row(
        "webhook",
        label,
        OK,
        "Looks correctly set up",
        "Stripe doesn't show an endpoint's signing secret, so it couldn't be "
        "compared with STRIPE_WEBHOOK_SECRET.",
    )


def _check_webhook(client, mode):
    try:
        endpoints = list(
            client.webhook_endpoints.list(params={"limit": 100}).auto_paging_iter()
        )
    except stripe.PermissionError:
        return [
            _row(
                "webhook",
                "Webhook setup",
                UNKNOWN,
                "Can't check",
                "The key has no access to webhook endpoints. Give it read "
                "access to Webhook Endpoints to check them here.",
            )
        ]
    except stripe.StripeError as e:
        return [
            _row(
                "webhook",
                "Webhook setup",
                UNKNOWN,
                "Can't check",
                f"Stripe returned an error: {_error_text(e)}",
            )
        ]

    expected = webhook_url()
    matches = [endpoint for endpoint in endpoints if endpoint.url == expected]
    if not matches:
        near = [_near_miss(endpoint.url, expected) for endpoint in endpoints]
        near = [reason for reason in near if reason]
        if near:
            detail = " ".join(near)
        elif endpoints:
            others = ", ".join(endpoint.url for endpoint in endpoints)
            detail = f"Stripe has endpoints for other addresses: {others}."
        else:
            detail = f"Stripe has no webhook endpoints in {mode} mode."
        return [
            _row(
                "webhook",
                "Webhook setup",
                ERROR,
                "No endpoint for this site",
                f"No {mode} mode endpoint points at {expected}. {detail}",
            )
        ]

    # Prefer an enabled endpoint when there are several.
    matches.sort(key=lambda endpoint: endpoint.status != "enabled")
    rows = _check_endpoint(matches[0], duplicates=len(matches) - 1)
    return [_webhook_verdict(rows), *rows]


def run_connection_test():
    """Read-only calls to Stripe: the key, its permissions and the webhook
    endpoint."""
    if not config.ENABLE_STRIPE:
        return {"checks": [_row("connection", "Connection", INFO, "Stripe is off")]}

    kind_and_mode = _secret_key()
    if kind_and_mode is None:
        return {
            "checks": [
                _row(
                    "connection",
                    "Connection",
                    ERROR,
                    "Not tested",
                    "Set a valid STRIPE_SECRET_KEY first.",
                )
            ]
        }

    mode = kind_and_mode[1]
    client = _stripe_client()
    connection, connected = _check_connection(client, mode)
    if not connected:
        return {
            "checks": [
                connection,
                _row("permissions", "Permissions", UNKNOWN, "Skipped", SKIPPED),
                _row("webhook", "Webhook setup", UNKNOWN, "Skipped", SKIPPED),
            ]
        }

    webhook_rows = _check_webhook(client, mode)
    if not _webhooks_needed():
        _not_needed(webhook_rows)

    return {"checks": [connection, _check_permissions(client), *webhook_rows]}
