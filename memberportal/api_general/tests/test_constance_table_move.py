"""api_general 0006: finishing django-constance 3.1's move to constance_constance.

On MySQL and MariaDB, constance's own copy fails without an error and leaves
every setting in constance_config. These tests recreate that state and run the
repair directly, as the suite runs with --no-migrations.
"""

import importlib
from types import SimpleNamespace

import pytest
from constance.models import Constance
from django.apps import apps
from django.db import connection
from picklefield.fields import dbsafe_encode

migration = importlib.import_module(
    "api_general.migrations.0006_finish_constance_table_move"
)

pytestmark = pytest.mark.django_db


def leave_settings_in_the_old_table(settings):
    quote = connection.ops.quote_name
    table, id_, key, value = (
        quote(name) for name in ("constance_config", "id", "key", "value")
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE TABLE {table} ({id_} integer PRIMARY KEY, "
            f"{key} varchar(255) NOT NULL UNIQUE, {value} text NULL)"
        )
        cursor.executemany(
            f"INSERT INTO {table} ({id_}, {key}, {value}) VALUES (%s, %s, %s)",
            [
                (row_id, name, dbsafe_encode(setting))
                for row_id, (name, setting) in enumerate(settings.items(), start=1)
            ],
        )


def run_repair():
    migration.finish_constance_table_move(apps, SimpleNamespace(connection=connection))


def old_table_exists():
    return "constance_config" in connection.introspection.table_names()


def saved_settings():
    return {row.key: row.value for row in Constance.objects.all()}


def test_settings_left_in_the_old_table_are_moved():
    leave_settings_in_the_old_table({"SITE_NAME": "Old Makerspace", "ENABLE_X": True})

    run_repair()

    assert saved_settings() == {"SITE_NAME": "Old Makerspace", "ENABLE_X": True}
    assert not old_table_exists()


def test_defaults_written_since_the_failed_move_are_replaced():
    # Reading a setting constance can't find stores its default, so a portal
    # that ran on the empty table has filled it with defaults.
    Constance.objects.create(key="SITE_NAME", value="MemberMatters Portal")
    Constance.objects.create(key="ENABLE_Y", value=False)
    leave_settings_in_the_old_table({"SITE_NAME": "Old Makerspace", "ENABLE_X": True})

    run_repair()

    assert saved_settings() == {
        "SITE_NAME": "Old Makerspace",
        "ENABLE_X": True,
        "ENABLE_Y": False,
    }


def test_nothing_happens_once_the_old_table_is_gone():
    Constance.objects.create(key="SITE_NAME", value="Makerspace")

    run_repair()

    assert saved_settings() == {"SITE_NAME": "Makerspace"}
