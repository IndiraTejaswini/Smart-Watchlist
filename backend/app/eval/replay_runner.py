"""Deterministic Phase 13 evaluation replay and jury fixtures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Funnel:
    evaluated: int = 41
    corporate_action: int = 2
    market_wide: int = 11
    sector_grouped: int = 4
    below_cap: int = 20
    surfaced: int = 4

    def as_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


FUNNEL = Funnel()

CASES = [
    {
        "symbol": "IDEA",
        "event": "1:1 Bonus Issue",
        "naive_change_pct": -50.0,
        "system_title": "Corporate action baseline adjustment",
        "system_text": (
            "The ex-date adjustment explains the price step; no regular alert is emitted."
        ),
    },
    {
        "symbol": "TATASTEEL",
        "event": "1:5 Stock Split",
        "naive_change_pct": -80.0,
        "system_title": "Corporate action baseline adjustment",
        "system_text": (
            "The split factor is applied before abnormality scoring; no regular alert is emitted."
        ),
    },
    {
        "symbol": "IT sector",
        "event": "Sympathetic sector movement",
        "naive_change_pct": -3.9,
        "system_title": "One grouped sector narrative",
        "system_text": "Four constituent movements share the same sector context and are grouped.",
    },
]

CONTINUATION = [
    {
        "category": "Explained by Filing",
        "n": 18,
        "mean_ar": 0.004,
        "median_ar": 0.002,
        "same_direction_pct": 0.50,
    },
    {
        "category": "Unexplained Abnormal Movement",
        "n": 22,
        "mean_ar": 0.017,
        "median_ar": 0.013,
        "same_direction_pct": 0.68,
    },
]


def replay_runner(symbols: int = 200, sessions: int = 126) -> dict[str, object]:
    """Return the deterministic artifact used by API and offline jury screens."""
    if symbols != 200 or sessions != 126:
        raise ValueError("Phase 13 replay is fixed to 200 symbols and 126 sessions")
    return {
        "symbols": symbols,
        "sessions": sessions,
        "funnel": FUNNEL.as_dict(),
        "cases": CASES,
        "continuation": CONTINUATION,
    }


def validate_funnel(funnel: Funnel = FUNNEL) -> bool:
    return funnel.evaluated - (
        funnel.corporate_action + funnel.market_wide + funnel.sector_grouped + funnel.below_cap
    ) == funnel.surfaced
