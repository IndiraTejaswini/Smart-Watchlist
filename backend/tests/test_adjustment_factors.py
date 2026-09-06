"""Unit coverage for isolated adjustment-factor recomputation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.ingest.adjustments import recompute_symbol_adjustment_factors


class _Result:
    def __init__(self, values=None, mappings=None):
        self._values = values or []
        self._mappings = mappings or []

    def scalars(self):
        return iter(self._values)

    def mappings(self):
        return self._mappings


class _Connection:
    def __init__(self):
        self.rows = []

    def execute(self, statement, params=None):
        text = str(statement)
        if "SELECT date FROM daily_bars" in text:
            return _Result([date(2024, 6, 21), date(2024, 6, 20)])
        if "SELECT ex_date, action_type" in text:
            return _Result(
                mappings=[
                    {
                        "ex_date": date(2024, 6, 21),
                        "action_type": "BONUS",
                        "price_factor": Decimal("0.5"),
                        "tr_factor": Decimal("1"),
                    }
                ]
            )
        if "INSERT INTO symbol_adjustment_factors" in text:
            self.rows.extend(params)
        return _Result()


def test_recompute_applies_bonus_backwards_and_only_for_symbol() -> None:
    connection = _Connection()
    assert recompute_symbol_adjustment_factors(connection, "BPCL") == 2
    assert connection.rows[0]["cum_price_factor"] == Decimal("1")
    assert connection.rows[1]["cum_price_factor"] == Decimal("0.5")
    assert connection.rows[1]["cum_vol_factor"] == Decimal("2")
    assert all(row["symbol"] == "BPCL" for row in connection.rows)
