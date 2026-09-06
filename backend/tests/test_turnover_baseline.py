"""Acceptance tests for lagged turnover baselines."""

from __future__ import annotations

from math import log

import numpy as np
import pandas as pd

from app.analytics.turnover import estimate_turnover_baselines


def test_log_transform_and_lagged_window() -> None:
    dates = pd.date_range("2026-01-01", periods=22, freq="D")
    values = np.arange(22, dtype=float) * 1_000_000
    frame = pd.DataFrame({"AAA": values}, index=dates)
    result = estimate_turnover_baselines(frame)
    row = result[result["date"] == dates[21]].iloc[0]
    expected = np.log1p(values[1:21]).mean()
    assert row["mean_log_turnover"] == expected
    assert row["n_obs"] == 20
    assert row["quality_flag"] == "CLEAN"
    assert result.loc[result["date"] == dates[21], "mean_log_turnover"].iloc[0] != np.log1p(
        values[21]
    )
    assert np.isclose(np.log1p(0), 0.0)
    assert np.isclose(np.log1p(10_000_000), log(10_000_001))


def test_short_history_degrades_and_twenty_observations_are_clean() -> None:
    dates = pd.date_range("2026-02-01", periods=21, freq="D")
    frame = pd.DataFrame(
        {
            "SHORT": np.r_[np.arange(6, dtype=float), [np.nan] * 15],
            "LONG": np.arange(21, dtype=float),
        },
        index=dates,
    )
    result = estimate_turnover_baselines(frame)
    short = result[(result["date"] == dates[5]) & (result["symbol"] == "SHORT")].iloc[0]
    long = result[(result["date"] == dates[20]) & (result["symbol"] == "LONG")].iloc[0]
    assert short["n_obs"] == 5
    assert short["quality_flag"] == "DEGRADED"
    assert long["n_obs"] == 20
    assert long["quality_flag"] == "CLEAN"
    assert long["std_log_turnover"] >= 0.05
