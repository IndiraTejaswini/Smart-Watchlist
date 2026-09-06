"""Pure universe candidate generation across the eight signal families."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from app.analytics.abnormality import AbnormalityScores
from app.analytics.fact_bundle import FactBundle
from app.analytics.hashing import compute_inputs_hash
from app.analytics.mpm import MPMResult


class SignalFamily(StrEnum):
    PRICE_MPM = "PRICE_MPM"
    INTRADAY_SWING = "INTRADAY_SWING"
    TURNOVER_SURGE = "TURNOVER_SURGE"
    DELIVERY_ACCUMULATION = "DELIVERY_ACCUMULATION"
    MULTI_SESSION_DRIFT = "MULTI_SESSION_DRIFT"
    EXTREME_52W = "EXTREME_52W"
    CIRCUIT_LOCK = "CIRCUIT_LOCK"
    MATERIAL_FILING = "MATERIAL_FILING"


@dataclass(frozen=True)
class Candidate:
    symbol: str
    date: date
    signal_families: frozenset[SignalFamily]
    primary_signal: SignalFamily
    sar: float
    turnover_z: float | None
    delivery_z: float | None
    material_announcements_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    inputs_hash: str = ""
    linked_announcement_ids: tuple[str, ...] = ()
    primary_category: str | None = None
    is_explained: bool = False
    revision: int = 1
    status: str = "PROVISIONAL"
    was_restated: bool = False
    superseded_by_id: str | None = None
    id: str | None = None

    @property
    def has_material_filing(self) -> bool:
        return self.material_announcements_count > 0


_MATERIAL_TERMS = (
    "FINANCIAL RESULTS",
    "RESULT",
    "ACQUISITION",
    "REGULATORY",
    "BOARD MEETING",
)


def _has_material_filing(bundle: FactBundle) -> bool:
    return any(
        any(term in announcement.category.upper() or term in announcement.subject.upper()
            for term in _MATERIAL_TERMS)
        for announcement in bundle.recent_announcements
    )


def generate_candidate(
    bundle: FactBundle,
    mpm: MPMResult,
    abnormality: AbnormalityScores,
) -> Candidate | None:
    """Generate one candidate, returning None when no family is triggered."""
    families: set[SignalFamily] = set()
    if mpm.close_triggered:
        families.add(SignalFamily.PRICE_MPM)
    if mpm.intraday_triggered and not mpm.close_triggered:
        families.add(SignalFamily.INTRADAY_SWING)
    if abnormality.turnover_z is not None and abnormality.turnover_z >= 2.5:
        families.add(SignalFamily.TURNOVER_SURGE)
    if abnormality.delivery_z is not None and abnormality.delivery_z >= 2.0:
        families.add(SignalFamily.DELIVERY_ACCUMULATION)
    if abnormality.scar_3d is not None and abs(abnormality.scar_3d) >= 2.5:
        families.add(SignalFamily.MULTI_SESSION_DRIFT)
    if (
        abnormality.dist_52w_high_pct is not None
        and abnormality.dist_52w_high_pct >= -1.0
    ) or (
        abnormality.dist_52w_low_pct is not None
        and abnormality.dist_52w_low_pct <= 1.0
    ):
        families.add(SignalFamily.EXTREME_52W)
    if mpm.is_circuit_override:
        families.add(SignalFamily.CIRCUIT_LOCK)
    material_count = sum(
        1 for announcement in bundle.recent_announcements
        if any(term in announcement.category.upper() or term in announcement.subject.upper()
               for term in _MATERIAL_TERMS)
    )
    if material_count:
        families.add(SignalFamily.MATERIAL_FILING)
    if not families:
        return None
    primary = next(family for family in SignalFamily if family in families)
    return Candidate(
        symbol=bundle.symbol,
        date=bundle.date,
        signal_families=frozenset(families),
        primary_signal=primary,
        sar=abnormality.sar,
        turnover_z=abnormality.turnover_z,
        delivery_z=abnormality.delivery_z,
        material_announcements_count=material_count,
        metadata={"scar_3d": abnormality.scar_3d, "quality_flag": abnormality.quality_flag},
        inputs_hash=compute_inputs_hash(bundle),
    )


def generate_candidates(
    fixtures: list[tuple[FactBundle, MPMResult, AbnormalityScores]],
) -> list[Candidate]:
    return [
        candidate
        for bundle, mpm, abnormality in fixtures
        if (candidate := generate_candidate(bundle, mpm, abnormality)) is not None
    ]
