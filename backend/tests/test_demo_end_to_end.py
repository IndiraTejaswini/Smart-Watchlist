"""The one test that verifies the product, not a component.

Three bugs each independently broke the demo Brief entirely — an ETF-polluted
candidate universe, a sector rollup that suppressed candidates across the
whole cursor window instead of per day, and a frontend cursor that always
queried an empty window — and 617 passing component tests caught none of
them, because each one only breaks the *composition* of `/api/brief`, not any
one function's contract.

This test hits `/api/brief` the way a fresh reviewer's browser does: no
`as_of` param, for the seeded demo user, at the seeded demo cursor. It is
deliberately end-to-end (real database, real HTTP layer, no mocked
component) so that a regression anywhere in the digest/ranker/attribution
chain shows up here even if every unit test around it still passes.

Run as the final step of `make seed` (`backend/scripts/seed.py`) and picked
up by the normal `pytest` sweep in CI — a trimmed or corrupted seed that
produces an empty Brief is worse than no deployment, and this is the check
that catches it before a reviewer does.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import get_settings
from app.constants import BRIEF_MAX_ITEMS
from app.main import create_app

DEMO_USER_HEADER = {"X-Demo-User": "demo_trader"}


@pytest.fixture(scope="module")
def engine():
    engine = sa.create_engine(get_settings().database_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 — any connection failure is a skip
        pytest.skip(f"postgres unreachable ({type(exc).__name__}); run `make up`")
    return engine


def test_demo_brief_is_populated_with_real_explained_signals(engine):
    with engine.connect() as conn:
        candidate_count = conn.execute(sa.text("SELECT COUNT(*) FROM candidates")).scalar_one()
        instrument_symbols = set(
            conn.execute(sa.text("SELECT symbol FROM instruments")).scalars().all()
        )
    if not candidate_count:
        pytest.skip("no candidates; run `make seed` first")

    client = TestClient(create_app())
    response = client.get("/api/brief", headers=DEMO_USER_HEADER)
    assert response.status_code == 200, response.text
    body = response.json()
    items = body["items"]

    # 1. Between 1 and BRIEF_MAX_ITEMS scored items — not zero (an empty
    # window bug, as in the cursor regression) and not more than the budget
    # cap ever allows.
    assert 1 <= len(items) <= BRIEF_MAX_ITEMS, (
        f"expected 1..{BRIEF_MAX_ITEMS} items at the seeded demo cursor, got {len(items)}: "
        f"{body['headline']!r}"
    )

    # 2. At least one EXPLAINED item with a real linked filing — proves the
    # announcement-matching path, not just that *something* scored.
    explained_with_filing = [
        item
        for item in items
        if item["classification"] == "EXPLAINED" and item["linked_announcement_ids"]
    ]
    assert explained_with_filing, (
        "expected at least one EXPLAINED item with a linked filing; "
        f"classifications present: {[i['classification'] for i in items]}"
    )

    with engine.connect() as conn:
        for item in items:
            # 3. Every surfaced symbol is a real NSE cash-equity instrument —
            # the ETF-pollution regression put LIQUIDBEES and LIQUIDCASE here.
            assert item["symbol"] in instrument_symbols, (
                f"{item['symbol']} is not in `instruments` — the candidate "
                "universe has drifted from cash equities again"
            )

            # 4. No item below its own MPM base threshold for its price tier.
            # The gate (app.analytics.mpm.evaluate_mpm_gate) triggers on
            # EITHER the close-to-close move OR the intraday high/low
            # excursion clearing the threshold — `metrics.pct_move` is only
            # the close-to-close figure, so a item can legitimately clear the
            # gate on intraday excursion alone (a stock that spiked 6%
            # intraday and closed up 2.5%). Re-derive both from the day's own
            # bar rather than trusting the server's `mpm_triggered` flag,
            # which is exactly the field a regression in the gate would also
            # get wrong.
            bar = conn.execute(
                sa.text(
                    "SELECT high, low, close, prev_close FROM daily_bars "
                    "WHERE symbol = :symbol AND date = :date"
                ),
                {"symbol": item["symbol"], "date": item["signal_event_id"].split(":")[0]},
            ).mappings().first()
            assert bar is not None, f"no daily_bars row for {item['signal_event_id']}"
            prev_close = float(bar["prev_close"])
            close_pct = abs(float(bar["close"]) - prev_close) / prev_close * 100
            high_excursion_pct = abs(float(bar["high"]) - prev_close) / prev_close * 100
            low_excursion_pct = abs(prev_close - float(bar["low"])) / prev_close * 100
            max_move_pct = max(close_pct, high_excursion_pct, low_excursion_pct)
            threshold_pct = item["metrics"]["mpm_threshold_used"] * 100
            assert max_move_pct >= threshold_pct, (
                f"{item['symbol']} moved at most {max_move_pct:.2f}% "
                f"(close {close_pct:.2f}%, high {high_excursion_pct:.2f}%, "
                f"low {low_excursion_pct:.2f}%), below its own reported MPM "
                f"threshold of {threshold_pct}% — the gate did not hold"
            )
