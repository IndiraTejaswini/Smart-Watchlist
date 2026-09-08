"""Deterministic institutional digest copy generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.analytics.candidates import Candidate
from app.constants import BANNED_COPY_CHARS, BANNED_COPY_TERMS


class DataStatus(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


@dataclass(frozen=True)
class RenderedCopy:
    headline: str
    driver: str
    statistical_context: str
    status_stamp: str
    full_text: str
    as_of_time: str
    status: DataStatus


# R12: ONE list, imported from the registry — app.constants.BANNED_COPY_TERMS.
# Single words are checked against the tokenised text; multi-word entries
# ("target price", "act now", "don't miss") are checked as normalised
# substrings, since a word-boundary token split can never match a phrase.
_SINGLE_WORD_TERMS = frozenset(term for term in BANNED_COPY_TERMS if " " not in term)
_PHRASE_TERMS = tuple(term for term in BANNED_COPY_TERMS if " " in term)
BANNED_WORDS = _SINGLE_WORD_TERMS  # kept for callers that import this name directly


def find_banned_words(text: str) -> frozenset[str]:
    normalized = " ".join(text.casefold().split())
    hits = set(re.findall(r"[A-Za-z']+", text.casefold())) & _SINGLE_WORD_TERMS
    hits |= {phrase for phrase in _PHRASE_TERMS if phrase in normalized}
    return frozenset(hits)


def assert_copy_is_compliant(text: str) -> None:
    banned = find_banned_words(text)
    if banned:
        raise ValueError(f"banned words in digest copy: {', '.join(sorted(banned))}")
    for char in BANNED_COPY_CHARS:
        if char in text:
            raise ValueError(f"banned character in digest copy: {char!r}")


def lint_rendered_text(text: str) -> frozenset[str]:
    """Return banned lexicon hits for callers that need a static lint pass."""
    return find_banned_words(text)


def render_candidate_copy(
    candidate: Candidate,
    *,
    return_pct: float,
    as_of_time: str,
    status: DataStatus,
    turnover_cr: float | None = None,
    turnover_multiple: float | None = None,
    delivery_pct: float | None = None,
    extreme_type: str | None = None,
    price: float | None = None,
    distance_pct: float | None = None,
    category_label: str | None = None,
    announcement_headline: str | None = None,
    mechanism_label: str | None = None,
) -> RenderedCopy:
    direction = "advanced" if return_pct >= 0.0 else "declined"
    headline = (
        f"{candidate.symbol} {direction} {abs(return_pct):.2f}% "
        f"(SAR: {candidate.sar:+.2f}σ)."
    )
    if mechanism_label is not None:
        driver = (
            f"Co-moving with {mechanism_label} "
            f"({return_pct:+.2f}%), reflecting systematic exposure."
        )
    elif candidate.is_explained and category_label and announcement_headline:
        driver = f"Accompanied by {category_label} announcement: '{announcement_headline}'."
    else:
        driver = "Unexplained: No material exchange filings recorded in the active session window."

    if extreme_type is not None and price is not None and distance_pct is not None:
        statistical_context = (
            f"Trading at {extreme_type} (₹{price:.2f}, "
            f"{distance_pct:+.2f}% from 52-week level)."
        )
    else:
        multiple = 0.0 if turnover_multiple is None else turnover_multiple
        turnover_z = 0.0 if candidate.turnover_z is None else candidate.turnover_z
        if candidate.delivery_z is None:
            statistical_context = (
                f"Turnover was {multiple:.1f}x 20-session ADV (z = {turnover_z:+.2f}); "
                "delivery data pending post-close settlement."
            )
        else:
            delivery = 0.0 if delivery_pct is None else delivery_pct
            statistical_context = (
                f"Turnover was {multiple:.1f}x 20-session ADV (z = {turnover_z:+.2f}); "
                f"delivery at {delivery:.1f}% (z = {candidate.delivery_z:+.2f})."
            )
    candidate_status = DataStatus(getattr(candidate, "status", status.value))
    if getattr(candidate, "was_restated", False):
        stamp = (
            f"[As of {as_of_time} IST | FINAL — Revised after final exchange data "
            f"(rev {getattr(candidate, 'revision', 1)})]"
        )
    else:
        stamp = f"[As of {as_of_time} IST | {candidate_status.value}]"
    full_text = " ".join((headline, driver, statistical_context, stamp))
    assert_copy_is_compliant(full_text)
    return RenderedCopy(
        headline=headline,
        driver=driver,
        statistical_context=statistical_context,
        status_stamp=stamp,
        full_text=full_text,
        as_of_time=as_of_time,
        status=candidate_status,
    )
