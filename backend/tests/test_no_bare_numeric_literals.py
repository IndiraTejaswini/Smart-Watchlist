"""R1 lint: no bare numeric literals in the numerical core — BUILD_PLAN Part A3.

"You may NOT write a bare number into business logic. Not `20`, not `0.05`,
not `300`." This walks the AST of each scoped module and fails on any
int/float constant that is not explicitly exempted (array indices 0/1, a
handful of calendar/unit-conversion facts, and HTTP status codes). A real
threshold, weight, window length, or timeout must be imported from
``app.constants`` instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# The modules where a silently-invented number does the most damage — the
# signal engine and its direct inputs. R11 already requires these be
# test-first; this lint keeps them literal-free afterwards too.
SCOPED_MODULES = (
    "app/canonical.py",
    "app/analytics/mpm.py",
    "app/analytics/market_model.py",
    "app/analytics/abnormality.py",
    "app/analytics/candidates.py",
    "app/analytics/attribution.py",
    "app/analytics/ranker.py",
    "app/analytics/turnover.py",
    "app/analytics/delivery.py",
    "app/analytics/extremes.py",
    "app/analytics/liquidity.py",
    "app/analytics/refractory.py",
    "app/analytics/freshness.py",
)

# Array indices (0, 1, -1), a small set of unit-conversion/calendar facts that
# are not tunable thresholds (2 = winsorisation pair, 4/5/6 = Mon-Sat weekday
# indices, 100 = percentage points, 1000 = ms<->s), and standard HTTP/WS status
# codes per R1's own exception clause.
EXEMPT_VALUES = {0, 1, -1, 2, 4, 5, 6, 100, 1000}
HTTP_STATUS_CODES = {200, 201, 204, 400, 401, 403, 404, 405, 408, 409, 422, 429,
                     500, 502, 503, 504, 1000, 1001, 1008, 1009, 1011}
EXEMPT_VALUES |= HTTP_STATUS_CODES


def _bare_literals(path: Path) -> list[tuple[int, object]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            if node.value not in EXEMPT_VALUES:
                hits.append((node.lineno, node.value))
    return hits


@pytest.mark.parametrize("relative_path", SCOPED_MODULES)
def test_no_bare_numeric_literals_in_business_logic(relative_path: str) -> None:
    path = BACKEND_ROOT / relative_path
    hits = _bare_literals(path)
    assert not hits, (
        f"{relative_path} has bare numeric literal(s) outside app.constants: "
        f"{hits} — import the threshold from app.constants instead (BUILD_PLAN R1)"
    )
