"""Resilient broker websocket quote source."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Iterable
from contextlib import suppress
from datetime import datetime
from decimal import Decimal
from typing import Any

import websockets

from app.analytics.quotes.protocol import QuoteSource
from app.schemas.quote import CircuitState, FreshnessState, QuoteDeltaPayload

log = logging.getLogger(__name__)


class BrokerWebSocketSource(QuoteSource):
    def __init__(
        self,
        ws_url: str,
        api_key: str,
        auth_token: str,
        ping_timeout_seconds: float = 5.0,
        base_reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 5.0,
        max_queue_size: int = 5000,
    ) -> None:
        self.ws_url = ws_url
        self.api_key = api_key
        self.auth_token = auth_token
        self.ping_timeout_seconds = ping_timeout_seconds
        self.base_reconnect_delay = base_reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self._symbols: set[str] = set()
        self._queue: asyncio.Queue[QuoteDeltaPayload] = asyncio.Queue(maxsize=max_queue_size)
        self._task: asyncio.Task[None] | None = None
        self._socket: Any = None
        self._running = False
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    @property
    def symbols(self) -> frozenset[str]:
        return frozenset(self._symbols)

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._connection_loop())

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        socket = self._socket
        if socket is not None:
            with suppress(Exception):
                await socket.close(code=1000)
        task = self._task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._task = None
        self._socket = None
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

    async def subscribe(self, symbols: Iterable[str]) -> None:
        additions = {symbol.strip().upper() for symbol in symbols if symbol.strip()}
        if not additions:
            return
        async with self._lock:
            self._symbols.update(additions)
            await self._send_subscription("subscribe", additions)

    async def unsubscribe(self, symbols: Iterable[str]) -> None:
        removals = {symbol.strip().upper() for symbol in symbols if symbol.strip()}
        if not removals:
            return
        async with self._lock:
            removed = self._symbols & removals
            self._symbols.difference_update(removals)
            await self._send_subscription("unsubscribe", removed)

    async def _send_subscription(self, action: str, symbols: Iterable[str]) -> None:
        if self._socket is not None and self._running:
            values = sorted(set(symbols))
            if values:
                await self._socket.send(json.dumps({"action": action, "symbols": values}))

    async def _connection_loop(self) -> None:
        attempts = 0
        while self._running:
            try:
                async with websockets.connect(
                    self.ws_url,
                    additional_headers={
                        "X-API-Key": self.api_key,
                        "Authorization": f"Bearer {self.auth_token}",
                    },
                    ping_interval=None,
                ) as socket:
                    self._socket = socket
                    attempts = 0
                    await self._send_subscription("subscribe", self._symbols)
                    await self._read_loop(socket)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                log.warning("broker websocket connection failed: %s", exc)
                delay = min(
                    self.max_reconnect_delay,
                    self.base_reconnect_delay * (2**attempts),
                ) + random.uniform(0.0, 0.5)
                attempts += 1
                await asyncio.sleep(delay)
            finally:
                self._socket = None

    async def _read_loop(self, socket: Any) -> None:
        while self._running:
            try:
                frame = await asyncio.wait_for(socket.recv(), self.ping_timeout_seconds)
            except TimeoutError as exc:
                raise TimeoutError("broker websocket silence timeout") from exc
            if frame is None:
                raise ConnectionError("broker websocket closed")
            if isinstance(frame, bytes):
                frame = frame.decode()
            payload = json.loads(frame) if isinstance(frame, str) else frame
            quote = self._parse_quote(payload)
            if self._queue.full():
                self._queue.get_nowait()
                self._queue.task_done()
            self._queue.put_nowait(quote)

    @staticmethod
    def _parse_quote(payload: dict[str, Any]) -> QuoteDeltaPayload:
        timestamp = payload["as_of_ts"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return QuoteDeltaPayload(
            symbol=str(payload["symbol"]),
            ltp=Decimal(str(payload["ltp"])),
            change=Decimal(str(payload.get("change", 0))),
            change_pct=float(payload.get("change_pct", 0.0)),
            open=Decimal(str(payload.get("open", payload["ltp"]))),
            high=Decimal(str(payload.get("high", payload["ltp"]))),
            low=Decimal(str(payload.get("low", payload["ltp"]))),
            close=Decimal(str(payload.get("close", payload["ltp"]))),
            volume=int(payload.get("volume", 0)),
            turnover=Decimal(str(payload.get("turnover", 0))),
            upper_band=(
                Decimal(str(payload["upper_band"]))
                if payload.get("upper_band") is not None
                else None
            ),
            lower_band=(
                Decimal(str(payload["lower_band"]))
                if payload.get("lower_band") is not None
                else None
            ),
            circuit_state=CircuitState(str(payload.get("circuit_state", "NORMAL"))),
            freshness_state=FreshnessState(str(payload.get("freshness_state", "UNKNOWN"))),
            freshness_age_ms=int(payload.get("freshness_age_ms", 0)),
            as_of_ts=timestamp,
            quality_flag=str(payload.get("quality_flag", "OK")),
        )

    async def stream_quotes(self) -> AsyncIterator[QuoteDeltaPayload]:
        while self.is_running or not self._queue.empty():
            quote = await self._queue.get()
            self._queue.task_done()
            yield quote

    async def stream_batches(self) -> AsyncIterator[list[QuoteDeltaPayload]]:
        while self.is_running or not self._queue.empty():
            first = await self._queue.get()
            self._queue.task_done()
            batch = [first]
            while True:
                try:
                    quote = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._queue.task_done()
                batch.append(quote)
            yield batch
