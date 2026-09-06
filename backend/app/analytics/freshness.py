"""Quote freshness state machines."""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.analytics.constants import (
    BENCHMARK_ANCHOR_SYMBOL,
    FRESHNESS_ANCHOR_SILENCE_MS,
    FRESHNESS_FLOW_MAX_AGE_MS,
    FRESHNESS_LIVE_MAX_AGE_MS,
    FRESHNESS_THIN_SILENCE_MS,
)
from app.schemas.quote import FreshnessState as QuoteFreshnessState
from app.timeutil import IST, SessionPhase, TradingCalendar, session_phase


class FreshnessState(StrEnum):
    HOLIDAY = "HOLIDAY"
    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    STALE_EOD = "STALE_EOD"
    HALTED_MARKET = "HALTED_MARKET"
    HALTED_SYMBOL = "HALTED_SYMBOL"
    STALE_THIN = "STALE_THIN"
    STALE_FLOW = "STALE_FLOW"
    LIVE = "LIVE"


@dataclass(frozen=True)
class FreshnessContext:
    symbol: str
    symbol_tick_ts: datetime | None
    symbol_date: date | None
    is_circuit_locked: bool = False
    is_regulatory_halted: bool = False
    anchor_symbol: str = BENCHMARK_ANCHOR_SYMBOL
    anchor_tick_ts: datetime | None = None
    eval_ts: datetime = field(
        default_factory=lambda: datetime.now(ZoneInfo("Asia/Kolkata"))
    )


def evaluate_freshness_state(
    ctx: FreshnessContext, calendar: TradingCalendar
) -> tuple[FreshnessState, str]:
    """Classify a symbol using the deterministic §14.2 waterfall."""
    eval_ts = ctx.eval_ts.astimezone(IST)
    eval_time = eval_ts.time()
    if calendar.is_holiday(eval_ts.date()):
        return FreshnessState.HOLIDAY, "Market holiday per trading calendar"
    if ctx.symbol_date is not None:
        expected = calendar.latest_completed_session(eval_ts.date())
        if ctx.symbol_date < expected:
            return (
                FreshnessState.STALE_EOD,
                f"Bhavcopy date {ctx.symbol_date} precedes expected session {expected}",
            )
    if eval_time < time(9, 0) or eval_time >= time(15, 30):
        return FreshnessState.CLOSED, "Outside official exchange hours"
    if time(9, 0) <= eval_time < time(9, 15):
        return FreshnessState.PRE_OPEN, "Pre-open auction window"

    delta_sym_ms = _age_ms(eval_ts, ctx.symbol_tick_ts)
    delta_anchor_ms = _age_ms(eval_ts, ctx.anchor_tick_ts)
    if delta_sym_ms > FRESHNESS_THIN_SILENCE_MS and (
        delta_anchor_ms > FRESHNESS_ANCHOR_SILENCE_MS
    ):
        return (
            FreshnessState.HALTED_MARKET,
            "Both symbol and benchmark anchor silent; exchange feed or pipe halted",
        )
    if ctx.is_regulatory_halted or ctx.is_circuit_locked:
        return FreshnessState.HALTED_SYMBOL, "Symbol suspended or locked at circuit limit"
    if delta_anchor_ms <= FRESHNESS_ANCHOR_SILENCE_MS and (
        delta_sym_ms > FRESHNESS_THIN_SILENCE_MS
    ):
        return (
            FreshnessState.STALE_THIN,
            f"Benchmark ticking but symbol silent for {delta_sym_ms / 1000:.1f}s (thin liquidity)",
        )
    if FRESHNESS_LIVE_MAX_AGE_MS < delta_sym_ms <= FRESHNESS_FLOW_MAX_AGE_MS:
        return (
            FreshnessState.STALE_FLOW,
            f"Quote age {delta_sym_ms / 1000:.1f}s exceeds live threshold",
        )
    if delta_sym_ms <= FRESHNESS_LIVE_MAX_AGE_MS:
        return FreshnessState.LIVE, f"Quote real-time (age {delta_sym_ms / 1000:.1f}s)"
    return FreshnessState.STALE_FLOW, "Default fallback"


def _age_ms(eval_ts: datetime, tick_ts: datetime | None) -> float:
    if tick_ts is None:
        return float("inf")
    return max(0.0, (eval_ts - tick_ts.astimezone(IST)).total_seconds() * 1000)


def evaluate_freshness(
    quote_ts: datetime,
    current_ts: datetime,
    calendar: TradingCalendar,
    is_circuit_locked: bool = False,
) -> tuple[QuoteFreshnessState, int]:
    age_ms = max(0, int((current_ts - quote_ts).total_seconds() * 1000))
    if session_phase(current_ts, calendar) is SessionPhase.CLOSED:
        return QuoteFreshnessState.CLOSED, age_ms
    if is_circuit_locked:
        return QuoteFreshnessState.HALTED, age_ms
    if age_ms < 5000:
        return QuoteFreshnessState.LIVE, age_ms
    if age_ms <= 60000:
        return QuoteFreshnessState.STALE, age_ms
    return QuoteFreshnessState.CLOSED, age_ms
