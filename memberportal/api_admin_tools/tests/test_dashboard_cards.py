"""Admin API for the Member Resources cards on the dashboard."""

import pytest
from django.urls import reverse

from api_general.models import DashboardCard

pytestmark = pytest.mark.django_db

LIST_URL = reverse("DashboardCards")
ORDER_URL = reverse("DashboardCardOrder")


def detail_url(card_id):
    return reverse("DashboardCardDetail", args=[card_id])


def make_card(**fields):
    return DashboardCard.objects.create(
        **{"title": "Wiki", "icon": "mdi-book", **fields}
    )


def new_card(**fields):
    return {
        "title": "Wiki",
        "icon": "mdi-book",
        "description": "<p>The rule book.</p>",
        "links": [{"label": "Read", "url": "https://bms.wiki"}],
        **fields,
    }


@pytest.mark.parametrize(
    "method, url",
    [
        ("get", LIST_URL),
        ("post", LIST_URL),
        ("put", "detail"),
        ("delete", "detail"),
        ("put", ORDER_URL),
    ],
)
def test_a_non_admin_is_refused(authed_client, method, url):
    card = make_card()
    if url == "detail":
        url = detail_url(card.id)

    response = getattr(authed_client, method)(url, {}, format="json")

    assert response.status_code == 403
    assert DashboardCard.objects.get().title == "Wiki"


def test_lists_every_card_in_order_including_disabled(admin_client):
    second = make_card(title="Second", position=1, enabled=False)
    first = make_card(title="First", position=0)

    response = admin_client.get(LIST_URL)

    assert response.status_code == 200
    assert response.json() == [first.get_admin_object(), second.get_admin_object()]


def test_the_first_card_goes_to_position_zero(admin_client):
    response = admin_client.post(LIST_URL, new_card(), format="json")

    assert response.status_code == 201
    card = DashboardCard.objects.get()
    assert response.json() == card.get_admin_object()
    assert card.position == 0
    assert card.enabled is True


def test_a_new_card_goes_after_the_last_one(admin_client):
    make_card(position=0)
    make_card(position=5)

    response = admin_client.post(LIST_URL, new_card(title="New"), format="json")

    assert response.status_code == 201
    assert DashboardCard.objects.get(title="New").position == 6


@pytest.mark.parametrize(
    "fields",
    [{"title": ""}, {"title": None}, {"icon": ""}, {"icon": None}],
)
def test_title_and_icon_are_required(admin_client, fields):
    card = {
        key: value for key, value in new_card(**fields).items() if value is not None
    }

    response = admin_client.post(LIST_URL, card, format="json")

    assert response.status_code == 400
    assert set(response.json()) == set(fields)
    assert not DashboardCard.objects.exists()


@pytest.mark.parametrize(
    "links",
    [
        pytest.param("https://bms.wiki", id="not-a-list"),
        pytest.param(["https://bms.wiki"], id="not-an-object"),
        pytest.param([{"url": "https://bms.wiki"}], id="no-label"),
        pytest.param([{"label": " ", "url": "https://bms.wiki"}], id="blank-label"),
        pytest.param([{"label": "Read"}], id="no-target"),
        pytest.param(
            [{"label": "Read", "url": "https://bms.wiki", "route": "memberbucks"}],
            id="url-and-route",
        ),
        pytest.param(
            [{"label": "Read", "url": "javascript:alert(1)"}], id="javascript"
        ),
        pytest.param(
            [{"label": "Read", "url": " JavaScript:alert(1)"}],
            id="javascript-padded",
        ),
        pytest.param([{"label": "Read", "url": "/memberbucks"}], id="relative-url"),
        pytest.param([{"label": "Read", "url": 5}], id="non-string-url"),
        pytest.param([{"label": "Read", "route": "a/b"}], id="bad-route"),
    ],
)
def test_invalid_links_are_rejected(admin_client, links):
    response = admin_client.post(LIST_URL, new_card(links=links), format="json")

    assert response.status_code == 400
    assert set(response.json()) == {"links"}
    assert not DashboardCard.objects.exists()


