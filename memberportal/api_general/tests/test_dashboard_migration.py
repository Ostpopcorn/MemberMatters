"""The one-off import of the HOME_PAGE_CARDS constance setting into DashboardCard.

The suite runs with --no-migrations, so the RunPython functions are called
directly against the current models.
"""

import importlib
import json

import pytest
from constance.backends.database.models import Constance
from django.apps import apps

from api_general.models import DashboardCard

migration = importlib.import_module(
    "api_general.migrations.0005_import_home_page_cards"
)

pytestmark = pytest.mark.django_db


def set_constance(key, value):
    Constance.objects.update_or_create(key=key, defaults={"value": value})


def run_import():
    migration.import_home_page_cards(apps, None)


def test_imports_each_legacy_link_shape_in_order():
    set_constance(
        "HOME_PAGE_CARDS",
        json.dumps(
            [
                {
                    "title": "Wiki",
                    "description": "<p>The <b>rule book</b>.</p>",
                    "icon": "mdi-book",
                    "url": "https://bms.wiki",
                    "btn_text": "Read Wiki",
                },
                {
                    "title": "Member Bucks",
                    "description": "Pay for things.",
                    "icon": "mdi-cash",
                    "routerLink": {"name": "memberbucks", "params": {"x": "y"}},
                    "btn_text": "Member Bucks",
                },
                {
                    "title": "Discord",
                    "description": "Chat.",
                    "icon": "mdi-chat",
                    "links": [
                        {"url": "https://a.example", "btn_text": "A", "newLine": True},
                        {"url": "https://b.example", "btn_text": "B"},
                    ],
                },
            ]
        ),
    )

    run_import()

    cards = [card.get_admin_object() for card in DashboardCard.objects.all()]
    for card in cards:
        del card["id"]
    assert cards == [
        {
            "title": "Wiki",
            "icon": "mdi-book",
            "description": "<p>The <b>rule book</b>.</p>",
            "links": [{"label": "Read Wiki", "url": "https://bms.wiki"}],
            "enabled": True,
            "position": 0,
        },
        {
            "title": "Member Bucks",
            "icon": "mdi-cash",
            "description": "Pay for things.",
            "links": [{"label": "Member Bucks", "route": "memberbucks"}],
            "enabled": True,
            "position": 1,
        },
        {
            "title": "Discord",
            "icon": "mdi-chat",
            "description": "Chat.",
            "links": [
                {"label": "A", "url": "https://a.example"},
                {"label": "B", "url": "https://b.example"},
            ],
            "enabled": True,
            "position": 2,
        },
    ]


def test_missing_setting_imports_nothing():
    run_import()

    assert not DashboardCard.objects.exists()


@pytest.mark.parametrize("value", ["not json", '{"title": "Wiki"}'])
def test_invalid_setting_imports_nothing(value):
    set_constance("HOME_PAGE_CARDS", value)

    run_import()

    assert not DashboardCard.objects.exists()


def test_reverse_deletes_the_cards():
    DashboardCard.objects.create(title="Wiki", icon="mdi-book")

    migration.delete_dashboard_cards(apps, None)

    assert not DashboardCard.objects.exists()
