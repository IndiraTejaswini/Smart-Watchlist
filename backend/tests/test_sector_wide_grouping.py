from datetime import date

from app.analytics.attribution import evaluate_sector_grouping
from app.analytics.candidates import Candidate, SignalFamily


def _candidate(symbol: str, value: float, *, material: bool = False) -> Candidate:
    return Candidate(
        symbol=symbol,
        date=date(2026, 4, 6),
        signal_families=frozenset({SignalFamily.PRICE_MPM}),
        primary_signal=SignalFamily.PRICE_MPM,
        sar=value,
        turnover_z=None,
        delivery_z=None,
        material_announcements_count=1 if material else 0,
        metadata={"return": value},
    )


def test_pharma_peers_collapse_into_one_sector_rollup() -> None:
    candidates = [
        _candidate("CIPLA", 0.035),
        _candidate("SUNPHARMA", 0.04),
        _candidate("DRREDDY", 0.045),
        _candidate("LUPIN", 0.05),
    ]
    retained, rollups = evaluate_sector_grouping(
        candidates, {candidate.symbol: "NIFTY_PHARMA" for candidate in candidates}
    )

    assert len(rollups) == 1
    assert rollups[0].sector == "NIFTY_PHARMA"
    assert rollups[0].symbol_count == 4
    assert set(rollups[0].affected_symbols) == {
        "CIPLA",
        "SUNPHARMA",
        "DRREDDY",
        "LUPIN",
    }
    assert retained == []


def test_unassigned_symbol_is_never_grouped() -> None:
    new_ipo = _candidate("NEW_IPO", 0.04)
    pharma = [_candidate("CIPLA", 0.035), _candidate("LUPIN", 0.045)]
    retained, rollups = evaluate_sector_grouping(
        [*pharma, new_ipo],
        {"CIPLA": "NIFTY_PHARMA", "LUPIN": "NIFTY_PHARMA", "NEW_IPO": "UNASSIGNED"},
    )

    assert rollups == []
    assert retained == [*pharma, new_ipo]


def test_sub_quorum_sector_peers_remain_individual() -> None:
    candidates = [_candidate("AUTO_A", 0.03), _candidate("AUTO_B", 0.04)]
    retained, rollups = evaluate_sector_grouping(
        candidates, {"AUTO_A": "NIFTY_AUTO", "AUTO_B": "NIFTY_AUTO"}
    )

    assert rollups == []
    assert retained == candidates


def test_material_filing_peer_is_preserved_outside_rollup() -> None:
    candidates = [
        _candidate("CIPLA", 0.035),
        _candidate("SUNPHARMA", 0.04),
        _candidate("DRREDDY", 0.045),
        _candidate("LUPIN", 0.05, material=True),
    ]
    retained, rollups = evaluate_sector_grouping(
        candidates, {candidate.symbol: "NIFTY_PHARMA" for candidate in candidates}
    )

    assert len(rollups) == 1
    assert rollups[0].symbol_count == 3
    assert retained == [candidates[-1]]