def test_valid_links_are_stored_trimmed_and_without_extra_keys(admin_client):
    links = [
        {"label": " Wiki ", "url": " https://bms.wiki ", "newLine": True},
        {"label": "Top up", "route": "memberbucks"},
        {"label": "Email us", "url": "mailto:hello@example.org"},
    ]

    response = admin_client.post(LIST_URL, new_card(links=links), format="json")

    assert response.status_code == 201
    assert DashboardCard.objects.get().links == [
        {"label": "Wiki", "url": "https://bms.wiki"},
        {"label": "Top up", "route": "memberbucks"},
        {"label": "Email us", "url": "mailto:hello@example.org"},
    ]


def test_the_description_is_sanitized(admin_client):
    description = (
        '<div><b>Bold</b></div><script>alert(1)</script><p onclick="x">Hi</p>'
        '<ul><li><a href="javascript:alert(1)">bad</a></li></ul>'
    )

    response = admin_client.post(
        LIST_URL, new_card(description=description), format="json"
    )

    assert response.status_code == 201
    assert DashboardCard.objects.get().description == (
        '<div><b>Bold</b></div><p>Hi</p><ul><li><a rel="noopener noreferrer">bad</a>'
        "</li></ul>"
    )


def test_an_update_changes_only_the_given_fields(admin_client):
    card = make_card(position=3, description="<p>Keep me.</p>")

    response = admin_client.put(detail_url(card.id), {"enabled": False}, format="json")

    assert response.status_code == 200
    card.refresh_from_db()
    assert response.json() == card.get_admin_object()
    assert card.enabled is False
    assert (card.title, card.position, card.description) == (
        "Wiki",
        3,
        "<p>Keep me.</p>",
    )


def test_an_update_is_validated(admin_client):
    card = make_card(links=[{"label": "Read", "url": "https://bms.wiki"}])

    response = admin_client.put(
        detail_url(card.id),
        {"title": "New", "links": [{"label": "Read", "url": "javascript:alert(1)"}]},
        format="json",
    )

    assert response.status_code == 400
    card.refresh_from_db()
    assert card.title == "Wiki"
    assert card.links == [{"label": "Read", "url": "https://bms.wiki"}]


def test_delete_removes_the_card(admin_client):
    card = make_card()
    other = make_card(title="Other")

    response = admin_client.delete(detail_url(card.id))

    assert response.status_code == 200
    assert list(DashboardCard.objects.all()) == [other]


@pytest.mark.parametrize("method", ["put", "delete"])
def test_an_unknown_card_is_not_found(admin_client, method):
    response = getattr(admin_client, method)(detail_url(999), {}, format="json")

    assert response.status_code == 404


def test_reorder_sets_every_position(admin_client):
    a = make_card(title="A", position=0)
    b = make_card(title="B", position=1)
    c = make_card(title="C", position=2)

    response = admin_client.put(ORDER_URL, {"ids": [c.id, a.id, b.id]}, format="json")

    assert response.status_code == 200
    assert [card["title"] for card in response.json()] == ["C", "A", "B"]
    assert [card.title for card in DashboardCard.objects.all()] == ["C", "A", "B"]
    assert [card.position for card in DashboardCard.objects.all()] == [0, 1, 2]


@pytest.mark.parametrize(
    "ids",
    [
        pytest.param(lambda a, b: [a], id="missing-card"),
        pytest.param(lambda a, b: [b, a, 999], id="unknown-card"),
        pytest.param(lambda a, b: [b, a, a], id="duplicate"),
        pytest.param(lambda a, b: "nope", id="not-a-list"),
    ],
)
def test_reorder_must_list_every_card_exactly_once(admin_client, ids):
    a = make_card(title="A", position=0)
    b = make_card(title="B", position=1)

    response = admin_client.put(ORDER_URL, {"ids": ids(a.id, b.id)}, format="json")

    assert response.status_code == 400
    assert set(response.json()) == {"ids"}
    assert [card.title for card in DashboardCard.objects.all()] == ["A", "B"]
