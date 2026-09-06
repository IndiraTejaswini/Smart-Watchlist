from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.api.watchlist import parse_if_match_header
from app.crud.watchlist import update_watchlist


def test_parse_if_match_header_supports_strong_and_weak_etags() -> None:
    assert parse_if_match_header('"1"') == 1
    assert parse_if_match_header(' W/"2" ') == 2


def test_parse_if_match_header_requires_a_valid_value() -> None:
    with pytest.raises(HTTPException) as missing:
        parse_if_match_header(None)
    assert missing.value.status_code == 428

    with pytest.raises(HTTPException) as invalid:
        parse_if_match_header("not-a-version")
    assert invalid.value.status_code == 400


def test_update_watchlist_uses_atomic_version_compare_and_swap() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE watchlists ("
                "id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(64) NOT NULL, "
                "name VARCHAR(64) NOT NULL, version INTEGER NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        now = datetime.now(UTC)
        connection.execute(
            sa.text(
                "INSERT INTO watchlists "
                "(id, user_id, name, version, created_at, updated_at) "
                "VALUES ('wl-1', 'USER', 'Alpha', 1, :now, :now)"
            ),
            {"now": now},
        )

    with engine.begin() as connection:
        updated = update_watchlist(connection, "wl-1", "Alpha Prime", 1)
        assert updated.name == "Alpha Prime"
        assert updated.version == 2

    with engine.begin() as connection:
        with pytest.raises(HTTPException) as conflict:
            update_watchlist(connection, "wl-1", "Beta Overwrite", 1)
        assert conflict.value.status_code == 409
        assert conflict.value.detail["current_version"] == 2

        current = connection.execute(
            sa.text("SELECT name, version FROM watchlists WHERE id = 'wl-1'")
        ).one()
        assert current.name == "Alpha Prime"
        assert current.version == 2
