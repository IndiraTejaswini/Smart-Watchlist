from datetime import date, datetime, timedelta

import pytest

from app.analytics.constants import BENCHMARK_ANCHOR_SYMBOL
from app.analytics.freshness import (
    FreshnessContext,
    FreshnessState,
    evaluate_freshness_state,
)
from app.analytics.quotes.manager import QuoteSubscriptionManager
from app.timeutil import IST, TradingCalendar


def make_calendar() -> TradingCalendar:
    rows = []
    day = date(2026, 4, 1)
    while day <= date(2026, 8, 17):
        trading = day.weekday() < 5 and day != date(2026, 8, 15)
        rows.append(
            {
                "calendar_date": day,
                "is_trading_day": trading,
                "session_type": "REGULAR" if trading else "CLOSED",
                "regular_open": "09:15" if trading else None,
                "regular_close": "15:30" if trading else None,
            }
        )
        day += timedelta(days=1)
    return TradingCalendar.from_rows(rows)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=IST)


CALENDAR = make_calendar()


@pytest.mark.parametrize(
    "eval_ts,symbol_ts,anchor_ts,symbol_date,is_locked,expected",
    [
        ("2026-08-15 11:00:00", None, None, None, False, FreshnessState.HOLIDAY),
        ("2026-04-06 17:30:00", None, None, None, False, FreshnessState.CLOSED),
        ("2026-04-06 09:05:00", None, None, None, False, FreshnessState.PRE_OPEN),
        (
            "2026-04-08 11:00:00",
            None,
            None,
            date(2026, 4, 6),
            False,
            FreshnessState.STALE_EOD,
        ),
        (
            "2026-04-06 11:00:00",
            "2026-04-06 10:57:00",
            "2026-04-06 10:59:00",
            None,
            False,
            FreshnessState.HALTED_MARKET,
        ),
        (
            "2026-04-06 11:00:00",
            "2026-04-06 10:59:58",
            "2026-04-06 10:59:59",
            None,
            True,
            FreshnessState.HALTED_SYMBOL,
        ),
        (
            "2026-04-06 11:00:00",
            "2026-04-06 10:58:20",
            "2026-04-06 10:59:59",
            None,
            False,
            FreshnessState.STALE_THIN,
        ),
        (
            "2026-04-06 11:00:00",
            "2026-04-06 10:59:50",
            "2026-04-06 10:59:59",
            None,
            False,
            FreshnessState.STALE_FLOW,
        ),
        (
            "2026-04-06 11:00:00",
            "2026-04-06 10:59:58",
            "2026-04-06 10:59:59",
            None,
            False,
            FreshnessState.LIVE,
        ),
    ],
)
def test_freshness_waterfall(
    eval_ts: str,
    symbol_ts: str | None,
    anchor_ts: str | None,
    symbol_date: date | None,
    is_locked: bool,
    expected: FreshnessState,
) -> None:
    state, reason = evaluate_freshness_state(
        FreshnessContext(
            symbol="RELIANCE",
            symbol_tick_ts=at(symbol_ts) if symbol_ts else None,
            symbol_date=symbol_date,
            is_circuit_locked=is_locked,
            anchor_tick_ts=at(anchor_ts) if anchor_ts else None,
            eval_ts=at(eval_ts),
        ),
        CALENDAR,
    )
    assert state is expected
    assert reason


def test_live_anchor_classifies_illiquid_symbols_as_thin() -> None:
    states = [
        evaluate_freshness_state(
            FreshnessContext(
                symbol=f"ILLIQUID_{index:02d}",
                symbol_tick_ts=at("2026-04-06 11:28:20"),
                symbol_date=None,
                anchor_tick_ts=at("2026-04-06 11:29:58"),
                eval_ts=at("2026-04-06 11:30:00"),
            ),
            CALENDAR,
        )[0]
        for index in range(1, 21)
    ]
    assert states == [FreshnessState.STALE_THIN] * 20


def test_silent_anchor_classifies_symbols_as_market_halted() -> None:
    state, _ = evaluate_freshness_state(
        FreshnessContext(
            symbol="ILLIQUID_01",
            symbol_tick_ts=at("2026-04-06 11:28:20"),
            symbol_date=None,
            anchor_tick_ts=at("2026-04-06 11:29:40"),
            eval_ts=at("2026-04-06 11:30:00"),
        ),
        CALENDAR,
    )
    assert state is FreshnessState.HALTED_MARKET


class FakeSource:
    def __init__(self) -> None:
        self.subscribed: set[str] = set()

    async def subscribe(self, symbols: set[str]) -> None:
        self.subscribed.update(symbols)

    async def unsubscribe(self, symbols: set[str]) -> None:
        self.subscribed.difference_update(symbols)


@pytest.mark.asyncio
async def test_anchor_cannot_be_unsubscribed() -> None:
    source = FakeSource()
    manager = QuoteSubscriptionManager(source, ["RELIANCE", "TCS"])
    await manager.start()
    await manager.unsubscribe(["RELIANCE", "TCS", BENCHMARK_ANCHOR_SYMBOL])
    assert BENCHMARK_ANCHOR_SYMBOL in source.subscribed
