"""Vectorised lagged turnover baselines."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
import sqlalchemy as sa

from app.constants import BASELINE_MIN_SHORT_OBS, LOG_TO_SD_FLOOR, VOL_WINDOW_DAYS

WINDOW = VOL_WINDOW_DAYS
MIN_SHORT = BASELINE_MIN_SHORT_OBS
STD_FLOOR = LOG_TO_SD_FLOOR


def estimate_turnover_baselines(wide_turnover: pd.DataFrame) -> pd.DataFrame:
    """Estimate strictly lagged log-turnover statistics for every symbol."""
    if wide_turnover.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "mean_log_turnover",
                "std_log_turnover",
                "n_obs",
                "quality_flag",
            ]
        )
    if not wide_turnover.index.is_monotonic_increasing:
        wide_turnover = wide_turnover.sort_index()

    log_turnover = np.log1p(wide_turnover.astype(float))
    shifted = log_turnover.shift(1)
    rolling = shifted.rolling(WINDOW, min_periods=1)
    mean_log = rolling.mean()
    std_log = rolling.std(ddof=1)
    n_obs = rolling.count()
    std_log = std_log.clip(lower=STD_FLOOR)
    median_std = std_log.median(axis=1).fillna(STD_FLOOR)
    degraded = n_obs < MIN_SHORT
    std_log = std_log.mask(degraded, median_std, axis=0)
    quality = pd.DataFrame(
        np.where(
            n_obs < MIN_SHORT,
            "DEGRADED",
            np.where(n_obs < WINDOW, "ACCEPTABLE_SHORT", "CLEAN"),
        ),
        index=wide_turnover.index,
        columns=wide_turnover.columns,
    )

    result = pd.concat(
        {
            "mean_log_turnover": mean_log.stack(future_stack=True),
            "std_log_turnover": std_log.stack(future_stack=True),
            "n_obs": n_obs.stack(future_stack=True),
            "quality_flag": quality.stack(future_stack=True),
        },
        axis=1,
    ).reset_index()
    result = result.rename(columns={"level_0": "date", "level_1": "symbol"})
    result["n_obs"] = result["n_obs"].round().astype(int)
    return result


def turnover_from_daily_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Pivot daily-bars rupee turnover into the estimator's wide input."""
    required = {"date", "symbol", "turnover"}
    if not required.issubset(bars.columns):
        raise ValueError(f"bars must contain {sorted(required)}")
    return bars.pivot(index="date", columns="symbol", values="turnover").sort_index()


def persist_turnover_baselines(
    conn: sa.Connection,
    baselines: pd.DataFrame,
) -> int:
    """Bulk upsert turnover baselines in the caller's transaction."""
    if baselines.empty:
        return 0
    rows: Iterable[dict[str, Any]] = (
        {
            "date": row.date,
            "symbol": row.symbol,
            "mean_log_turnover": Decimal(str(row.mean_log_turnover)),
            "std_log_turnover": Decimal(str(row.std_log_turnover)),
            "n_obs": int(row.n_obs),
            "quality_flag": row.quality_flag,
        }
        for row in baselines.itertuples(index=False)
    )
    result = conn.execute(
        sa.text(
            "INSERT INTO turnover_baselines "
            "(date, symbol, mean_log_turnover, std_log_turnover, n_obs, quality_flag) "
            "VALUES (:date, :symbol, :mean_log_turnover, :std_log_turnover, :n_obs, :quality_flag) "
            "ON CONFLICT (symbol, date) DO UPDATE SET "
            "mean_log_turnover = EXCLUDED.mean_log_turnover, "
            "std_log_turnover = EXCLUDED.std_log_turnover, "
            "n_obs = EXCLUDED.n_obs, quality_flag = EXCLUDED.quality_flag"
        ),
        list(rows),
    )
    return int(result.rowcount)
