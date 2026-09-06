import asyncio
import json
from datetime import UTC, datetime

import pytest

from app.analytics.quotes.broker_ws import BrokerWebSocketSource


def quote_frame(symbol: str) -> str:
    return json.dumps(
        {
            "symbol": symbol,
            "ltp": "100.00",
            "as_of_ts": datetime.now(UTC).isoformat(),
        }
    )


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.frames: asyncio.Queue[object] = asyncio.Queue()
        self.closed_code: int | None = None

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    async def recv(self) -> object:
        frame = await self.frames.get()
        if isinstance(frame, BaseException):
            raise frame
        return frame

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


class FakeConnection:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> FakeSocket:
        return self.socket

    async def __aexit__(self, *_args: object) -> None:
        await self.socket.close()


@pytest.mark.asyncio
async def test_reconnects_and_resubscribes(monkeypatch: pytest.MonkeyPatch) -> None:
    first_socket = FakeSocket()
    second_socket = FakeSocket()
    sockets = iter([first_socket, second_socket])
    connect_kwargs: list[dict[str, object]] = []

    def connect(_url: str, **kwargs: object) -> FakeConnection:
        connect_kwargs.append(kwargs)
        return FakeConnection(next(sockets))

    monkeypatch.setattr("app.analytics.quotes.broker_ws.websockets.connect", connect)
    monkeypatch.setattr(
        "app.analytics.quotes.broker_ws.random.uniform", lambda _lower, _upper: 0.0
    )
    source = BrokerWebSocketSource(
        "ws://broker",
        "key",
        "token",
        base_reconnect_delay=0.01,
        max_reconnect_delay=0.01,
    )
    await source.subscribe(["reliance", "TCS"])
    await source.start()
    try:
        for _ in range(100):
            if first_socket.sent:
                break
            await asyncio.sleep(0.001)
        assert first_socket.sent == [{"action": "subscribe", "symbols": ["RELIANCE", "TCS"]}]
        assert connect_kwargs[0]["additional_headers"] == {
            "X-API-Key": "key",
            "Authorization": "Bearer token",
        }

        await first_socket.frames.put(quote_frame("RELIANCE"))
        stream = source.stream_quotes()
        quote = await asyncio.wait_for(anext(stream), timeout=1)
        assert quote.symbol == "RELIANCE"

        await first_socket.frames.put(ConnectionError("connection lost"))
        for _ in range(100):
            if len(connect_kwargs) == 2:
                break
            await asyncio.sleep(0.002)
        assert len(connect_kwargs) == 2
        assert second_socket.sent == [{"action": "subscribe", "symbols": ["RELIANCE", "TCS"]}]
    finally:
        await source.stop()
        await stream.aclose()


@pytest.mark.asyncio
async def test_dynamic_subscriptions_are_sent_to_live_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket()

    monkeypatch.setattr(
        "app.analytics.quotes.broker_ws.websockets.connect",
        lambda _url, **_kwargs: FakeConnection(socket),
    )
    source = BrokerWebSocketSource("ws://broker", "key", "token")
    await source.start()
    try:
        await source.subscribe(["INFY", "TCS"])
        for _ in range(100):
            if socket.sent:
                break
            await asyncio.sleep(0.001)
        await source.unsubscribe(["TCS"])
        assert socket.sent[-1] == {"action": "unsubscribe", "symbols": ["TCS"]}
        assert source.symbols == frozenset({"INFY"})
    finally:
        await source.stop()


@pytest.mark.asyncio
async def test_stop_closes_socket_with_normal_close_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket()
    monkeypatch.setattr(
        "app.analytics.quotes.broker_ws.websockets.connect",
        lambda _url, **_kwargs: FakeConnection(socket),
    )
    source = BrokerWebSocketSource("ws://broker", "key", "token")
    await source.start()
    for _ in range(100):
        if source._socket is socket:
            break
        await asyncio.sleep(0.001)
    await source.stop()
    assert socket.closed_code == 1000
    assert not source.is_running
