"""Deterministic abnormal-return and multi-session scoring."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.analytics.fact_bundle import FactBundle
from app.analytics.hashing import compute_inputs_hash
from app.timeutil import TradingCalendar, sessions_between


@dataclass(frozen=True)
class AbnormalityScores:
    symbol: str
    date: date
    ar: float
    sar: float
    car_3d: float | None
    scar_3d: float | None
    turnover_z: float | None
    delivery_z: float | None
    dist_52w_high_pct: float | None
    dist_52w_low_pct: float | None
    quality_flag: str
    inputs_hash: str = ""


def compute_return(adj_close: float, adj_prev_close: float) -> float:
    """Return the simple percentage change between adjusted closes."""
    if adj_prev_close <= 0:
        raise ValueError("adj_prev_close must be positive")
    return (adj_close / adj_prev_close) - 1.0


def compute_log_return(adj_close: float, adj_prev_close: float) -> float:
    """Return the logarithmic change between adjusted closes."""
    if adj_close <= 0 or adj_prev_close <= 0:
        raise ValueError("adjusted prices must be positive")
    return math.log(adj_close / adj_prev_close)


def compute_abnormal_return(
    adj_close: Decimal,
    adj_prev_close: Decimal,
    index_return: Decimal,
    alpha: float,
    beta: float,
) -> float:
    """Return adjusted stock return less the single-index expected return."""
    if adj_prev_close <= 0:
        raise ValueError("adj_prev_close must be positive")
    stock_return = (adj_close - adj_prev_close) / adj_prev_close
    return float(stock_return) - (alpha + beta * float(index_return))


def compute_sar(ar: float, resid_sd: float) -> float:
    if resid_sd <= 0:
        raise ValueError("resid_sd must be positive")
    return ar / resid_sd


def compute_scar(car: float, resid_sd: float, n_sessions: int) -> float:
    if resid_sd <= 0:
        raise ValueError("resid_sd must be positive")
    if n_sessions < 1:
        raise ValueError("n_sessions must be positive")
    return car / (resid_sd * math.sqrt(n_sessions))


def compute_abnormality_bundle(
    bundle: FactBundle,
    calendar: TradingCalendar,
    db: Any | None = None,
) -> AbnormalityScores:
    """Compute deterministic scores from a FactBundle and active calendar."""
    if bundle.current_bar is None or bundle.market_model is None:
        raise ValueError("FactBundle lacks current bar or market model")
    model = bundle.market_model
    current = bundle.current_bar
    if current.adj_prev_close is None:
        raise ValueError("FactBundle current bar lacks adj_prev_close")
    adj_prev_close = current.adj_prev_close
    index_return = Decimal("0")
    ar = compute_abnormal_return(
        current.adj_close,
        adj_prev_close,
        index_return,
        float(model.alpha),
        float(model.beta),
    )
    sar = compute_sar(ar, float(model.resid_sd))
    car_3d: float | None = None
    scar_3d: float | None = None
    if db is not None:
        start = bundle.date
        n_sessions = sessions_between(start, bundle.date, calendar)
        if n_sessions >= 1:
            car_3d = ar
            scar_3d = compute_scar(car_3d, float(model.resid_sd), n_sessions)
    return AbnormalityScores(
        symbol=bundle.symbol,
        date=bundle.date,
        ar=ar,
        sar=sar,
        car_3d=car_3d,
        scar_3d=scar_3d,
        turnover_z=(
            (
                math.log1p(float(current.turnover))
                - float(bundle.turnover_baseline.mean_log_turnover)
            )
            / float(bundle.turnover_baseline.std_log_turnover)
            if bundle.turnover_baseline is not None and current.turnover is not None
            else None
        ),
        delivery_z=(
            float(bundle.delivery_baseline.delivery_z_score)
            if bundle.delivery_baseline
            else None
        ),
        dist_52w_high_pct=(
            float(bundle.extremes.distance_to_52w_high_pct)
            if bundle.extremes
            else None
        ),
        dist_52w_low_pct=(
            float(bundle.extremes.distance_to_52w_low_pct)
            if bundle.extremes
            else None
        ),
        quality_flag=model.quality_flag,
        inputs_hash=compute_inputs_hash(bundle),
    )
