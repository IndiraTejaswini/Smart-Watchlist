"""Acceptance tests for empirical-logit delivery baselines."""

from __future__ import annotations

import pandas as pd

from app.analytics.delivery import estimate_delivery_baselines


def _rows(count: int = 25, delivery_pct: float = 30.0) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=count, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "AAA",
            "delivery_pct": delivery_pct,
            "traded_qty": 1000,
        }
    )


def test_logit_tail_expansion_and_raw_metric() -> None:
    frame = pd.concat(
        [_rows(20, 30.0), _rows(1, 95.0).assign(date=pd.Timestamp("2026-01-21"))],
        ignore_index=True,
    )
    frame.loc[frame.index[-1], "delivery_pct"] = 95.0
    result = estimate_delivery_baselines(frame)
    tail = result.iloc[-1]
    assert tail["raw_delivery_pct"] == 95.0
    assert tail["delivery_z_score"] > 0
    fifty = frame.copy()
    fifty.loc[fifty.index[-1], "delivery_pct"] = 50.0
    middle = estimate_delivery_baselines(fifty).iloc[-1]
    assert tail["delivery_z_score"] > middle["delivery_z_score"]


def test_zero_volume_days_are_excluded_from_active_window() -> None:
    frame = _rows(25, 30.0)
    frame.loc[10:14, "traded_qty"] = 0
    result = estimate_delivery_baselines(frame)
    row = result[result["date"] == frame.iloc[-1]["date"]].iloc[0]
    assert row["n_obs"] == 19


def test_current_delivery_is_excluded_and_short_history_degrades() -> None:
    short = _rows(8, 30.0)
    short_result = estimate_delivery_baselines(short)
    assert short_result.iloc[-1]["quality_flag"] == "DEGRADED"
    assert short_result.iloc[-1]["delivery_z_score"] == 0.0

    frame = _rows(21, 30.0)
    baseline = estimate_delivery_baselines(frame).iloc[-1]["mean_logit_20d"]
    changed = frame.copy()
    changed.loc[changed.index[-1], "delivery_pct"] = 99.0
    assert estimate_delivery_baselines(changed).iloc[-1]["mean_logit_20d"] == baseline
