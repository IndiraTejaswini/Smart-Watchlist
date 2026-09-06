from datetime import date, timedelta
from decimal import Decimal

from app.analytics.liquidity import (
    evaluate_liquidity_state,
    filter_illiquid_candidates,
)


def test_liquidity_hysteresis_resists_oscillation() -> None:
    day = date(2026, 4, 6)
    state = evaluate_liquidity_state("SYM_OSC", day, Decimal("13000000.00"), None)
    values = (
        "10500000.00",
        "9500000.00",
        "10200000.00",
        "8500000.00",
        "7900000.00",
        "9500000.00",
        "10500000.00",
        "11800000.00",
        "12100000.00",
    )
    for index, value in enumerate(values, 1):
        state = evaluate_liquidity_state(
            "SYM_OSC", day + timedelta(days=index), Decimal(value), state
        )
        if index < 5:
            assert state.is_liquid
            assert not state.state_flipped
        if index == 5:
            assert not state.is_liquid
            assert state.state_flipped
        if 5 < index < 9:
            assert not state.is_liquid
            assert not state.state_flipped
        if index == 9:
            assert state.is_liquid
            assert state.state_flipped
            assert state.last_state_change_date == day + timedelta(days=9)


def test_liquidity_cold_start_and_unknown_filter_behavior() -> None:
    assert evaluate_liquidity_state(
        "LIQUID", date(2026, 4, 6), Decimal("10500000.00"), None
    ).is_liquid
    assert not evaluate_liquidity_state(
        "ILLIQUID", date(2026, 4, 6), Decimal("9500000.00"), None
    ).is_liquid
    assert filter_illiquid_candidates([]) == []
