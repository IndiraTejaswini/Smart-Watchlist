"""Acceptance coverage for the vectorised single-index market model."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.market_model import estimate_market_model


def _returns(days: int = 125) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    market = rng.normal(0.001, 0.01, days)
    stock = 0.0002 + 1.2 * market + rng.normal(0, 0.006, days)
    return pd.DataFrame({"STOCK": stock, "BENCHMARK": market})


def test_clean_window_is_vectorised_and_has_plausible_fit() -> None:
    result = estimate_market_model(_returns())
    row = result.iloc[-1]
    assert 0.10 <= row["r2"] <= 0.90
    assert row["n_obs"] == 120
    assert row["quality_flag"] == "CLEAN"


def test_short_history_is_degraded() -> None:
    row = estimate_market_model(_returns(40)).iloc[-1]
    assert row["quality_flag"] == "DEGRADED"
    assert row["beta"] == 1.0
    assert row["alpha"] == 0.0


def test_beta_is_clamped() -> None:
    frame = _returns()
    frame["STOCK"] = frame["BENCHMARK"] * 100
    row = estimate_market_model(frame).iloc[-1]
    assert 0.0 <= row["beta"] <= 3.0


def test_five_session_gap_excludes_recent_returns() -> None:
    frame = _returns()
    baseline = estimate_market_model(frame).iloc[-1]
    changed = frame.copy()
    changed.iloc[-4:, changed.columns.get_loc("STOCK")] = 50.0
    changed_row = estimate_market_model(changed).iloc[-1]
    assert changed_row["beta"] == baseline["beta"]
    assert changed_row["alpha"] == baseline["alpha"]
