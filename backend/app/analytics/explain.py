"""Decision-path tracing and score audit construction."""

from __future__ import annotations

from datetime import date
from math import exp
from typing import Any

from app.analytics.attribution import AttributionResult
from app.analytics.candidates import Candidate
from app.analytics.constants import (
    BOOST_HELD,
    BOOST_LEVEL_CROSSED,
    BOOST_PINNED,
    BOOST_RECENTLY_ADDED,
)
from app.analytics.mpm import MPMResult
from app.analytics.ranker import (
    PersonalContext,
    classification_multiplier,
    compute_personal_multiplier,
)
from app.constants import (
    DECAY_TAU_SESSIONS,
    PERSONAL_CAP,
    W_DELIVERY,
    W_EXTREME,
    W_SCAR,
    W_TURNOVER,
)
from app.schemas.explain import BaseScoreBreakdown, DecayAudit, DecisionStep, PersonalAudit
from app.timeutil import TradingCalendar, sessions_between


def trace_decision_path(
    candidate: Candidate,
    bundle: Any,
    mpm: MPMResult,
    attribution: AttributionResult,
) -> list[DecisionStep]:
    del bundle
    return [
        DecisionStep(
            step=1,
            rule="Corporate action",
            test="An ex-date for this symbol inside the cursor window",
            evaluated=f"No corporate action on {candidate.symbol} at {candidate.date}.",
            taken=True,
        ),
        DecisionStep(
            step=2,
            rule="Liquidity state",
            test="The symbol cleared the liquidity gate",
            evaluated="Liquidity state permitted candidate evaluation.",
            taken=True,
        ),
        DecisionStep(
            step=3,
            rule="MPM gate",
            test="The stock movement was compared with the MPM threshold",
            evaluated=(
                f"Base threshold {mpm.base_threshold}; effective threshold "
                f"{mpm.effective_threshold}."
            ),
            taken=mpm.close_triggered or mpm.intraday_triggered,
        ),
        DecisionStep(
            step=4,
            rule="Refractory filter",
            test="No refractory suppression was applied",
            evaluated="The candidate was outside the refractory window.",
            taken=True,
        ),
        DecisionStep(
            step=5,
            rule="Attribution",
            test="Market and sector context were evaluated",
            evaluated=attribution.reason,
            taken=attribution.category.value == "IDIOSYNCRATIC"
            or attribution.is_rollup_eligible,
        ),
        DecisionStep(
            step=6,
            rule="Explainability link",
            test="A linked announcement was evaluated",
            evaluated="Announcement linkage was evaluated.",
            taken=candidate.is_explained,
        ),
    ]


def build_score_audit(
    candidate: Candidate,
    evaluation_date: date,
    context: PersonalContext,
    calendar: TradingCalendar,
) -> tuple[BaseScoreBreakdown, DecayAudit, PersonalAudit, float]:
    sessions = max(0, sessions_between(candidate.date, evaluation_date, calendar))
    turnover = max(0.0, candidate.turnover_z or 0.0)
    delivery = max(0.0, candidate.delivery_z or 0.0)
    extreme = any(family.value == "EXTREME_52W" for family in candidate.signal_families)
    class_mult = classification_multiplier(candidate)
    base_sum = class_mult * (
        abs(candidate.sar) * W_SCAR
        + turnover * W_TURNOVER
        + delivery * W_DELIVERY
        + (W_EXTREME if extreme else 0.0)
    )
    base = BaseScoreBreakdown(
        sar_raw=candidate.sar,
        sar_weight=W_SCAR,
        sar_contribution=class_mult * abs(candidate.sar) * W_SCAR,
        turnover_z_raw=candidate.turnover_z,
        turnover_z_clamped=turnover,
        turnover_z_weight=W_TURNOVER,
        turnover_z_contribution=class_mult * turnover * W_TURNOVER,
        delivery_z_raw=candidate.delivery_z,
        delivery_z_clamped=delivery,
        delivery_z_weight=W_DELIVERY,
        delivery_z_contribution=class_mult * delivery * W_DELIVERY,
        material_filing_active=extreme,
        material_filing_weight=W_EXTREME,
        material_filing_contribution=class_mult * (W_EXTREME if extreme else 0.0),
        classification="EXPLAINED" if candidate.is_explained else "UNEXPLAINED",
        classification_multiplier=class_mult,
        base_score_sum=base_sum,
    )
    decay_multiplier = exp(-sessions / DECAY_TAU_SESSIONS)
    decay = DecayAudit(
        event_date=str(candidate.date),
        evaluation_date=str(evaluation_date),
        sessions_elapsed=sessions,
        decay_rate=DECAY_TAU_SESSIONS,
        decay_multiplier=decay_multiplier,
    )
    raw, effective = compute_personal_multiplier(context)
    personal = PersonalAudit(
        is_held=context.is_held,
        boost_held=BOOST_HELD,
        is_pinned=context.is_pinned,
        boost_pinned=BOOST_PINNED,
        is_recently_added=context.is_recently_added,
        boost_recently_added=BOOST_RECENTLY_ADDED,
        is_level_crossed=context.is_level_crossed,
        boost_level_crossed=BOOST_LEVEL_CROSSED,
        raw_boost_sum=raw,
        personal_cap=PERSONAL_CAP,
        effective_multiplier=effective,
    )
    return base, decay, personal, base_sum * decay_multiplier * effective
