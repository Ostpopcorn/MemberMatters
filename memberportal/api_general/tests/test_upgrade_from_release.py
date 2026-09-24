"""Migrating a database from the last release (v3.8.0) to this branch.

A release has no dashboard cards yet (api_general 0004 onwards) and keeps its
settings in constance 2.9's constance_config table. This rolls the test
database back to that shape and migrates forward, as `migrate` does when the
container starts. It needs real migrations, so it only runs on the
--migrations leg.
"""

import json

import pytest
from constance.models import Constance
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from picklefield.fields import dbsafe_encode

from api_general.models import DashboardCard

pytestmark = pytest.mark.django_db(transaction=True)

LAST_RELEASE = [("api_general", "0003_auto_20211005_0015"), ("constance", None)]


def migrate(targets=None):
    executor = MigrationExecutor(connection)
    executor.migrate(targets or executor.loader.graph.leaf_nodes())


@pytest.fixture
def release_database(request):
    if request.config.getoption("nomigrations"):
        pytest.skip("needs real migrations; runs on the --migrations leg")

    migrate(LAST_RELEASE)
    yield
    migrate()  # leave the full schema for the tests that follow


def upgrade_in_one_go():
    migrate()


def upgrade_api_general_first():
    # The order this branch used before api_general 0006 existed: 0005 runs
    # while constance's table is still unmoved, so it can't import anything.
    migrate([("api_general", "0005_import_home_page_cards")])
    migrate([("constance", "0002_migrate_from_old_table")])
    migrate()


@pytest.mark.parametrize("upgrade", [upgrade_in_one_go, upgrade_api_general_first])
def test_a_release_keeps_its_settings_and_gets_its_dashboard_cards(
    release_database, upgrade
):
    cards = [
        {"title": "Wiki", "icon": "mdi-book", "url": "https://wiki.example"},
        {"title": "Chat", "icon": "mdi-chat", "url": "https://chat.example"},
    ]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE constance_config (id serial PRIMARY KEY, "
            f"{quote('key')} varchar(255) NOT NULL UNIQUE, value text NULL)"
        )
        cursor.executemany(
            f"INSERT INTO constance_config ({quote('key')}, value) VALUES (%s, %s)",
            [
                ("SITE_NAME", dbsafe_encode("Old Makerspace")),
                ("HOME_PAGE_CARDS", dbsafe_encode(json.dumps(cards))),
            ],
        )

    upgrade()

    assert Constance.objects.get(key="SITE_NAME").value == "Old Makerspace"
    assert list(DashboardCard.objects.values_list("title", flat=True)) == [
        "Wiki",
        "Chat",
    ]
    assert "constance_config" not in connection.introspection.table_names()
