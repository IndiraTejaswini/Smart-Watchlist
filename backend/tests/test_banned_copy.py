"""R12 backend acceptance: one banned-word list, enforced at build time over
the copy templates and at runtime over any model-generated text.

BUILD_PLAN task 8.3: "the banned-word lint passes". Task 8.6: "output
containing any word from the R12 banned list is rejected and the template is
used. Test with a filing about a buyback... assert the Brief never renders
'should', 'bullish' or 'opportunity'." Neither existed before this file —
copy.py had no test at all, and its own word list silently diverged from the
canonical one in app.constants (missing 'target price', 'act now',
"don't miss", 'hurry', and unable to catch any of them since phrases can
never match a single-word tokenizer).
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.analytics.candidates import Candidate, SignalFamily
from app.analytics.digest import copy as copy_module
from app.analytics.digest.copy import (
    DataStatus,
    assert_copy_is_compliant,
    find_banned_words,
    render_candidate_copy,
)
from app.analytics.digest.summariser import validate_summary_candidate
from app.constants import BANNED_COPY_CHARS, BANNED_COPY_TERMS


def _candidate(**overrides) -> Candidate:
    defaults = dict(
        symbol="TESTCO",
        date=date(2026, 4, 6),
        signal_families=frozenset({SignalFamily.PRICE_MPM}),
        primary_signal=SignalFamily.PRICE_MPM,
        sar=2.1,
        turnover_z=2.5,
        delivery_z=1.8,
        material_announcements_count=0,
    )
    defaults.update(overrides)
    return Candidate(**defaults)


# ─── R12 build-time: one list ────────────────────────────────────────────────


def test_copy_module_word_list_is_sourced_from_the_registry() -> None:
    """The list lives in app.constants; copy.py must not re-declare its own."""
    source = Path(inspect.getfile(copy_module)).read_text(encoding="utf-8")
    assert "BANNED_COPY_TERMS" in source
    assert copy_module.BANNED_WORDS == frozenset(
        term for term in BANNED_COPY_TERMS if " " not in term
    )


def test_registry_terms_missing_from_the_old_local_list_are_now_caught() -> None:
    for phrase in ("target price", "act now", "don't miss", "hurry"):
        assert phrase in BANNED_COPY_TERMS
        assert phrase in find_banned_words(f"A note about the {phrase} here.")


def test_exclamation_mark_is_rejected() -> None:
    assert BANNED_COPY_CHARS == ("!",)
    with pytest.raises(ValueError):
        assert_copy_is_compliant("This moved a lot!")


def test_lint_over_the_static_template_source_finds_no_banned_literal() -> None:
    """Build-time lint: grep copy.py's own template strings, not just runtime input."""
    source = Path(inspect.getfile(copy_module)).read_text(encoding="utf-8")
    # Only the literal f-string templates matter; the word-list declarations
    # and this file's own docstring are not user-facing copy.
    template_lines = [
        line
        for line in source.splitlines()
        if ("headline = " in line or "driver = " in line or "statistical_context = " in line)
        and "f\"" in line
    ]
    assert template_lines, "expected at least one template line to check"
    for line in template_lines:
        hits = find_banned_words(line)
        assert not hits, f"banned word {hits} in template line: {line.strip()}"


# ─── render_candidate_copy: never emits a banned word for real inputs ───────


def test_render_candidate_copy_is_clean_for_a_typical_explained_move() -> None:
    candidate = _candidate(is_explained=True, primary_category="FINANCIAL_RESULTS")
    rendered = render_candidate_copy(
        candidate,
        return_pct=4.2,
        as_of_time="15:30",
        status=DataStatus.FINAL,
        turnover_cr=12.5,
        turnover_multiple=3.1,
        delivery_pct=61.0,
        category_label="Financial Results",
        announcement_headline="Board approved quarterly results",
    )
    assert not find_banned_words(rendered.full_text)


def test_render_candidate_copy_rejects_a_buyback_headline_with_banned_language() -> None:
    """Task 8.6's own test, applied to the deterministic template path: a
    buyback filing headline is exactly the kind of real text most likely to
    smuggle recommendation language ('opportunity', 'should', 'attractive')
    into the driver line via interpolation."""
    candidate = _candidate(is_explained=True, primary_category="FUND_RAISE")
    with pytest.raises(ValueError) as exc_info:
        render_candidate_copy(
            candidate,
            return_pct=3.0,
            as_of_time="15:30",
            status=DataStatus.FINAL,
            category_label="Fund Raise",
            announcement_headline=(
                "Board considers this an attractive buyback opportunity that "
                "investors should not miss"
            ),
        )
    banned = str(exc_info.value)
    for word in ("should", "opportunity", "attractive"):
        assert word in banned


# ─── summariser: same list, same rejection path (Task 8.6) ─────────────────


class _BannedLLMClient:
    """Simulates a model that reaches for recommendation language on a
    buyback prompt — the exact failure mode Task 8.6 calls out by name."""

    def summarize(self, prompt: str, timeout: float) -> str:
        del prompt, timeout
        return "This is a bullish buyback opportunity investors should consider."


def test_summariser_rejects_buyback_filing_with_banned_words(tmp_path) -> None:
    from app.ingest.announcement_ingest import Announcement

    announcement = Announcement(
        symbol="TESTCO",
        filed_at=datetime(2026, 4, 6, 10, 0, tzinfo=UTC),
        subject="Board approves share buyback",
        category="CORP_ACTION",
        para_ref=None,
        attachment_url=None,
        raw_json={"body_text": "The company will buy back up to 5% of equity shares."},
        content_hash="deadbeef",
    )
    source = " ".join(
        [announcement.category, announcement.subject, announcement.body_text]
    )
    raw_output = _BannedLLMClient().summarize("prompt", 1.5)
    valid, reason = validate_summary_candidate(raw_output, source)
    assert not valid
    assert reason is not None and reason.startswith("BANNED_WORD:")
    for word in ("bullish", "opportunity", "should"):
        assert word in reason
