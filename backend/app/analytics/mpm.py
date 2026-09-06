"""Material Price Movement gate calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.constants import MPM_TIER_THRESHOLDS


@dataclass(frozen=True)
class MPMResult:
    close_triggered: bool
    intraday_triggered: bool
    effective_threshold: float
    base_threshold: float
    stock_return: float
    index_return: float
    max_excursion: float
    is_circuit_override: bool


def _base_threshold(adj_prev_close: Decimal) -> Decimal:
    for upper_bound, threshold_pct in MPM_TIER_THRESHOLDS:
        if adj_prev_close < Decimal(str(upper_bound)):
            return Decimal(str(threshold_pct)) / Decimal("100")
    raise ValueError("MPM tier thresholds must include a finite matching tier")


def evaluate_mpm_gate(
    adj_prev_close: Decimal,
    adj_high: Decimal,
    adj_low: Decimal,
    adj_close: Decimal,
    index_return: Decimal,
    is_circuit_band_hit: bool = False,
) -> MPMResult:
    """Evaluate close-to-close and unadjusted-by-index intraday MPM gates."""
    if adj_prev_close <= 0:
        raise ValueError("adj_prev_close must be positive")
    stock_return = (adj_close - adj_prev_close) / adj_prev_close
    high_excursion = abs(adj_high - adj_prev_close) / adj_prev_close
    low_excursion = abs(adj_low - adj_prev_close) / adj_prev_close
    max_excursion = max(high_excursion, low_excursion)
    base_threshold = _base_threshold(adj_prev_close)
    same_direction = (
        (stock_return > 0 and index_return > 0)
        or (stock_return < 0 and index_return < 0)
    )
    effective_threshold = base_threshold + abs(index_return) if same_direction else base_threshold
    return MPMResult(
        close_triggered=abs(stock_return) >= effective_threshold or is_circuit_band_hit,
        intraday_triggered=max_excursion >= base_threshold or is_circuit_band_hit,
        effective_threshold=float(effective_threshold),
        base_threshold=float(base_threshold),
        stock_return=float(stock_return),
        index_return=float(index_return),
        max_excursion=float(max_excursion),
        is_circuit_override=is_circuit_band_hit,
    )
