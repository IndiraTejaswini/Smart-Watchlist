"""Acceptance tests for abnormality scoring."""

from decimal import Decimal

from app.analytics.abnormality import compute_abnormal_return, compute_sar, compute_scar


def test_synthetic_shock_recovers_three_standard_deviations() -> None:
    ar = compute_abnormal_return(
        Decimal("107"), Decimal("100"), Decimal("0.01"), 0.0, 1.0
    )
    assert abs(compute_sar(ar, 0.02) - 3.0) < 0.05


def test_holiday_crossing_scar_uses_trading_session_count() -> None:
    assert abs(compute_scar(0.06, 0.015, 3) - 2.309401) < 1e-4
