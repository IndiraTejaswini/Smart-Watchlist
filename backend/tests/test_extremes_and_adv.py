"""Acceptance tests for adjusted-price extremes and rupee ADV."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.extremes import estimate_extremes_and_adv


def _bars(count: int = 25) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=count, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "AAA",
            "adj_close": np.arange(100, 100 + count, dtype=float),
            "turnover": np.arange(1, count + 1, dtype=float) * 1_000_000,
        }
    )


def test_history_threshold_and_lagged_adv() -> None:
    frame = _bars()
    result = estimate_extremes_and_adv(frame)
    row = result.iloc[-1]
    assert row["high_52w"] == frame["adj_close"].iloc[-1]
    assert row["low_52w"] == frame["adj_close"].iloc[0]
    assert row["n_obs_52w"] == 25
    assert row["adv_20d"] == frame["turnover"].iloc[4:24].mean()
    assert row["distance_to_52w_high_pct"] <= 0.0
    assert row["distance_to_52w_low_pct"] >= 0.0


def test_adjusted_series_prevents_split_collapse() -> None:
    frame = _bars(110)
    frame.loc[100:, "adj_close"] = np.arange(200, 210, dtype=float)
    result = estimate_extremes_and_adv(frame)
    row = result[result["date"] == frame.iloc[-1]["date"]].iloc[0]
    assert row["high_52w"] >= 209
    assert row["low_52w"] >= 100


def test_adv_uses_rupee_turnover_not_share_volume() -> None:
    frame = _bars()
    frame["volume"] = 1
    row = estimate_extremes_and_adv(frame).iloc[-1]
    assert row["adv_20d"] == frame["turnover"].iloc[4:24].mean()
    assert row["adv_20d"] != frame["volume"].iloc[4:24].mean()
