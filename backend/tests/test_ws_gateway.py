from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.analytics.streaming.gateway import WebSocketGateway
from app.analytics.streaming.session import ClientSession
from app.schemas.quote import CircuitState, FreshnessState, QuoteDeltaPayload


def quote(symbol: str, price: str = "100") -> QuoteDeltaPayload:
    return QuoteDeltaPayload(
        symbol=symbol,
        ltp=Decimal(price),
        change=Decimal("1"),
        change_pct=1.0,
        open=Decimal("99"),
        high=Decimal(price),
        low=Decimal("99"),
        close=Decimal("99"),
        volume=10,
        turnover=Decimal("1000"),
        upper_band=None,
        lower_band=None,
        circuit_state=CircuitState.NORMAL,
        freshness_state=FreshnessState.LIVE,
        freshness_age_ms=0,
        as_of_ts=datetime.now(UTC),
        quality_flag="OK",
    )


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.closed: tuple[int, str] | None = None

    async def send_text(self, value: str) -> None:
        self.messages.append(value)

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


def test_session_conflates_by_symbol() -> None:
    session = ClientSession("one", FakeWebSocket())
    session.subscribed_symbols.add("RELIANCE")
    session.update_tick(quote("RELIANCE", "100"))
    session.update_tick(quote("RELIANCE", "101"))
    batch = session.flush_conflated_batch(0.0)
    assert batch is not None
    assert len(batch) == 1
    assert batch[0].ltp == Decimal("101")


@pytest.mark.asyncio
async def test_gateway_broadcasts_only_to_subscribers() -> None:
    gateway = WebSocketGateway()
    first_socket = FakeWebSocket()
    second_socket = FakeWebSocket()
    first = await gateway.register(first_socket, "first")
    second = await gateway.register(second_socket, "second")
    await gateway.subscribe(first, {"RELIANCE"})
    await gateway.subscribe(second, {"TCS"})
    await gateway.broadcast_tick(quote("RELIANCE"))
    now = 0.0
    batch = first.flush_conflated_batch(now)
    assert batch is not None and batch[0].symbol == "RELIANCE"
    assert second.flush_conflated_batch(now) is None
    await gateway.stop()


@pytest.mark.asyncio
async def test_full_queue_evicts_after_stall_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.analytics.streaming.session.WS_SLOW_CLIENT_TIMEOUT_SECONDS", 2.0
    )
    socket = FakeWebSocket()
    session = ClientSession("slow", socket, max_queue_size=1)
    assert session.enqueue_outbound([quote("RELIANCE")], 0.0)
    assert session.enqueue_outbound([quote("RELIANCE", "101")], 1.0)
    assert not session.enqueue_outbound([quote("RELIANCE", "102")], 3.0)

    gateway = WebSocketGateway()
    gateway._sessions[session.session_id] = session
    await gateway.subscribe(session, {"RELIANCE"})
    await gateway.disconnect_slow_client(session)
    assert socket.closed is not None
    assert socket.closed[0] == 1008
    assert session.session_id not in gateway.sessions
