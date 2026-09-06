"""Announcement category resolution — ARCHITECTURE.md §9.2.

Only the category resolver lives here so far. The full announcement ingest —
polling `ANNOUNCEMENT_POLL_SECONDS`, the content-hash dedup, the historical
backfill — is BUILD_PLAN task 2.8, a `P0` EOD-ingest task with its own
acceptance criteria, and does not exist yet.

This module exists early because BUILD_PLAN task 1.6's coverage report needs
somewhere to send an announcement's `desc` and `subject` and get back how it
would be categorised. Task 2.8 imports `resolve_category` directly rather than
duplicating it; the file `§4.1`'s repository layout already names
(`ingest/announcements.py`) is where that ingest logic will land next to it.

─── Resolution order — structured field first, regex second ────────────────

§9.2, verbatim:

    1. NSE `desc` field → CATEGORY_FROM_DESC lookup      (exact, normalised match)
    2. subject line     → CATEGORY_PATTERNS regex        (fallback)
    3. neither matches  → OTHER

The NSE payload's `desc` field is a controlled vocabulary the exchange
maintains (*Financial Results*, *Change in Directorate*, *Credit Rating* ...),
and it is a far better signal than anything recoverable from free text. Regex
is the fallback, not the primary path.

─── Why `CATEGORY_FROM_DESC` is empty here ──────────────────────────────────

§9.2 is explicit about how it gets built: run the announcement backfill (task
2.8), then `SELECT raw_json->>'desc', count(*) GROUP BY 1 ORDER BY 2 DESC` and
hand-map the top ~30 values. That is empirical work over real filings — R3
forbids guessing market-data semantics, and a hand-typed guess at what NSE's
`desc` values are and mean would be exactly that guess. So the table starts
empty and every announcement falls through to the regex fallback until task 2.8
populates it from real data. The coverage report says so honestly rather than
padding the "resolved by desc" bucket with invented entries.

`CATEGORY_PATTERNS`, by contrast, is copied verbatim from §9.2 — it is already
the empirical output of that section's own worked example (the review's
complaint about `"loa"` matching *Download* and `"ncd"` matching
*Unconditional*), so reproducing it is not a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ─── Step 1: the exchange's own controlled vocabulary ───────────────────────
# {normalised desc: category}. Populated empirically by BUILD_PLAN task 2.8 —
# see the module docstring for why it must not be guessed at here.
CATEGORY_FROM_DESC: dict[str, str] = {}

# ─── Step 2: the regex fallback — §9.2, verbatim ────────────────────────────
# Anchored patterns, not substring matching: revision 1's case-insensitive
# substring match let "loa" match "Download" and "ncd" match "Unconditional".
# Evaluated in order; first match wins. The trailing catch-all is what makes
# every subject resolve to *some* category — OTHER still counts as an
# explanation, just with the smaller §13 multiplier.
CATEGORY_PATTERNS: tuple[tuple[str, str | None, str], ...] = (
    ("RESULTS", "A", r"\b(financial|unaudited|audited|quarterly)\s+results?\b"),
    ("BOARD_MEETING", "A", r"\b(board\s+meeting|outcome\s+of\s+board\s+meeting)\b"),
    (
        "CORP_ACTION",
        "A",
        r"\b(dividend|bonus\s+issue|stock\s+split|sub-?division|buy-?back)\b",
    ),
    (
        "MNA",
        "A",
        r"\b(acquisition|amalgamation|merger|scheme\s+of\s+arrangement|divestment)\b",
    ),
    (
        "FUND_RAISE",
        "A",
        r"\b(qip|preferential\s+(issue|allotment)|rights\s+issue|fund\s+rais\w*|"
        r"ncd|debenture)\b",
    ),
    (
        "RATING",
        "A",
        r"\b(credit\s+rating|rating\s+action|icra|crisil|care\s+ratings|"
        r"india\s+ratings)\b",
    ),
    (
        "KMP_CHANGE",
        "A",
        r"\b(resignation|cessation|appointment\s+of|managing\s+director|"
        r"chief\s+executive|cfo)\b",
    ),
    (
        "LITIGATION",
        "A",
        r"\b(litigation|penalt\w+|show\s+cause|tribunal|nclt|adjudication)\b",
    ),
    (
        "ORDER_WIN",
        "B",
        r"\b(order\s+(win|received|bagged)|letter\s+of\s+award|\bloa\b|"
        r"new\s+contract|bagged)\b",
    ),
    ("OTHER", None, r".*"),
)

OTHER = "OTHER"

# Compiled once, case-insensitive: the real subjects are Title Case
# ("Award of Order") while the patterns are written lower-case.
_COMPILED_PATTERNS = tuple(
    (category, schedule_iii, re.compile(pattern, re.IGNORECASE))
    for category, schedule_iii, pattern in CATEGORY_PATTERNS
)

# Source tags the coverage report (task 1.6) buckets by.
FROM_DESC = "DESC"
FROM_REGEX = "REGEX"
FROM_OTHER = "OTHER"


def _normalise(text: str) -> str:
    return " ".join((text or "").strip().upper().split())


@dataclass(frozen=True)
class Resolution:
    """How one announcement was categorised, and which of §9.2's three steps
    answered — the field the coverage report groups on."""

    category: str
    schedule_iii: str | None
    source: str


def resolve_category(*, desc: str | None, subject: str) -> Resolution:
    """§9.2's three-step resolution, exactly. Pure: no I/O, no clock.

    A `desc` hit never falls through to the regex, even for a `desc` value that
    would itself land on OTHER once mapped — the exchange's own classification
    is authoritative for anything it covers.
    """
    if desc:
        looked_up = CATEGORY_FROM_DESC.get(_normalise(desc))
        if looked_up is not None:
            return Resolution(looked_up, None, FROM_DESC)

    text = subject or ""
    for category, schedule_iii, pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            source = FROM_OTHER if category == OTHER else FROM_REGEX
            return Resolution(category, schedule_iii, source)

    # Unreachable: the trailing `.*` in CATEGORY_PATTERNS always matches, even
    # an empty subject. Kept as a refusal rather than removed, per R5 — a
    # future edit that narrows the catch-all must not silently start raising
    # from inside a loader instead of failing here where the cause is obvious.
    raise AssertionError(  # pragma: no cover - the catch-all always matches
        "no CATEGORY_PATTERNS entry matched; the trailing catch-all is missing "
        "or was narrowed"
    )


def parse_announcements(payload):
    """Parse raw NSE announcements; implementation is kept beside the resolver."""
    from app.ingest.announcement_ingest import parse_announcements as parse

    return parse(payload)


def ingest_announcements(announcements, *, engine=None):
    """Persist parsed announcements with content-hash deduplication."""
    from app.ingest.announcement_ingest import ingest_announcements as ingest

    return ingest(announcements, engine=engine)
