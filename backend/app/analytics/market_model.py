"""Vectorised single-index market-model parameter estimation."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
import sqlalchemy as sa

WINDOW = 120
GAP = 5
MIN_OBS = 60
RESID_SD_FLOOR = 0.005
BENCHMARK = "BENCHMARK"


def _winsorize_cross_section(wide_returns: pd.DataFrame) -> pd.DataFrame:
    """Winsorize each session cross-section at the 1st and 99th percentiles."""
    lower = wide_returns.quantile(0.01, axis=1)
    upper = wide_returns.quantile(0.99, axis=1)
    return wide_returns.clip(
        lower=lower.reindex(wide_returns.index),
        upper=upper.reindex(wide_returns.index),
        axis=0,
    )


def estimate_market_model(
    wide_returns: pd.DataFrame,
    *,
    benchmark: str = BENCHMARK,
) -> pd.DataFrame:
    """Estimate all symbols for all dates using one vectorised rolling pass.

    ``wide_returns`` must be indexed by chronological sessions and contain one
    column per symbol plus the benchmark return column.
    """
    if benchmark not in wide_returns.columns:
        raise ValueError(f"missing benchmark column {benchmark!r}")
    if not wide_returns.index.is_monotonic_increasing:
        wide_returns = wide_returns.sort_index()

    returns = _winsorize_cross_section(wide_returns.astype(float))
    shifted = returns.shift(GAP)
    market = shifted[benchmark]
    rolling = shifted.rolling(WINDOW, min_periods=1)
    market_var = market.rolling(WINDOW, min_periods=1).var()
    market_mean = market.rolling(WINDOW, min_periods=1).mean()
    covariance = rolling.cov(market)
    variance = rolling.var()
    means = rolling.mean()
    valid = shifted.notna() & market.notna().to_numpy()[:, None]
    n_obs = valid.astype(float).rolling(WINDOW, min_periods=1).sum()

    symbols = [column for column in returns.columns if column != benchmark]
    beta = covariance[symbols].div(market_var.replace(0.0, np.nan), axis=0)
    beta = beta.clip(lower=0.0, upper=3.0).fillna(1.0)
    alpha = means[symbols].sub(
        beta.mul(market_mean, axis=0),
    )
    residual_variance = variance[symbols].sub(
        beta.pow(2).mul(market_var, axis=0),
    ).clip(lower=0.0)
    resid_sd = np.sqrt(residual_variance).clip(lower=RESID_SD_FLOOR)
    symbol_variance = variance[symbols].replace(0.0, np.nan)
    r2 = beta.pow(2).mul(market_var, axis=0).div(symbol_variance)

    median_sd = resid_sd.median(axis=1).fillna(RESID_SD_FLOOR)
    degraded = n_obs[symbols] < MIN_OBS
    beta = beta.mask(degraded, 1.0)
    alpha = alpha.mask(degraded, 0.0)
    r2 = r2.mask(degraded)
    resid_sd = resid_sd.mask(degraded, median_sd, axis=0)
    quality = pd.DataFrame(
        np.where(
            degraded,
            "DEGRADED",
            np.where(n_obs[symbols] < WINDOW, "ACCEPTABLE_SHORT", "CLEAN"),
        ),
        index=returns.index,
        columns=symbols,
    )

    frames: list[pd.DataFrame] = []
    for name, values in (
        ("alpha", alpha),
        ("beta", beta),
        ("r2", r2),
        ("resid_sd", resid_sd),
        ("n_obs", n_obs[symbols]),
        ("quality_flag", quality),
    ):
        frame = values.stack(future_stack=True).rename(name).to_frame()
        frames.append(frame)
    result = pd.concat(frames, axis=1).reset_index()
    result = result.rename(columns={"level_0": "date", "level_1": "symbol"})
    result["n_obs"] = result["n_obs"].round().astype(int)
    return result


def returns_from_adjusted_bars(
    bars: pd.DataFrame,
    benchmark_returns: pd.Series,
) -> pd.DataFrame:
    """Build the wide adjusted-return frame consumed by the estimator."""
    required = {"date", "symbol", "adj_close"}
    if not required.issubset(bars.columns):
        raise ValueError(f"bars must contain {sorted(required)}")
    prices = bars.pivot(index="date", columns="symbol", values="adj_close")
    stock_returns = prices.pct_change()
    benchmark = benchmark_returns.rename(BENCHMARK)
    return stock_returns.join(benchmark, how="outer").sort_index()


def persist_market_model_parameters(
    conn: sa.Connection,
    parameters: pd.DataFrame,
) -> int:
    """Bulk upsert estimated parameters in one transaction."""
    if parameters.empty:
        return 0
    rows: Iterable[dict[str, Any]] = (
        {
            "date": row.date,
            "symbol": row.symbol,
            "alpha": Decimal(str(row.alpha)),
            "beta": Decimal(str(row.beta)),
            "r2": None if pd.isna(row.r2) else Decimal(str(row.r2)),
            "resid_sd": Decimal(str(row.resid_sd)),
            "n_obs": int(row.n_obs),
            "quality_flag": row.quality_flag,
        }
        for row in parameters.itertuples(index=False)
    )
    result = conn.execute(
        sa.text(
            "INSERT INTO market_model_parameters "
            "(date, symbol, alpha, beta, r2, resid_sd, n_obs, quality_flag) "
            "VALUES (:date, :symbol, :alpha, :beta, :r2, :resid_sd, :n_obs, :quality_flag) "
            "ON CONFLICT (symbol, date) DO UPDATE SET "
            "alpha = EXCLUDED.alpha, beta = EXCLUDED.beta, r2 = EXCLUDED.r2, "
            "resid_sd = EXCLUDED.resid_sd, n_obs = EXCLUDED.n_obs, "
            "quality_flag = EXCLUDED.quality_flag"
        ),
        list(rows),
    )
    return int(result.rowcount)
