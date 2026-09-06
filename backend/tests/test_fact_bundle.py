"""FactBundle immutability, loading, and cache tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.analytics.fact_bundle import (
    AnnouncementFact,
    DailyBarFact,
    FactBundle,
    MarketModelFact,
)
from app.analytics.fact_bundle_loader import get_cold_fact_bundle


def test_fact_bundle_is_frozen_and_complete() -> None:
    bundle = FactBundle(
        symbol="AAA",
        date=date(2026, 9, 6),
        market_model=MarketModelFact(
            Decimal("0.1"), Decimal("1.2"), Decimal("0.4"),
            Decimal("0.01"), 120, "CLEAN",
        ),
        current_bar=DailyBarFact(Decimal("100.1234"), Decimal("1000"), 10),
        recent_announcements=(
            AnnouncementFact(
                datetime(2026, 9, 6, tzinfo=UTC),
                "Subject", "RESULT", None,
            ),
        ),
        completeness=frozenset({"BARS", "MARKET_MODEL", "ANNOUNCEMENTS"}),
    )
    assert bundle.is_complete({"BARS", "MARKET_MODEL"})
    with pytest.raises(AttributeError):
        bundle.symbol = "BBB"  # type: ignore[misc]


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl = 0

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttl = ttl


class _Result:
    def mappings(self):
        return self

    def first(self):
        return None

    def __iter__(self):
        return iter(())


class _Db:
    def execute(self, statement, params):
        return _Result()


def test_empty_db_bundle_degrades_and_round_trips_cache() -> None:
    redis = _Redis()
    bundle = get_cold_fact_bundle(redis, _Db(), "NEW", date(2026, 9, 6))
    assert bundle.market_model is None
    assert not bundle.is_complete({"BARS", "MARKET_MODEL"})
    assert redis.ttl == 86400
    cached = get_cold_fact_bundle(redis, _Db(), "NEW", date(2026, 9, 6))
    assert cached == bundle


def test_fact_bundle_downstream_purity(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = FactBundle(
        symbol="PURE",
        date=date(2026, 9, 6),
        completeness=frozenset({"BARS", "MARKET_MODEL"}),
    )

    def impure(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Impure call detected")

    monkeypatch.setattr("time.time", impure)
    monkeypatch.setattr("random.random", impure)
    monkeypatch.setattr("socket.socket", impure)
    assert bundle.is_complete({"BARS"})
