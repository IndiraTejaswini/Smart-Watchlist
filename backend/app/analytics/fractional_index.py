"""Fractional positions for stable, zero-rewrite list reordering."""

from __future__ import annotations

from decimal import Decimal

DEFAULT_POSITION = Decimal("1000.0000000000000000")
POSITION_STEP = Decimal("100.0000000000000000")
POSITION_MAX_STR_LEN = 32


def generate_midpoint_position(
    prev_pos: Decimal | None, next_pos: Decimal | None
) -> Decimal:
    if prev_pos is None and next_pos is None:
        return DEFAULT_POSITION
    if prev_pos is None:
        assert next_pos is not None
        return next_pos - POSITION_STEP
    if next_pos is None:
        return prev_pos + POSITION_STEP
    if not prev_pos < next_pos:
        raise ValueError("prev_pos must be less than next_pos")
    return (prev_pos + next_pos) / Decimal("2")


def should_trigger_rebalance(position: Decimal | str) -> bool:
    normalized = str(position).rstrip("0").rstrip(".")
    return len(normalized) > POSITION_MAX_STR_LEN
