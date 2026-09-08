"""Session-aware candidate refractory filtering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.analytics.candidates import Candidate
from app.constants import (
    REFRACTORY_ESCALATION,
    REFRACTORY_MEMORY_TTL_DAYS,
    REFRACTORY_WINDOW_SESSIONS,
)
from app.timeutil import TradingCalendar, sessions_between


@dataclass(frozen=True)
class CandidateEvent:
    symbol: str
    occurred_at: datetime | date
    magnitude: float

    @property
    def event_date(self) -> date:
        return (
            self.occurred_at.date()
            if isinstance(self.occurred_at, datetime)
            else self.occurred_at
        )


@dataclass(frozen=True)
class RefractoryState:
    symbol: str
    last_emitted_at: datetime | date
    direction: int
    anchor_magnitude: float
    window_sessions: int = REFRACTORY_WINDOW_SESSIONS


class RefractoryStore:
    """Small store abstraction supporting memory and Redis-like clients."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._memory: dict[str, tuple[RefractoryState, datetime]] = {}

    def get(self, symbol: str) -> RefractoryState | None:
        key = f"refractory:{symbol}"
        if self._redis is not None:
            return self._redis.get(key)
        item = self._memory.get(key)
        if item is None or item[1] <= datetime.now():
            self._memory.pop(key, None)
            return None
        return item[0]

    def set(self, state: RefractoryState) -> None:
        key = f"refractory:{state.symbol}"
        ttl = timedelta(days=REFRACTORY_MEMORY_TTL_DAYS)
        if self._redis is not None:
            self._redis.setex(key, int(ttl.total_seconds()), state)
        else:
            self._memory[key] = (state, datetime.now() + ttl)

    def delete(self, symbol: str) -> None:
        key = f"refractory:{symbol}"
        if self._redis is not None:
            self._redis.delete(key)
        else:
            self._memory.pop(key, None)


def evaluate_refractory_filter(
    current_event: CandidateEvent,
    state: RefractoryState | None,
    calendar: TradingCalendar,
) -> tuple[bool, RefractoryState]:
    """Return whether an event emits and the resulting refractory state."""
    current_date = current_event.event_date
    direction = 1 if current_event.magnitude > 0 else -1
    magnitude = abs(current_event.magnitude)
    expired = (
        state is None
        or sessions_between(
            state.last_emitted_at
            if isinstance(state.last_emitted_at, date)
            else state.last_emitted_at.date(),
            current_date,
            calendar,
        )
        > state.window_sessions
    )
    if expired or state is None or direction != state.direction:
        return True, RefractoryState(
            current_event.symbol,
            current_event.occurred_at,
            direction,
            magnitude,
            state.window_sessions if state else REFRACTORY_WINDOW_SESSIONS,
        )
    if magnitude >= (1.0 + REFRACTORY_ESCALATION) * state.anchor_magnitude:
        return True, RefractoryState(
            state.symbol,
            current_event.occurred_at,
            state.direction,
            magnitude,
            state.window_sessions,
        )
    return False, state


def filter_candidates(
    candidates: list[Candidate],
    events: dict[str, CandidateEvent],
    store: RefractoryStore,
    calendar: TradingCalendar,
) -> list[Candidate]:
    """Filter candidates and annotate suppressed rows for downstream auditing."""
    result: list[Candidate] = []
    for candidate in candidates:
        event = events[candidate.symbol]
        emitted, state = evaluate_refractory_filter(event, store.get(candidate.symbol), calendar)
        store.set(state)
        if emitted:
            result.append(candidate)
        else:
            metadata = dict(candidate.metadata)
            metadata["is_refractory_suppressed"] = True
    return result
