"""The welcome email: its cards, its admin preview and the members' page."""

import json

import pytest
from constance.test import override_config
from django.urls import reverse
from rest_framework.test import APIClient

from api_general.models import DashboardCard
from profile.models import welcome_email_cards
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

CARDS = [
    {
        "title": "Wiki",
        "description": "<p>The rule book.</p>",
        "url": "https://bms.wiki",
        "btn_text": "Read Wiki",
    }
]


@pytest.fixture
def dashboard_cards():
    DashboardCard.objects.create(
        title="Discord",
        icon="mdi-chat",
        position=0,
        description="<p>Chat.</p>",
        links=[
            {"label": "Top up", "route": "memberbucks"},
            {"label": "Join", "url": "https://discord.example"},
            {"label": "Other", "url": "https://other.example"},
        ],
    )
    DashboardCard.objects.create(
        title="Member Bucks",
        icon="mdi-cash",
        position=1,
        links=[{"label": "Top up", "route": "memberbucks"}],
    )
    DashboardCard.objects.create(
        title="Hidden", icon="mdi-eye-off", position=2, enabled=False
    )


@override_config(WELCOME_EMAIL_CARDS=json.dumps(CARDS))
def test_the_configured_cards_are_used(outbox, dashboard_cards):
    ProfileFactory().user.email_welcome()

    assert welcome_email_cards() == CARDS
    assert "Read Wiki" in outbox[-1]["HtmlBody"]
    assert "Discord" not in outbox[-1]["HtmlBody"]


@override_config(WELCOME_EMAIL_CARDS="")
def test_blank_falls_back_to_the_enabled_dashboard_cards(outbox, dashboard_cards):
    ProfileFactory().user.email_welcome()

    assert welcome_email_cards() == [
        {
            "title": "Discord",
            "description": "<p>Chat.</p>",
            "url": "https://discord.example",
            "btn_text": "Join",
        },
        {"title": "Member Bucks", "description": "", "url": "", "btn_text": ""},
    ]
    html = outbox[-1]["HtmlBody"]
    assert "Join" in html and "Member Bucks" in html and "Hidden" not in html
    # A card with no website link gets no button rather than an empty one.
    assert 'href=""' not in html


@override_config(WELCOME_EMAIL_CARDS="", SITE_URL="https://portal.example.org")
def test_a_path_on_this_site_becomes_a_full_link():
    DashboardCard.objects.create(
        title="Rules",
        icon="mdi-book",
        links=[{"label": "Read", "url": "/static/rules.pdf"}],
    )

    assert welcome_email_cards()[0]["url"] == (
        "https://portal.example.org/static/rules.pdf"
    )


def test_the_default_uses_the_dashboard_cards(dashboard_cards):
    assert [card["title"] for card in welcome_email_cards()] == [
        "Discord",
        "Member Bucks",
    ]


@override_config(WELCOME_EMAIL_CARDS="[]")
def test_an_empty_list_means_no_cards(dashboard_cards):
    assert welcome_email_cards() == []


@pytest.mark.parametrize("value", ["not json", '{"title": "Wiki"}'])
def test_invalid_cards_become_no_cards_and_the_email_still_sends(
    outbox, dashboard_cards, value
):
    with override_config(WELCOME_EMAIL_CARDS=value):
        assert welcome_email_cards() == []
        assert ProfileFactory().user.email_welcome()

    assert len(outbox) == 1


@pytest.mark.parametrize("value", ["", "not json"])
def test_the_signup_preview_matches_the_email(admin_client, dashboard_cards, value):
    with override_config(WELCOME_EMAIL_CARDS=value):
        response = admin_client.get(reverse("SignupPreview"))

    assert response.status_code == 200
    assert ("Discord" in response.json()["welcomeEmailHtml"]) is (value == "")


def client_for(profile):
    client = APIClient()
    client.force_authenticate(user=profile.user)
    return client


@pytest.mark.parametrize(
    "state, page_enabled, allowed",
    [
        ("active", True, True),
        ("noob", True, False),
        ("inactive", True, False),
        ("active", False, False),
    ],
)
def test_only_active_members_see_the_welcome_email_page(state, page_enabled, allowed):
    client = client_for(ProfileFactory(state=state))

    with override_config(ENABLE_WELCOME_EMAIL_PAGE=page_enabled):
        response = client.get(reverse("WelcomeEmail"))

    assert response.status_code == (200 if allowed else 403)


def test_the_welcome_email_page_shows_the_email_as_sent(outbox, dashboard_cards):
    member = ProfileFactory(active=True)
    member.user.email_welcome()

    response = client_for(member).get(reverse("WelcomeEmail"))

    assert response.json()["welcomeEmailHtml"] == outbox[-1]["HtmlBody"]
