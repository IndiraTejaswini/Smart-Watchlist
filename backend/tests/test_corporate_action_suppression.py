from datetime import UTC, date, datetime
from decimal import Decimal

from app.analytics.abnormality import AbnormalityScores
from app.analytics.corporate_action_notice import CorporateActionNotice
from app.analytics.engine import (
    CorporateAction,
    CorporateActionRegistry,
    is_ex_date_in_opening_pause,
    process_live_tick,
    score_candidates,
)
from app.analytics.fact_bundle import FactBundle
from app.analytics.mpm import MPMResult
from tests.fixtures.golden_corporate_actions import GOLDEN_CORPORATE_ACTIONS


def _fixture_inputs(
    symbol: str, event_date: date
) -> tuple[FactBundle, MPMResult, AbnormalityScores]:
    return (
        FactBundle(symbol=symbol, date=event_date),
        MPMResult(True, True, 0.05, 0.05, -0.5, 0.0, 0.5, False),
        AbnormalityScores(
            symbol=symbol,
            date=event_date,
            ar=0.0,
            sar=3.0,
            car_3d=None,
            scar_3d=3.0,
            turnover_z=3.0,
            delivery_z=3.0,
            dist_52w_high_pct=-0.5,
            dist_52w_low_pct=None,
            quality_flag="CLEAN",
        ),
    )


def _registry() -> CorporateActionRegistry:
    return CorporateActionRegistry(
        CorporateAction(
            symbol=fixture.symbol,
            ex_date=fixture.ex_date,
            cum_date=fixture.cum_date,
            action_type=fixture.action_type,
            as_traded_cum_close=fixture.as_traded_close,
            adjusted_prev_close=fixture.expected_adjusted_close,
            adjustment_factor=fixture.price_factor,
            ratio_or_amount=fixture.ratio or f"Rs {fixture.dividend_amount}/share",
            source_url=fixture.source_url,
        )
        for fixture in GOLDEN_CORPORATE_ACTIONS
    )


def test_golden_actions_suppress_signals_and_emit_one_notice_each() -> None:
    registry = _registry()
    candidates, notices = score_candidates(
        [_fixture_inputs(fixture.symbol, fixture.ex_date) for fixture in GOLDEN_CORPORATE_ACTIONS],
        registry=registry,
        notice_created_at=datetime(2024, 6, 21, 4, 0, tzinfo=UTC),
    )

    assert candidates == []
    assert len(notices) == 3
    assert all(isinstance(notice, CorporateActionNotice) for notice in notices)
    bpcl = next(notice for notice in notices if notice.symbol == "BPCL")
    assert bpcl.as_traded_cum_close == Decimal("617.50")
    assert bpcl.adjusted_prev_close == Decimal("308.75")
    assert bpcl.adjustment_factor == Decimal("0.500000")


def test_ex_date_opening_pause_is_strictly_fifteen_minutes() -> None:
    registry = _registry()
    assert is_ex_date_in_opening_pause(
        "BPCL", datetime.fromisoformat("2024-06-21T09:20:00+05:30"), registry
    )
    assert not is_ex_date_in_opening_pause(
        "BPCL", datetime.fromisoformat("2024-06-21T09:30:00+05:30"), registry
    )


def test_live_tick_is_buffered_but_never_scored_on_ex_date() -> None:
    registry = _registry()
    buffered: list[str] = []
    scored: list[str] = []
    notices: list[CorporateActionNotice] = []

    result = process_live_tick(
        symbol="BPCL",
        tick_time=datetime.fromisoformat("2024-06-21T09:20:00+05:30"),
        score=lambda: scored.append("scored"),
        buffer_tick=lambda: buffered.append("buffered"),
        registry=registry,
        dispatch_notice=notices.append,
    )

    assert result is None
    assert buffered == ["buffered"]
    assert scored == []
    assert notices == []
