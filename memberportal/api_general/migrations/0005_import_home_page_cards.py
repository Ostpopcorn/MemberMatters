import json
import re

from django.db import migrations

from services.sanitize import clean_html

# Only Material Design Icons are loaded, so any other name showed no icon.
ICON_NAME = re.compile(r"mdi-[a-z0-9-]+")
DEFAULT_ICON = "mdi-link-variant"


def legacy_links(card):
    """Converts a HOME_PAGE_CARDS card's link to DashboardCard.links.

    The precedence mirrors the old DashboardCard.vue: routerLink, then url, then
    the links list. Links with no target are dropped, and a missing button text
    falls back to the card's title, so every imported card can be saved again.
    """
    title = card.get("title") or ""

    router_link = card.get("routerLink")
    if isinstance(router_link, dict) and router_link.get("name"):
        return [{"label": card.get("btn_text") or title, "route": router_link["name"]}]

    if card.get("url"):
        return [{"label": card.get("btn_text") or title, "url": card["url"]}]

    return [
        {"label": link.get("btn_text") or title, "url": link["url"]}
        for link in card.get("links") or []
        if isinstance(link, dict) and link.get("url")
    ]


def import_home_page_cards(apps, schema_editor):
    Constance = apps.get_model("database", "Constance")
    DashboardCard = apps.get_model("api_general", "DashboardCard")

    home_page_cards = Constance.objects.filter(key="HOME_PAGE_CARDS").first()
    if home_page_cards is None:
        # Never customised, so the dashboard showed constance's placeholder cards.
        return

    try:
        cards = json.loads(home_page_cards.value)
    except (TypeError, ValueError):
        cards = None

    if not isinstance(cards, list):
        print(
            "\n  HOME_PAGE_CARDS is not a valid JSON array, so no dashboard cards "
            "were imported. Recreate them in Admin Tools -> Dashboard Cards."
        )
        return

    DashboardCard.objects.bulk_create(
        DashboardCard(
            position=position,
            title=(card.get("title") or "")[:255],
            icon=(
                card["icon"]
                if ICON_NAME.fullmatch(str(card.get("icon") or ""))
                else DEFAULT_ICON
            )[:100],
            description=clean_html(card.get("description")),
            links=legacy_links(card),
        )
        for position, card in enumerate(c for c in cards if isinstance(c, dict))
    )


def delete_dashboard_cards(apps, schema_editor):
    apps.get_model("api_general", "DashboardCard").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("api_general", "0004_dashboardcard"),
        ("database", "0002_auto_20190129_2304"),
    ]

    operations = [
        migrations.RunPython(import_home_page_cards, delete_dashboard_cards),
    ]
