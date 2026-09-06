"""Corporate-action interception for batch and live scoring."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.analytics.abnormality import AbnormalityScores
from app.analytics.candidates import Candidate, generate_candidate
from app.analytics.corporate_action_notice import CorporateActionNotice
from app.analytics.fact_bundle import FactBundle
from app.analytics.mpm import MPMResult

IST = ZoneInfo("Asia/Kolkata")
EIGHT_DECIMAL_PLACES = Decimal("0.00000001")
OPENING_PAUSE_START = time(9, 15)
OPENING_PAUSE_END = time(9, 30)
@dataclass(frozen=True)
class CorporateAction:
    """The minimum verified action data required by the suppression path."""

    symbol: str
    ex_date: date
    cum_date: date
    action_type: str
    as_traded_cum_close: Decimal
    adjusted_prev_close: Decimal
    adjustment_factor: Decimal
    ratio_or_amount: str
    source_url: str


class CorporateActionRegistry:
    """Immutable lookup registry for verified actions in a scoring session."""

    def __init__(self, actions: Iterable[CorporateAction] = ()) -> None:
        self._actions = {(action.symbol, action.ex_date): action for action in actions}

    def get(self, symbol: str, ex_date: date) -> CorporateAction | None:
        return self._actions.get((symbol, ex_date))

    def has(self, symbol: str, ex_date: date) -> bool:
        return (symbol, ex_date) in self._actions


_registry = CorporateActionRegistry()


def set_corporate_action_registry(registry: CorporateActionRegistry) -> None:
    """Set the process registry used by convenience live-tick functions."""
    global _registry
    _registry = registry


def _to_ist(tick_time: datetime) -> datetime:
    if tick_time.tzinfo is None:
        raise ValueError("tick_time must be timezone-aware")
    return tick_time.astimezone(IST)


def is_ex_date_in_opening_pause(
    symbol: str,
    tick_time: datetime,
    registry: CorporateActionRegistry | None = None,
) -> bool:
    """Return whether a tick falls in the 09:15–09:30 IST ex-date pause."""
    local_time = _to_ist(tick_time)
    action_registry = registry or _registry
    return (
        action_registry.has(symbol, local_time.date())
        and OPENING_PAUSE_START <= local_time.time() < OPENING_PAUSE_END
    )


def emit_corporate_action_notice(
    action: CorporateAction,
    *,
    created_at: datetime | None = None,
) -> CorporateActionNotice:
    """Build the one canonical notice for an intercepted action."""
    action_type = action.action_type.upper()
    headline = (
        f"{action.symbol}: {action_type.replace('_', ' ').title()} "
        f"effective {action.ex_date}"
    )
    detail = (
        f"{action_type} effective on {action.ex_date}; "
        f"cum-date close {action.as_traded_cum_close} adjusted to "
        f"{action.adjusted_prev_close} (factor {action.adjustment_factor})."
    )
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    return CorporateActionNotice(
        symbol=action.symbol,
        ex_date=action.ex_date,
        cum_date=action.cum_date,
        action_type=action_type,
        as_traded_cum_close=action.as_traded_cum_close,
        adjusted_prev_close=action.adjusted_prev_close,
        adjustment_factor=action.adjustment_factor.quantize(EIGHT_DECIMAL_PLACES),
        ratio_or_amount=action.ratio_or_amount,
        headline=headline,
        detail_text=detail,
        source_url=action.source_url,
        created_at=timestamp,
    )


def score_symbol(
    bundle: FactBundle,
    mpm: MPMResult,
    abnormality: AbnormalityScores,
    *,
    registry: CorporateActionRegistry | None = None,
    notice_created_at: datetime | None = None,
) -> tuple[Candidate | None, CorporateActionNotice | None]:
    """Score one symbol, suppressing all standard families on its ex-date."""
    action_registry = registry or _registry
    action = action_registry.get(bundle.symbol, bundle.date)
    if action is not None:
        return None, emit_corporate_action_notice(action, created_at=notice_created_at)
    return generate_candidate(bundle, mpm, abnormality), None


def score_candidates(
    fixtures: Iterable[tuple[FactBundle, MPMResult, AbnormalityScores]],
    *,
    registry: CorporateActionRegistry | None = None,
    notice_created_at: datetime | None = None,
) -> tuple[list[Candidate], list[CorporateActionNotice]]:
    """Score a batch and emit at most one notice per symbol and ex-date."""
    candidates: list[Candidate] = []
    notices: list[CorporateActionNotice] = []
    seen_actions: set[tuple[str, date]] = set()
    for bundle, mpm, abnormality in fixtures:
        candidate, notice = score_symbol(
            bundle,
            mpm,
            abnormality,
            registry=registry,
            notice_created_at=notice_created_at,
        )
        if candidate is not None:
            candidates.append(candidate)
        if notice is not None and (notice.symbol, notice.ex_date) not in seen_actions:
            notices.append(notice)
            seen_actions.add((notice.symbol, notice.ex_date))
    return candidates, notices


def process_live_tick(
    *,
    symbol: str,
    tick_time: datetime,
    score: Callable[[], Candidate | None],
    buffer_tick: Callable[[], None],
    registry: CorporateActionRegistry | None = None,
    dispatch_notice: Callable[[CorporateActionNotice], None] | None = None,
) -> Candidate | None:
    """Buffer a tick and suppress scoring for an ex-date action."""
    buffer_tick()
    if is_ex_date_in_opening_pause(symbol, tick_time, registry):
        return None
    local_date = _to_ist(tick_time).date()
    action = (registry or _registry).get(symbol, local_date)
    if action is not None:
        if dispatch_notice is not None:
            dispatch_notice(emit_corporate_action_notice(action))
        return None
    return score()
