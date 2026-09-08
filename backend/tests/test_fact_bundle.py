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
    """R2: the signal engine — MPM gate, abnormality layer, candidate
    generation — must never touch the clock, randomness, the network, or
    the DB. Every input arrives on the FactBundle.

    A bundle carrying only ``completeness`` proves nothing about the
    functions that actually consume one, so this drives the real chain:
    evaluate_mpm_gate -> compute_abnormality_bundle -> generate_candidate,
    with every impure symbol R2 names patched to explode on contact.
    """
    from app.analytics.abnormality import compute_abnormality_bundle
    from app.analytics.candidates import generate_candidate
    from app.analytics.fact_bundle import (
        DeliveryBaselineFact,
        ExtremesAdvFact,
        TurnoverBaselineFact,
    )
    from app.analytics.mpm import evaluate_mpm_gate
    from app.timeutil import TradingCalendar

    bundle = FactBundle(
        symbol="PURE",
        date=date(2026, 9, 8),
        market_model=MarketModelFact(
            Decimal("0.001"), Decimal("1.1"), Decimal("0.4"),
            Decimal("0.02"), 120, "CLEAN",
        ),
        turnover_baseline=TurnoverBaselineFact(
            Decimal("14.0"), Decimal("0.3"), 20, "CLEAN"
        ),
        delivery_baseline=DeliveryBaselineFact(
            Decimal("42.0"), Decimal("0.1"), Decimal("0.05"),
            Decimal("0.2"), Decimal("0.5"), 20, "CLEAN",
        ),
        extremes=ExtremesAdvFact(
            Decimal("120.0"), Decimal("80.0"), Decimal("-5.0"),
            Decimal("25.0"), Decimal("50000000"),
        ),
        current_bar=DailyBarFact(
            adj_close=Decimal("105.0"),
            turnover=Decimal("60000000"),
            volume=500000,
            adj_prev_close=Decimal("100.0"),
        ),
        completeness=frozenset({"BARS", "MARKET_MODEL"}),
    )
    calendar = TradingCalendar.from_rows(
        [
            {"calendar_date": date(2026, 9, 7), "is_trading_day": True, "session_type": "REGULAR"},
            {"calendar_date": date(2026, 9, 8), "is_trading_day": True, "session_type": "REGULAR"},
        ]
    )

    def impure(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Impure call detected")

    monkeypatch.setattr("time.time", impure)
    monkeypatch.setattr("random.random", impure)
    monkeypatch.setattr("uuid.uuid4", impure)
    monkeypatch.setattr("socket.socket", impure)
    monkeypatch.setattr("os.environ.get", impure)
    # datetime.datetime/date are C types — pytest cannot monkeypatch their
    # classmethods (raises TypeError on the immutable type), so R2's
    # datetime.now()/date.today() ban is enforced statically below instead.

    mpm = evaluate_mpm_gate(
        bundle.current_bar.adj_prev_close,
        Decimal("108.0"),
        Decimal("99.0"),
        bundle.current_bar.adj_close,
        Decimal("0.005"),
    )
    abnormality = compute_abnormality_bundle(bundle, calendar)
    candidate = generate_candidate(bundle, mpm, abnormality)

    assert mpm is not None
    assert abnormality.symbol == "PURE"
    # candidate may legitimately be None if nothing triggered; the point of
    # this test is that reaching this line never raised RuntimeError.
    assert candidate is None or candidate.symbol == "PURE"


def test_signal_engine_never_imports_datetime_now_or_date_today() -> None:
    """R2, the half monkeypatch cannot reach: datetime.now/date.today are C
    classmethods pytest cannot patch, so the ban on them is enforced by
    reading the source of the modules the signal engine is actually made of.
    """
    import ast
    from pathlib import Path

    modules = [
        "app/analytics/mpm.py",
        "app/analytics/abnormality.py",
        "app/analytics/candidates.py",
        "app/analytics/fact_bundle.py",
    ]
    backend_root = Path(__file__).resolve().parents[1]
    banned_calls = {("datetime", "now"), ("date", "today")}
    for relative in modules:
        source = (backend_root / relative).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            callee = node.func.attr
            owner = node.func.value.id if isinstance(node.func.value, ast.Name) else None
            assert (owner, callee) not in banned_calls, (
                f"{relative} calls {owner}.{callee}() — the signal engine must "
                "receive every input through the FactBundle (R2)"
            )
