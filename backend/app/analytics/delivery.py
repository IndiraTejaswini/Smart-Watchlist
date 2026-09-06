"""Vectorised, lagged empirical-logit delivery baselines."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
import sqlalchemy as sa

WINDOW = 20
MIN_SHORT = 10
EPSILON = 1e-4
STD_FLOOR = 0.05


def _logit(delivery_pct: pd.Series) -> pd.Series:
    fraction = delivery_pct.astype(float) / 100.0
    return np.log((fraction + EPSILON) / (1.0 - fraction + EPSILON))


def estimate_delivery_baselines(delivery: pd.DataFrame) -> pd.DataFrame:
    """Estimate active-session delivery baselines without zero-volume imputation."""
    required = {"date", "symbol", "delivery_pct", "traded_qty"}
    if not required.issubset(delivery.columns):
        raise ValueError(f"delivery must contain {sorted(required)}")
    active = delivery.loc[delivery["traded_qty"].astype(float) > 0].copy()
    if active.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "raw_delivery_pct",
                "logit_delivery",
                "mean_logit_20d",
                "std_logit_20d",
                "delivery_z_score",
                "n_obs",
                "quality_flag",
            ]
        )
    active = active.sort_values("date")
    active["logit_delivery"] = _logit(active["delivery_pct"])
    logit_wide = active.pivot(index="date", columns="symbol", values="logit_delivery")
    raw_wide = active.pivot(index="date", columns="symbol", values="delivery_pct")
    shifted = logit_wide.shift(1)
    rolling = shifted.rolling(WINDOW, min_periods=1)
    mean_logit = rolling.mean()
    std_logit = rolling.std(ddof=1).clip(lower=STD_FLOOR)
    n_obs = rolling.count()
    median_std = std_logit.median(axis=1).fillna(STD_FLOOR)
    degraded = n_obs < MIN_SHORT
    std_logit = std_logit.mask(degraded, median_std, axis=0)
    quality = pd.DataFrame(
        np.where(
            n_obs < MIN_SHORT,
            "DEGRADED",
            np.where(n_obs < WINDOW, "ACCEPTABLE_SHORT", "CLEAN"),
        ),
        index=logit_wide.index,
        columns=logit_wide.columns,
    )
    current = logit_wide.stack(future_stack=True).rename("logit_delivery")
    result = pd.concat(
        {
            "raw_delivery_pct": raw_wide.stack(future_stack=True),
            "logit_delivery": current,
            "mean_logit_20d": mean_logit.stack(future_stack=True),
            "std_logit_20d": std_logit.stack(future_stack=True),
            "n_obs": n_obs.stack(future_stack=True),
            "quality_flag": quality.stack(future_stack=True),
        },
        axis=1,
    ).reset_index()
    result = result.rename(columns={"level_0": "date", "level_1": "symbol"})
    result["mean_logit_20d"] = result["mean_logit_20d"].fillna(result["logit_delivery"])
    result["n_obs"] = result["n_obs"].round().astype(int)
    result["delivery_z_score"] = np.where(
        result["quality_flag"].eq("DEGRADED"),
        0.0,
        (result["logit_delivery"] - result["mean_logit_20d"])
        / result["std_logit_20d"],
    )
    return result


def persist_delivery_baselines(
    conn: sa.Connection,
    baselines: pd.DataFrame,
) -> int:
    """Bulk upsert transformed and raw delivery metrics."""
    if baselines.empty:
        return 0
    rows: Iterable[dict[str, Any]] = (
        {
            "date": row.date,
            "symbol": row.symbol,
            "raw_delivery_pct": Decimal(str(row.raw_delivery_pct)),
            "logit_delivery": Decimal(str(row.logit_delivery)),
            "mean_logit_20d": Decimal(str(row.mean_logit_20d)),
            "std_logit_20d": Decimal(str(row.std_logit_20d)),
            "delivery_z_score": Decimal(str(row.delivery_z_score)),
            "n_obs": int(row.n_obs),
            "quality_flag": row.quality_flag,
        }
        for row in baselines.itertuples(index=False)
    )
    result = conn.execute(
        sa.text(
            "INSERT INTO delivery_baselines "
            "(date, symbol, raw_delivery_pct, logit_delivery, mean_logit_20d, "
            "std_logit_20d, delivery_z_score, n_obs, quality_flag) "
            "VALUES (:date, :symbol, :raw_delivery_pct, :logit_delivery, "
            ":mean_logit_20d, :std_logit_20d, :delivery_z_score, :n_obs, :quality_flag) "
            "ON CONFLICT (symbol, date) DO UPDATE SET "
            "raw_delivery_pct = EXCLUDED.raw_delivery_pct, "
            "logit_delivery = EXCLUDED.logit_delivery, "
            "mean_logit_20d = EXCLUDED.mean_logit_20d, "
            "std_logit_20d = EXCLUDED.std_logit_20d, "
            "delivery_z_score = EXCLUDED.delivery_z_score, "
            "n_obs = EXCLUDED.n_obs, quality_flag = EXCLUDED.quality_flag"
        ),
        list(rows),
    )
    return int(result.rowcount)
