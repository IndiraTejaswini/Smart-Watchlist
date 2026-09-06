"""Static guard preventing share-count fields in turnover baselines."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "app" / "analytics" / "turnover.py"
FORBIDDEN = {"volume", "raw_volume", "adj_volume", "traded_qty"}


def _assert_turnover_only(source: str) -> None:
    tree = ast.parse(source)
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "estimate_turnover_baselines"
    )
    for node in ast.walk(target):
        if isinstance(node, ast.Name):
            assert node.id not in FORBIDDEN, (
                f"turnover baseline references forbidden share-count field {node.id!r}"
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not any(
                forbidden in node.value for forbidden in FORBIDDEN
            ), "turnover baseline contains a forbidden share-count field"


def test_turnover_baseline_excludes_share_count_fields() -> None:
    _assert_turnover_only(MODULE.read_text(encoding="utf-8"))


def test_guard_rejects_volume_reference() -> None:
    with pytest.raises(AssertionError, match="forbidden"):
        _assert_turnover_only(
            """
def estimate_turnover_baselines(frame):
    volume = frame["volume"]
    return volume
"""
        )
