"""The Member Resources cards in the public site config."""

import pytest
from django.urls import reverse

from api_general.models import DashboardCard

pytestmark = pytest.mark.django_db


def test_the_config_lists_the_enabled_cards_in_order(api_client):
    second = DashboardCard.objects.create(
        title="Second",
        icon="mdi-chat",
        position=2,
        links=[{"label": "Top up", "route": "memberbucks"}],
    )
    DashboardCard.objects.create(
        title="Hidden", icon="mdi-eye-off", position=1, enabled=False
    )
    first = DashboardCard.objects.create(
        title="First",
        icon="mdi-book",
        position=0,
        description="<p>The rule book.</p>",
        links=[{"label": "Read", "url": "https://bms.wiki"}],
    )

    response = api_client.get(reverse("get_config"))

    assert response.status_code == 200
    assert response.json()["dashboardCards"] == [
        {
            "id": first.id,
            "title": "First",
            "icon": "mdi-book",
            "description": "<p>The rule book.</p>",
            "links": [{"label": "Read", "url": "https://bms.wiki"}],
        },
        {
            "id": second.id,
            "title": "Second",
            "icon": "mdi-chat",
            "description": "",
            "links": [{"label": "Top up", "route": "memberbucks"}],
        },
    ]
    assert "homepageCards" not in response.json()
