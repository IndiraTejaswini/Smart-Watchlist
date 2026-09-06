"""Acceptance tests for the Material Price Movement gate."""

from decimal import Decimal

from app.analytics.mpm import evaluate_mpm_gate


def test_low_price_threshold_trigger() -> None:
    result = evaluate_mpm_gate(
        Decimal("95"), Decimal("99.845"), Decimal("95"), Decimal("99.845"), Decimal("0")
    )
    assert result.close_triggered
    assert result.base_threshold == 0.05


def test_low_price_threshold_not_triggered() -> None:
    result = evaluate_mpm_gate(
        Decimal("95"), Decimal("99.655"), Decimal("95"), Decimal("99.655"), Decimal("0")
    )
    assert not result.close_triggered


def test_same_direction_index_return_raises_threshold() -> None:
    result = evaluate_mpm_gate(
        Decimal("150"), Decimal("156.3"), Decimal("150"), Decimal("156.3"), Decimal("0.015")
    )
    assert not result.close_triggered
    assert result.effective_threshold == 0.055


def test_opposite_direction_keeps_base_threshold() -> None:
    result = evaluate_mpm_gate(
        Decimal("150"), Decimal("156.3"), Decimal("150"), Decimal("156.3"), Decimal("-0.015")
    )
    assert result.close_triggered
    assert result.effective_threshold == 0.04


def test_circuit_override_triggers_close_gate() -> None:
    result = evaluate_mpm_gate(
        Decimal("500"), Decimal("510"), Decimal("500"), Decimal("510"), Decimal("0"),
        is_circuit_band_hit=True,
    )
    assert result.close_triggered
    assert result.is_circuit_override


def test_intraday_excursion_uses_base_threshold_only() -> None:
    result = evaluate_mpm_gate(
        Decimal("200"), Decimal("212"), Decimal("199.6"), Decimal("200.4"), Decimal("0")
    )
    assert not result.close_triggered
    assert result.intraday_triggered
    assert result.max_excursion == 0.06
