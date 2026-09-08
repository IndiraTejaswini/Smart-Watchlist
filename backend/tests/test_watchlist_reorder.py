"""PATCH /api/watchlist/items/{symbol}/position — drag-to-reorder (12.6).

The fractional-index machinery (Task 7.3/7.4) already existed for *inserting*
a new item between two others; there was no endpoint that applied the same
midpoint math to *moving* an existing one, which is what a drag-to-reorder
gesture actually needs.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

USER_ID = "reorder_test_user"


@pytest.fixture(scope="module")
def engine():
    engine = sa.create_engine(get_settings().database_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 — any connection failure is a skip
        pytest.skip(f"postgres unreachable ({type(exc).__name__}); run `make up`")
    return engine


@pytest.fixture()
def watchlist_id(engine):
    wl_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO watchlists (id, user_id, name) VALUES (:id, :u, 'Default')"),
            {"id": wl_id, "u": USER_ID},
        )
        for symbol, position in (("AAA", "100"), ("BBB", "200"), ("CCC", "300")):
            conn.execute(
                sa.text(
                    "INSERT INTO watchlist_items (id, watchlist_id, symbol, position) "
                    "VALUES (:id, :w, :s, :p)"
                ),
                {"id": str(uuid4()), "w": wl_id, "s": symbol, "p": position},
            )
    yield wl_id
    with engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM watchlist_items WHERE watchlist_id = :w"), {"w": wl_id}
        )
        conn.execute(sa.text("DELETE FROM watchlists WHERE id = :w"), {"w": wl_id})


@pytest.fixture()
def client():
    return TestClient(create_app())


def _order(engine, watchlist_id: str) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                sa.text(
                    "SELECT symbol FROM watchlist_items WHERE watchlist_id = :w "
                    "ORDER BY position ASC"
                ),
                {"w": watchlist_id},
            ).scalars()
        )


def test_move_last_item_between_the_first_two(client, engine, watchlist_id) -> None:
    assert _order(engine, watchlist_id) == ["AAA", "BBB", "CCC"]
    response = client.patch(
        "/api/watchlist/items/CCC/position",
        json={"after_symbol": "AAA", "before_symbol": "BBB"},
        headers={"X-User-ID": USER_ID},
    )
    assert response.status_code == 200
    assert _order(engine, watchlist_id) == ["AAA", "CCC", "BBB"]


def test_move_to_the_front_has_no_after_symbol(client, engine, watchlist_id) -> None:
    response = client.patch(
        "/api/watchlist/items/CCC/position",
        json={"before_symbol": "AAA"},
        headers={"X-User-ID": USER_ID},
    )
    assert response.status_code == 200
    assert _order(engine, watchlist_id) == ["CCC", "AAA", "BBB"]


def test_move_to_the_back_has_no_before_symbol(client, engine, watchlist_id) -> None:
    # Fresh fixture state per test: AAA=100, BBB=200, CCC=300.
    response = client.patch(
        "/api/watchlist/items/AAA/position",
        json={"after_symbol": "CCC"},
        headers={"X-User-ID": USER_ID},
    )
    assert response.status_code == 200
    assert _order(engine, watchlist_id) == ["BBB", "CCC", "AAA"]


def test_reordering_a_symbol_not_on_the_list_404s(client, watchlist_id) -> None:
    response = client.patch(
        "/api/watchlist/items/NOTHERE/position",
        json={"after_symbol": "AAA"},
        headers={"X-User-ID": USER_ID},
    )
    assert response.status_code == 404


def test_reordering_without_x_user_id_400s(client) -> None:
    response = client.patch(
        "/api/watchlist/items/AAA/position",
        json={"after_symbol": None},
    )
    assert response.status_code == 400
