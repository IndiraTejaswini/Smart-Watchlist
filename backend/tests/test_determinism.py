"""Cross-process and mutation tests for canonical input hashing."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from decimal import Decimal

from app.analytics.fact_bundle import DailyBarFact, FactBundle
from app.analytics.hashing import compute_inputs_hash


def _bundle() -> FactBundle:
    return FactBundle(
        symbol="INFY",
        date=date(2026, 4, 6),
        current_bar=DailyBarFact(
            adj_close=Decimal("100.0100"),
            turnover=Decimal("1000000.00"),
            volume=100,
            adj_prev_close=Decimal("100.0000"),
        ),
        completeness=frozenset({"BARS"}),
    )


def test_hash_is_stable_across_processes() -> None:
    expected = compute_inputs_hash(_bundle())
    script = (
        "from datetime import date; from decimal import Decimal; "
        "from app.analytics.fact_bundle import DailyBarFact, FactBundle; "
        "from app.analytics.hashing import compute_inputs_hash; "
        "b=FactBundle('INFY',date(2026,4,6),"
        "current_bar=DailyBarFact(Decimal('100.0100'),Decimal('1000000.00'),100,"
        "Decimal('100.0000')),completeness=frozenset({'BARS'})); "
        "print(compute_inputs_hash(b))"
    )
    env = {**os.environ, "PYTHONHASHSEED": "random"}
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.stdout.strip() == expected


def test_hash_changes_for_mutations() -> None:
    original = _bundle()
    baseline = compute_inputs_hash(original)
    changed_close = FactBundle(
        original.symbol,
        original.date,
        current_bar=DailyBarFact(
            Decimal("100.0100"), Decimal("1000000.00"), 100, Decimal("100.0100")
        ),
        completeness=original.completeness,
    )
    changed_completeness = FactBundle(
        original.symbol,
        original.date,
        current_bar=original.current_bar,
        completeness=frozenset({"BARS", "MARKET_MODEL"}),
    )
    assert compute_inputs_hash(changed_close) != baseline
    assert compute_inputs_hash(changed_completeness) != baseline
