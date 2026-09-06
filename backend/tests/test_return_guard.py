"""Static guard against passing unadjusted prices to return calculations."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ABNORMALITY = (
    Path(__file__).resolve().parents[1] / "app" / "analytics" / "abnormality.py"
)
RETURN_FUNCTION_MARKERS = ("return", "abnormal")
RAW_NAMES = {"close", "prev_close", "price", "raw_close"}


def _validate_return_inputs(source: str) -> None:
    tree = ast.parse(source)
    return_functions: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(marker in node.name.lower() for marker in RETURN_FUNCTION_MARKERS):
            continue
        return_functions.add(node.name)
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if argument.arg in RAW_NAMES or (
                any(token in argument.arg.lower() for token in ("close", "price"))
                and not argument.arg.startswith("adj_")
            ):
                raise AssertionError(
                    f"{node.name} accepts non-adjusted parameter {argument.arg!r}"
                )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id not in return_functions:
            continue
        for call_argument in node.args:
            if isinstance(call_argument, ast.Name):
                valid = (
                    call_argument.id.startswith("adj_")
                    or not any(
                        token in call_argument.id.lower() for token in ("close", "price")
                    )
                )
            elif isinstance(call_argument, ast.Subscript):
                valid = (
                    isinstance(call_argument.value, ast.Name)
                    and call_argument.value.id.startswith("adj_")
                )
            elif isinstance(call_argument, ast.Attribute):
                valid = call_argument.attr.startswith("adj_") or not any(
                    token in call_argument.attr.lower() for token in ("close", "price")
                )
            elif isinstance(call_argument, ast.Constant):
                valid = True
            elif isinstance(call_argument, ast.Call):
                valid = True
            else:
                valid = False
            if not valid:
                raise AssertionError(
                    f"{node.func.id} received a non-adjusted argument"
                )


def test_abnormality_return_signatures_are_adjusted_only() -> None:
    _validate_return_inputs(ABNORMALITY.read_text(encoding="utf-8"))


def test_return_guard_rejects_unadjusted_call() -> None:
    source = """
def compute_return(adj_close):
    return adj_close

def caller(df):
    return compute_return(df["close"])
"""
    with pytest.raises(AssertionError, match="non-adjusted argument"):
        _validate_return_inputs(source)
