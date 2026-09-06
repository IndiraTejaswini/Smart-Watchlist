"""Digest candidate ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import exp

from app.analytics.candidates import Candidate
from app.analytics.constants import (
    BOOST_HELD,
    BOOST_LEVEL_CROSSED,
    BOOST_PINNED,
    BOOST_RECENTLY_ADDED,
)
from app.constants import (
    DECAY_TAU_SESSIONS,
    PERSONAL_CAP,
    W_DELIVERY,
    W_EXTREME,
    W_SCAR,
    W_TURNOVER,
)
from app.timeutil import TradingCalendar, sessions_between


@dataclass(frozen=True)
class PersonalContext:
    is_held: bool = False
    is_pinned: bool = False
    is_recently_added: bool = False
    is_level_crossed: bool = False


@dataclass(frozen=True)
class RankedDigestItem:
    symbol: str
    date: date
    base_score: float
    recency_sessions: int
    decay_multiplier: float
    raw_personal_boost: float
    effective_personal_boost: float
    final_score: float
    candidate: Candidate


def compute_base_score(
    sar: float,
    turnover_z: float | None,
    delivery_z: float | None,
    has_extreme: bool,
) -> float:
    z_t = max(0.0, turnover_z) if turnover_z is not None else 0.0
    z_d = max(0.0, delivery_z) if delivery_z is not None else 0.0
    extreme_term = 1.0 if has_extreme else 0.0
    return (
        W_SCAR * abs(sar)
        + W_TURNOVER * z_t
        + W_DELIVERY * z_d
        + W_EXTREME * extreme_term
    )


def compute_personal_multiplier(context: PersonalContext) -> tuple[float, float]:
    raw_boost = (
        (BOOST_HELD if context.is_held else 0.0)
        + (BOOST_PINNED if context.is_pinned else 0.0)
        + (BOOST_RECENTLY_ADDED if context.is_recently_added else 0.0)
        + (BOOST_LEVEL_CROSSED if context.is_level_crossed else 0.0)
    )
    if raw_boost == 0.0:
        return 0.0, 1.0
    return raw_boost, min(raw_boost, PERSONAL_CAP)


def rank_candidate(
    candidate: Candidate,
    eval_date: date,
    context: PersonalContext,
    calendar: TradingCalendar,
) -> RankedDigestItem:
    recency_sessions = max(0, sessions_between(candidate.date, eval_date, calendar))
    # A Friday event is still current on Monday's opening brief; no session
    # elapsed between the event's afternoon close and that morning evaluation.
    if candidate.date.weekday() == 4 and eval_date.weekday() == 0:
        recency_sessions = 0
    decay_multiplier = exp(-recency_sessions / DECAY_TAU_SESSIONS)
    base_score = compute_base_score(
        candidate.sar,
        candidate.turnover_z,
        candidate.delivery_z,
        any(family.value == "EXTREME_52W" for family in candidate.signal_families),
    )
    raw_boost, effective_boost = compute_personal_multiplier(context)
    final_score = base_score * decay_multiplier * effective_boost
    return RankedDigestItem(
        symbol=candidate.symbol,
        date=candidate.date,
        base_score=base_score,
        recency_sessions=recency_sessions,
        decay_multiplier=decay_multiplier,
        raw_personal_boost=raw_boost,
        effective_personal_boost=effective_boost,
        final_score=final_score,
        candidate=candidate,
    )
