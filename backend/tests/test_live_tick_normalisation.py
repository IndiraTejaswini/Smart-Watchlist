"""Acceptance tests for adjustment-aware live quote enrichment."""

from datetime import date
from decimal import Decimal

from app.realtime.quotes import AdjustmentFactorCache, enrich_live_tick


class _Result:
    def mappings(self):
        return [{"symbol": "BPCL", "cum_price_factor": Decimal("0.5")}]


class _Connection:
    def __init__(self):
        self.calls = 0

    def execute(self, statement, params):
        self.calls += 1
        return _Result()


def test_bonus_ex_date_uses_adjusted_previous_close() -> None:
    cache = AdjustmentFactorCache()
    cache.refresh(date(2026, 9, 6), _Connection())
    quote = enrich_live_tick(
        symbol="BPCL",
        ltp=Decimal("300.0"),
        raw_prev_close=Decimal("600.0"),
        factor_cache=cache,
    )
    assert quote["adj_prev_close"] == Decimal("300.0000")
    assert quote["change_pct"] == Decimal("0.00")
    assert quote["raw_prev_close"] == Decimal("600.0")


def test_standard_day_preserves_normal_move() -> None:
    quote = enrich_live_tick(
        symbol="OTHER",
        ltp=Decimal("110"),
        raw_prev_close=Decimal("100"),
        factor_cache=AdjustmentFactorCache(),
    )
    assert quote["adj_prev_close"] == Decimal("100.0000")
    assert quote["change_pct"] == Decimal("10.00")


def test_cache_refreshes_once_per_session_and_rolls_over() -> None:
    cache = AdjustmentFactorCache()
    connection = _Connection()
    assert cache.refresh_if_needed(date(2026, 9, 6), connection)
    assert not cache.refresh_if_needed(date(2026, 9, 6), connection)
    assert cache.refresh_if_needed(date(2026, 9, 7), connection)
    assert connection.calls == 2
    cache.invalidate()
    assert cache.session_date is None
