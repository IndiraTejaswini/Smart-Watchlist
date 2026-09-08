"""Evaluation endpoints — docs/BUILD_SPEC.md §16, §18.

Only `/api/eval/unparsed-actions` exists so far. It is here rather than in
Phase 13 because BUILD_PLAN task 1.4 makes it part of that task's acceptance:
"every DISCREPANCY is listed at /api/eval/unparsed-actions". The funnel,
suppression cases and continuation test arrive with the rest of §18.

Why this endpoint is worth having at all, from §5.3.0: "Regex will not extract
everything, and the design does not need it to. What it needs is to *know when
it failed*. Coverage is reported as a metric, not assumed." This is where that
report is served, and publishing it is a stronger position than claiming the
parser is always right.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query

from app.constants import EVAL_UNPARSED_DEFAULT_LIMIT, EVAL_UNPARSED_MAX_LIMIT
from app.db import get_engine
from app.eval.replay_runner import replay_runner
from app.ingest import ca_verify

router = APIRouter(prefix="/api/eval", tags=["eval"])

# §16: cursor pagination elsewhere; this list is bounded by how much a parser
# failed to read, which is small by construction and shrinking.
DEFAULT_LIMIT = EVAL_UNPARSED_DEFAULT_LIMIT
MAX_LIMIT = EVAL_UNPARSED_MAX_LIMIT


def connection() -> Iterator[sa.Connection]:
    with get_engine().connect() as conn:
        yield conn


# Annotated rather than a `Depends` default: the default-argument form builds
# the dependency once at import time, which is the pattern B008 exists to catch.
Connection = Annotated[sa.Connection, Depends(connection)]


@router.get("/funnel")
def funnel() -> dict[str, int]:
    return replay_runner()["funnel"]  # type: ignore[return-value]


@router.get("/cases")
def cases() -> list[dict[str, object]]:
    return replay_runner()["cases"]  # type: ignore[return-value]


@router.get("/suppression-cases")
def suppression_cases() -> list[dict[str, object]]:
    """Compatibility alias for the architecture contract name."""
    return cases()


@router.get("/continuation")
def continuation() -> list[dict[str, object]]:
    return replay_runner()["continuation"]  # type: ignore[return-value]


@router.get("/unparsed-actions")
def unparsed_actions(
    conn: Connection,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Every corporate action the system does not trust, and why.

    Two populations, deliberately served together because they are the two ways
    the same question is answered wrongly:

      `UNPARSED`    the purpose string could not be read, so no factor exists.
      `DISCREPANCY` a factor was parsed and the market contradicted it.

    Both suppress their ex-date window under §5.3's fail-safe rule, so this is
    also the list of what the product deliberately declined to score.
    """
    rows = ca_verify.discrepancies(conn, limit=limit)
    totals: dict[str, int] = {
        str(verification): int(count)
        for verification, count in conn.execute(
            sa.text(
                "SELECT verification, COUNT(*) FROM corporate_actions GROUP BY verification"
            )
        ).all()
    }
    total = sum(totals.values())
    verified = totals.get(ca_verify.VERIFIED, 0)
    settled = verified + totals.get(ca_verify.DISCREPANCY, 0)
    return {
        "summary": {
            "corporate_actions": total,
            "by_verification": totals,
            # The §1.4 acceptance quantity: of the actions the market could
            # settle, the share it confirmed.
            "verified_ratio": round(verified / settled, 4) if settled else None,
            "tolerance": ca_verify.float_tolerance(),
        },
        "count": len(rows),
        "items": rows,
    }
