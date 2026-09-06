from datetime import date
from decimal import Decimal

from app.analytics.attribution import (
    AttributionCategory,
    classify_market_attribution,
    generate_market_wide_rollup,
)
from app.analytics.candidates import Candidate, SignalFamily
from app.analytics.fact_bundle import FactBundle, MarketModelFact


def _candidate(symbol: str, sar: float) -> Candidate:
    return Candidate(
        symbol=symbol,
        date=date(2026, 4, 6),
        signal_families=frozenset({SignalFamily.PRICE_MPM}),
        primary_signal=SignalFamily.PRICE_MPM,
        sar=sar,
        turnover_z=None,
        delivery_z=None,
        material_announcements_count=0,
    )


def _bundle(symbol: str, beta: float, quality: str = "CLEAN") -> FactBundle:
    return FactBundle(
        symbol=symbol,
        date=date(2026, 4, 6),
        market_model=MarketModelFact(
            alpha=Decimal("0"),
            beta=Decimal(str(beta)),
            r2=Decimal("0.9"),
            resid_sd=Decimal("0.015"),
            n_obs=120,
            quality_flag=quality,
        ),
    )


def test_index_slide_collapses_market_wide_candidates() -> None:
    candidates = [_candidate(f"LARGE_{i}", 0.5 + i / 20) for i in range(20)]
    attributions = [
        classify_market_attribution(candidate, _bundle(candidate.symbol, 1.2 + i / 20),
                                     Decimal("-0.022"))
        for i, candidate in enumerate(candidates)
    ]

    assert sum(
        attribution.category is AttributionCategory.MARKET_WIDE
        for attribution in attributions
    ) >= 12
    retained, rollup = generate_market_wide_rollup(
        candidates, attributions, "NIFTY50", Decimal("-0.022")
    )
    assert rollup is not None
    assert len(rollup.symbols) >= 12
    assert len(retained) == len(candidates) - len(rollup.symbols)


def test_market_sar_ceiling_keeps_high_beta_panic_independent() -> None:
    candidate = _candidate("HIGH_BETA_PANIC", 2.8)
    attribution = classify_market_attribution(
        candidate, _bundle(candidate.symbol, 2.5), Decimal("-0.025")
    )

    assert attribution.category is AttributionCategory.IDIOSYNCRATIC
    assert not attribution.is_rollup_eligible
    retained, rollup = generate_market_wide_rollup(
        [candidate], [attribution], "NIFTY50", Decimal("-0.025")
    )
    assert retained == [candidate]
    assert rollup is None
