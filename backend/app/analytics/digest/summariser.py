"""Bounded, fail-safe filing summarisation."""

from __future__ import annotations

import logging
import re
from typing import Protocol
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.analytics.digest.copy import lint_rendered_text
from app.ingest.announcement_ingest import Announcement

SUMMARY_MAX_CHARS: int = 160
LLM_TIMEOUT_SECONDS: float = 1.5
log = logging.getLogger(__name__)


class LLMClient(Protocol):
    def summarize(self, prompt: str, timeout: float) -> str: ...


def extract_isolated_input(announcement: Announcement) -> dict[str, str]:
    raw = announcement.raw_json
    return {
        "subject": str(getattr(announcement, "headline", announcement.subject)),
        "category": str(announcement.category),
        "body": str(
            getattr(
                announcement,
                "body_text",
                raw.get("body_text", raw.get("body", "")),
            )
        ),
    }


def validate_summary_candidate(summary: str, source_text: str) -> tuple[bool, str | None]:
    if len(summary) > SUMMARY_MAX_CHARS:
        return False, "LENGTH_EXCEEDED"
    if "\n" in summary or not summary.strip():
        return False, "NOT_SINGLE_SENTENCE"
    if summary.count(".") > 1:
        return False, "NOT_SINGLE_SENTENCE"
    summary_digits = set(re.findall(r"\d", summary))
    source_digits = set(re.findall(r"\d", source_text))
    if not summary_digits.issubset(source_digits):
        return False, "DIGIT_HALLUCINATION"
    detected = lint_rendered_text(summary)
    if detected:
        return False, f"BANNED_WORD:{','.join(sorted(detected))}"
    return True, None


def _fallback(category: str, subject: str) -> str:
    return f"Accompanied by {category} announcement: '{subject}'."


def _persist(
    db: Session,
    *,
    brief_id: str,
    symbol: str,
    announcement: Announcement,
    model_version: str,
    prompt: str,
    raw_output: str | None,
    valid: bool,
    reason: str | None,
    sentence: str | None,
) -> None:
    db.execute(
        sa.text(
            "INSERT INTO filing_summaries "
            "(id, brief_id, symbol, announcement_id, model_version, prompt_text, "
            "raw_output, is_valid, validation_failure_reason, sanitized_sentence) "
            "VALUES (:id, :brief_id, :symbol, :announcement_id, :model_version, "
            ":prompt_text, :raw_output, :is_valid, :reason, :sentence)"
        ),
        {
            "id": str(uuid4()),
            "brief_id": brief_id,
            "symbol": symbol,
            "announcement_id": announcement.content_hash,
            "model_version": model_version,
            "prompt_text": prompt,
            "raw_output": raw_output,
            "is_valid": valid,
            "reason": reason,
            "sentence": sentence,
        },
    )
    db.commit()


def generate_filing_summary(
    db: Session,
    brief_id: str,
    symbol: str,
    announcement: Announcement,
    client: LLMClient | None = None,
) -> tuple[str, bool]:
    isolated = extract_isolated_input(announcement)
    prompt = (
        "Summarize this corporate filing in exactly one objective, factual sentence "
        "under 150 characters. Mention only verifiable actions taken by the firm. "
        "Do not give financial advice or use subjective adjectives.\n\n"
        f"Category: {isolated['category']}\nSubject: {isolated['subject']}\n"
        f"Text: {isolated['body']}"
    )
    fallback = _fallback(isolated["category"], isolated["subject"])
    if client is None:
        _persist(
            db, brief_id=brief_id, symbol=symbol, announcement=announcement,
            model_version="local-template", prompt=prompt, raw_output=None,
            valid=False, reason="ENDPOINT_FAILURE", sentence=None,
        )
        return fallback, False
    try:
        raw_output = client.summarize(prompt, timeout=LLM_TIMEOUT_SECONDS).strip()
    except Exception as exc:
        log.warning("filing summariser endpoint failed: %s", exc)
        _persist(
            db, brief_id=brief_id, symbol=symbol, announcement=announcement,
            model_version="local-stub", prompt=prompt, raw_output=None,
            valid=False, reason="ENDPOINT_FAILURE", sentence=None,
        )
        return fallback, False
    source = " ".join(isolated.values())
    valid, reason = validate_summary_candidate(raw_output, source)
    _persist(
        db, brief_id=brief_id, symbol=symbol, announcement=announcement,
        model_version="local-stub", prompt=prompt, raw_output=raw_output,
        valid=valid, reason=reason, sentence=raw_output if valid else None,
    )
    if valid:
        return f"{raw_output} (summarised from exchange filing)", True
    return fallback, False
