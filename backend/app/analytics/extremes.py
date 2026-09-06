"""Adjusted-price 52-week extremes and lagged ADV baselines."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import pandas as pd
import sqlalchemy as sa

EXTREME_WINDOW = 252
ADV_WINDOW = 20


def estimate_extremes_and_adv(bars: pd.DataFrame) -> pd.DataFrame:
    """Estimate adjusted-price extremes and rupee ADV without lookahead."""
    required = {"date", "symbol", "adj_close", "turnover"}
    if not required.issubset(bars.columns):
        raise ValueError(f"bars must contain {sorted(required)}")
    if bars.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "high_52w",
                "low_52w",
                "distance_to_52w_high_pct",
                "distance_to_52w_low_pct",
                "adv_20d",
                "n_obs_52w",
            ]
        )

    ordered = bars.sort_values(["symbol", "date"])
    prices = ordered.pivot(index="date", columns="symbol", values="adj_close")
    turnover = ordered.pivot(index="date", columns="symbol", values="turnover")
    rolling_prices = prices.rolling(EXTREME_WINDOW, min_periods=20)
    high = rolling_prices.max()
    low = rolling_prices.min()
    n_obs = rolling_prices.count()
    adv = turnover.shift(1).rolling(ADV_WINDOW, min_periods=ADV_WINDOW).mean()

    current = prices.stack(future_stack=True).rename("adj_close")
    result = pd.concat(
        {
            "adj_close": current,
            "high_52w": high.stack(future_stack=True),
            "low_52w": low.stack(future_stack=True),
            "adv_20d": adv.stack(future_stack=True),
            "n_obs_52w": n_obs.stack(future_stack=True),
        },
        axis=1,
    ).reset_index()
    result = result.rename(columns={"level_0": "date", "level_1": "symbol"})
    result["distance_to_52w_high_pct"] = (
        (result["adj_close"] - result["high_52w"]) / result["high_52w"] * 100.0
    )
    result["distance_to_52w_low_pct"] = (
        (result["adj_close"] - result["low_52w"]) / result["low_52w"] * 100.0
    )
    result["n_obs_52w"] = result["n_obs_52w"].round().astype("Int64")
    return result.loc[
        result["n_obs_52w"].ge(20) & result["adv_20d"].notna()
    ].reset_index(drop=True)


def persist_extremes_and_adv(
    conn: sa.Connection,
    estimates: pd.DataFrame,
) -> int:
    """Bulk upsert adjusted-price extremes and ADV values."""
    if estimates.empty:
        return 0
    rows: Iterable[dict[str, Any]] = (
        {
            "date": row.date,
            "symbol": row.symbol,
            "high_52w": Decimal(str(row.high_52w)),
            "low_52w": Decimal(str(row.low_52w)),
            "distance_to_52w_high_pct": Decimal(str(row.distance_to_52w_high_pct)),
            "distance_to_52w_low_pct": Decimal(str(row.distance_to_52w_low_pct)),
            "adv_20d": Decimal(str(row.adv_20d)),
            "n_obs_52w": int(row.n_obs_52w),
        }
        for row in estimates.itertuples(index=False)
    )
    result = conn.execute(
        sa.text(
            "INSERT INTO market_extremes_adv "
            "(date, symbol, high_52w, low_52w, distance_to_52w_high_pct, "
            "distance_to_52w_low_pct, adv_20d, n_obs_52w) "
            "VALUES (:date, :symbol, :high_52w, :low_52w, "
            ":distance_to_52w_high_pct, :distance_to_52w_low_pct, :adv_20d, :n_obs_52w) "
            "ON CONFLICT (symbol, date) DO UPDATE SET "
            "high_52w = EXCLUDED.high_52w, low_52w = EXCLUDED.low_52w, "
            "distance_to_52w_high_pct = EXCLUDED.distance_to_52w_high_pct, "
            "distance_to_52w_low_pct = EXCLUDED.distance_to_52w_low_pct, "
            "adv_20d = EXCLUDED.adv_20d, n_obs_52w = EXCLUDED.n_obs_52w"
        ),
        list(rows),
    )
    return int(result.rowcount)
