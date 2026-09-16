"""The cards in the welcome email and its admin preview."""

import json

import pytest
from constance.test import override_config
from django.urls import reverse

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
