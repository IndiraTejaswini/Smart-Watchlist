"""Systematic market attribution and cross-sectional rollups."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from statistics import median

from app.analytics.candidates import Candidate
from app.analytics.fact_bundle import FactBundle
from app.constants import (
    MARKET_ATTRIB_RATIO,
    MARKET_SAR_CEILING,
    MARKET_WIDE_BENCHMARK_MOVE_MIN,
    MARKET_WIDE_MIN_SYMBOLS,
    SECTOR_MIN_PEERS,
)


class AttributionCategory(StrEnum):
    MARKET_WIDE = "MARKET_WIDE"
    IDIOSYNCRATIC = "IDIOSYNCRATIC"
    SECTOR_PEER = "SECTOR_PEER"


@dataclass(frozen=True)
class AttributionResult:
    symbol: str
    date: date
    category: AttributionCategory
    market_ratio: float
    sar: float
    beta: float
    is_rollup_eligible: bool
    reason: str


@dataclass(frozen=True)
class MarketWideRollup:
    date: date
    benchmark_symbol: str
    benchmark_return: float
    affected_symbols_count: int
    symbols: tuple[str, ...]
    median_beta: float
    median_sar: float
    summary_text: str


@dataclass(frozen=True)
class SectorWideRollup:
    sector: str
    date: date
    direction: int
    affected_symbols: tuple[str, ...]
    symbol_count: int
    median_return: float
    median_sar: float
    summary_text: str
    created_at: datetime


def _same_sign(left: float, right: float) -> bool:
    return (left > 0 and right > 0) or (left < 0 and right < 0)


def classify_market_attribution(
    candidate: Candidate,
    bundle: FactBundle,
    benchmark_return: Decimal,
    market_sar_ceiling: float = MARKET_SAR_CEILING,
) -> AttributionResult:
    """Classify a candidate using its market-model residual decomposition."""
    model = bundle.market_model
    if model is None or model.quality_flag == "DEGRADED":
        return AttributionResult(
            symbol=candidate.symbol,
            date=candidate.date,
            category=AttributionCategory.IDIOSYNCRATIC,
            market_ratio=0.0,
            sar=candidate.sar,
            beta=float(model.beta) if model is not None else 0.0,
            is_rollup_eligible=False,
            reason="Market model baseline missing or degraded.",
        )

    benchmark = float(benchmark_return)
    beta = float(model.beta)
    residual_sd = float(model.resid_sd)
    alpha = float(model.alpha)
    systematic_return = beta * benchmark
    total_return = candidate.sar * residual_sd + (alpha + systematic_return)
    market_ratio = (
        abs(systematic_return) / abs(total_return) if total_return != 0.0 else 0.0
    )

    if abs(candidate.sar) >= market_sar_ceiling:
        return AttributionResult(
            symbol=candidate.symbol,
            date=candidate.date,
            category=AttributionCategory.IDIOSYNCRATIC,
            market_ratio=market_ratio,
            sar=candidate.sar,
            beta=beta,
            is_rollup_eligible=False,
            reason="SAR exceeds market ceiling; significant idiosyncratic shock present.",
        )

    if (
        abs(benchmark) >= MARKET_WIDE_BENCHMARK_MOVE_MIN
        and _same_sign(total_return, benchmark)
        and market_ratio >= MARKET_ATTRIB_RATIO
    ):
        return AttributionResult(
            symbol=candidate.symbol,
            date=candidate.date,
            category=AttributionCategory.MARKET_WIDE,
            market_ratio=market_ratio,
            sar=candidate.sar,
            beta=beta,
            is_rollup_eligible=True,
            reason="Return is directionally aligned with a material benchmark move.",
        )

    return AttributionResult(
        symbol=candidate.symbol,
        date=candidate.date,
        category=AttributionCategory.IDIOSYNCRATIC,
        market_ratio=market_ratio,
        sar=candidate.sar,
        beta=beta,
        is_rollup_eligible=False,
        reason="Market ratio or direction threshold not met.",
    )


def generate_market_wide_rollup(
    candidates: list[Candidate],
    attributions: list[AttributionResult],
    benchmark_symbol: str,
    benchmark_return: Decimal,
) -> tuple[list[Candidate], MarketWideRollup | None]:
    """Collapse three or more eligible market-wide candidates into one line."""
    attribution_by_symbol = {attribution.symbol: attribution for attribution in attributions}
    rollup_group = [
        candidate
        for candidate in candidates
        if (
            (attribution := attribution_by_symbol.get(candidate.symbol)) is not None
            and attribution.category is AttributionCategory.MARKET_WIDE
            and attribution.is_rollup_eligible
        )
    ]
    if len(rollup_group) < MARKET_WIDE_MIN_SYMBOLS:
        return candidates, None

    symbols = tuple(candidate.symbol for candidate in rollup_group)
    group_attributions = [attribution_by_symbol[symbol] for symbol in symbols]
    first = rollup_group[0]
    rollup = MarketWideRollup(
        date=first.date,
        benchmark_symbol=benchmark_symbol,
        benchmark_return=float(benchmark_return),
        affected_symbols_count=len(rollup_group),
        symbols=symbols,
        median_beta=float(median(attribution.beta for attribution in group_attributions)),
        median_sar=float(median(attribution.sar for attribution in group_attributions)),
        summary_text=(
            f"{len(rollup_group)} symbols moved with {benchmark_symbol} "
            f"({float(benchmark_return):.2%}); market-wide attribution."
        ),
    )
    suppressed = {candidate.symbol for candidate in rollup_group}
    retained = [candidate for candidate in candidates if candidate.symbol not in suppressed]
    return retained, rollup


def _candidate_return(candidate: Candidate) -> float:
    """Read the observed return when available, falling back to SAR direction."""
    for key in ("return", "stock_return", "abnormal_return"):
        value = candidate.metadata.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return float(candidate.sar)


def evaluate_sector_grouping(
    candidates: list[Candidate],
    symbol_sector_map: dict[str, str | None],
) -> tuple[list[Candidate], list[SectorWideRollup]]:
    """Collapse sector peers with a directional quorum of three or more.

    Grouped by (sector, direction, date): candidates accumulate across the
    whole cursor window (days or weeks), and a peer group that ignored date
    would blend unrelated sessions into one summary — a Materials rally in
    March and a Materials sell-off in June credited as the same event. Mirrors
    the per-day grouping `_evaluate_market_wide` already uses.
    """
    groups: dict[tuple[str, int, date], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        sector = symbol_sector_map.get(candidate.symbol)
        if sector in (None, "", "UNASSIGNED"):
            continue
        value = _candidate_return(candidate)
        direction = 1 if value > 0 else -1 if value < 0 else 0
        groups[(sector, direction, candidate.date)].append(candidate)

    rollups: list[SectorWideRollup] = []
    # Keyed by (symbol, date), not symbol alone: a symbol trades most days in
    # the cursor window, and matching on symbol name would let one day's
    # rollup silently suppress every other day that same symbol shows up as
    # its own candidate — swallowing the whole Brief window over a peer group
    # formed on a single unrelated session.
    suppressed_keys: set[tuple[str, date]] = set()
    for (sector, direction, group_date), group in groups.items():
        eligible = [
            candidate for candidate in group if candidate.material_announcements_count == 0
        ]
        if len(group) < SECTOR_MIN_PEERS or len(eligible) < SECTOR_MIN_PEERS or direction == 0:
            continue
        symbols = tuple(candidate.symbol for candidate in eligible)
        returns = [_candidate_return(candidate) for candidate in eligible]
        rollups.append(
            SectorWideRollup(
                sector=sector,
                date=group_date,
                direction=direction,
                affected_symbols=symbols,
                symbol_count=len(eligible),
                median_return=float(median(returns)),
                median_sar=float(median(candidate.sar for candidate in eligible)),
                summary_text=(
                    f"{len(eligible)} {sector} symbols moved together "
                    f"({('rally' if direction > 0 else 'sell-off')})."
                ),
                created_at=datetime.now(UTC),
            )
        )
        suppressed_keys.update((candidate.symbol, candidate.date) for candidate in eligible)
    retained = [
        candidate for candidate in candidates
        if (candidate.symbol, candidate.date) not in suppressed_keys
    ]
    return retained, rollups
