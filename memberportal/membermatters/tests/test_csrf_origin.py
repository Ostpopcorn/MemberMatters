"""Pins how Django 4's CSRF Origin check treats the ways a POST reaches Django.

Since Django 4.0 the browser's Origin header has to match the scheme and host
Django believes it is serving, or be listed in CSRF_TRUSTED_ORIGINS. Members
authenticate with a session, so this applies to every change they make, not
just to the admin login form.
"""

import pytest
from django.test import Client

from tests.factories import ProfileFactory

# Any well-formed secret works: the check only needs cookie and token to agree.
CSRF_SECRET = "a" * 32

SOURCES = {
    # nginx as set up in docs/POST_INSTALL_STEPS.md
    "production proxy": {
        "HTTP_HOST": "portal.example.org",
        "HTTP_ORIGIN": "https://portal.example.org",
        "HTTP_REFERER": "https://portal.example.org/",
        "HTTP_X_FORWARDED_PROTO": "https",
    },
    # The case docs/UPGRADING.md warns about: TLS ends at the proxy, which
    # doesn't say so, so Django compares against http://portal.example.org.
    "proxy without X-Forwarded-Proto": {
        "HTTP_HOST": "portal.example.org",
        "HTTP_ORIGIN": "https://portal.example.org",
        "HTTP_REFERER": "https://portal.example.org/",
    },
    # quasar.config.js proxies /admin and /openid with changeOrigin: true
    "frontend dev server": {
        "HTTP_HOST": "127.0.0.1:8000",
        "HTTP_ORIGIN": "http://localhost:8080",
        "HTTP_REFERER": "http://localhost:8080/",
    },
    "another site": {
        "HTTP_HOST": "portal.example.org",
        "HTTP_ORIGIN": "https://attacker.example",
        "HTTP_REFERER": "https://attacker.example/",
        "HTTP_X_FORWARDED_PROTO": "https",
    },
}


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/logout/", "/admin/login/"])
@pytest.mark.parametrize(
    "source, rejected",
    [
        ("production proxy", False),
        ("proxy without X-Forwarded-Proto", True),
        ("frontend dev server", False),
        ("another site", True),
    ],
)
def test_csrf_origin_check(path, source, rejected):
    client = Client(enforce_csrf_checks=True)
    if path == "/api/logout/":
        # DRF only enforces CSRF on session-authenticated requests.
        client.force_login(ProfileFactory().user)
    client.cookies["csrftoken"] = CSRF_SECRET

    response = client.post(
        path,
        {"csrfmiddlewaretoken": CSRF_SECRET},
        HTTP_X_CSRFTOKEN=CSRF_SECRET,
        **SOURCES[source],
    )

    rejected_by_csrf = response.status_code == 403 and b"CSRF" in response.content
    assert rejected_by_csrf is rejected
