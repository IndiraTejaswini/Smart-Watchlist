"""Acceptance tests for the eight candidate signal families."""

from datetime import date, datetime

from app.analytics.abnormality import AbnormalityScores
from app.analytics.candidates import (
    SignalFamily,
    generate_candidate,
    generate_candidates,
)
from app.analytics.fact_bundle import AnnouncementFact, FactBundle
from app.analytics.mpm import MPMResult

TARGET = date(2026, 4, 6)


def _inputs(symbol: str, family: SignalFamily):
    announcement = (
        AnnouncementFact(datetime(2026, 4, 6), "Financial Results", "Financial Results", None)
        if family is SignalFamily.MATERIAL_FILING
        else ()
    )
    bundle = FactBundle(
        symbol=symbol,
        date=TARGET,
        recent_announcements=(announcement,) if announcement else (),
    )
    mpm = MPMResult(
        close_triggered=family in {SignalFamily.PRICE_MPM, SignalFamily.CIRCUIT_LOCK},
        intraday_triggered=family is SignalFamily.INTRADAY_SWING,
        effective_threshold=0.05,
        base_threshold=0.05,
        stock_return=0.0,
        index_return=0.0,
        max_excursion=0.06,
        is_circuit_override=family is SignalFamily.CIRCUIT_LOCK,
    )
    abnormality = AbnormalityScores(
        symbol=symbol,
        date=TARGET,
        ar=0.0,
        sar=0.0,
        car_3d=None,
        scar_3d=2.8 if family is SignalFamily.MULTI_SESSION_DRIFT else None,
        turnover_z=3.2 if family is SignalFamily.TURNOVER_SURGE else None,
        delivery_z=2.4 if family is SignalFamily.DELIVERY_ACCUMULATION else None,
        dist_52w_high_pct=-0.5 if family is SignalFamily.EXTREME_52W else None,
        dist_52w_low_pct=None,
        quality_flag="CLEAN",
    )
    return bundle, mpm, abnormality


def test_universe_covers_all_signal_families() -> None:
    fixtures = [_inputs(f"SYM_{index:02d}", family) for index, family in enumerate(SignalFamily, 1)]
    candidates = generate_candidates(fixtures)
    triggered = {family for candidate in candidates for family in candidate.signal_families}
    assert triggered == set(SignalFamily)


def test_material_filing_generates_candidate_without_price_move() -> None:
    bundle, mpm, abnormality = _inputs("SYM_08", SignalFamily.MATERIAL_FILING)
    candidate = generate_candidate(bundle, mpm, abnormality)
    assert candidate is not None
    assert candidate.sar == 0.0
    assert SignalFamily.MATERIAL_FILING in candidate.signal_families
    assert candidate.material_announcements_count == 1
