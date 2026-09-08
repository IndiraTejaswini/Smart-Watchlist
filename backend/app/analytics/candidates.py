"""Pure universe candidate generation across the eight signal families."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from app.analytics.abnormality import AbnormalityScores
from app.analytics.fact_bundle import FactBundle
from app.analytics.hashing import compute_inputs_hash
from app.analytics.mpm import MPMResult
from app.constants import (
    DELIVERY_Z_CANDIDATE_MIN,
    EXTREME_PROXIMITY_PCT,
    SCAR_MIN,
    TURNOVER_Z_CANDIDATE_MIN,
)


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


def candidate_from_row(row: Mapping[str, Any]) -> Candidate:
    """The single row-to-``Candidate`` mapper for every reader of the table.

    Two call sites (``digest/__init__.py`` and ``api/brief_explain.py``) used
    to each hand-roll a subset of this mapping and silently dropped
    ``primary_category``, ``is_explained``, ``id``, ``revision``, ``status``,
    ``was_restated`` and ``linked_announcement_ids`` — every reader saw the
    dataclass defaults for those fields regardless of what was persisted.
    """
    families = frozenset(
        SignalFamily(value)
        for value in (row.get("signal_families") or [row["primary_signal"]])
    )
    metadata = dict(row.get("metadata") or {})
    if row.get("sector") is not None:
        metadata.setdefault("sector", row["sector"])
    if row.get("scar_3d") is not None:
        metadata.setdefault("scar_3d", float(row["scar_3d"]))
    linked = row.get("linked_announcement_ids") or ()
    return Candidate(
        symbol=str(row["symbol"]),
        date=row["date"],
        signal_families=families,
        primary_signal=SignalFamily(str(row["primary_signal"])),
        sar=float(row["sar"]),
        turnover_z=None if row.get("turnover_z") is None else float(row["turnover_z"]),
        delivery_z=None if row.get("delivery_z") is None else float(row["delivery_z"]),
        material_announcements_count=(
            int(row["material_announcements_count"])
            if row.get("material_announcements_count") is not None
            else (1 if row.get("has_material_filing") else 0)
        ),
        metadata=metadata,
        inputs_hash=str(row.get("inputs_hash", "")),
        linked_announcement_ids=tuple(str(value) for value in linked),
        primary_category=row.get("primary_category"),
        is_explained=bool(row.get("is_explained", False)),
        revision=int(row.get("revision", 1)),
        status=str(row.get("status", "PROVISIONAL")),
        was_restated=bool(row.get("was_restated", False)),
        superseded_by_id=row.get("superseded_by_id"),
        id=row.get("id"),
    )


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
    if abnormality.turnover_z is not None and abnormality.turnover_z >= TURNOVER_Z_CANDIDATE_MIN:
        families.add(SignalFamily.TURNOVER_SURGE)
    if abnormality.delivery_z is not None and abnormality.delivery_z >= DELIVERY_Z_CANDIDATE_MIN:
        families.add(SignalFamily.DELIVERY_ACCUMULATION)
    if abnormality.scar_3d is not None and abs(abnormality.scar_3d) >= SCAR_MIN:
        families.add(SignalFamily.MULTI_SESSION_DRIFT)
    if (
        abnormality.dist_52w_high_pct is not None
        and abnormality.dist_52w_high_pct >= -EXTREME_PROXIMITY_PCT
    ) or (
        abnormality.dist_52w_low_pct is not None
        and abnormality.dist_52w_low_pct <= EXTREME_PROXIMITY_PCT
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
