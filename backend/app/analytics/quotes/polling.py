"""Drift-compensated polling quote source."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import suppress
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Any

from app.analytics.quotes.protocol import QuoteSource
from app.crud.quotes import fetch_quotes_batch
from app.schemas.quote import QuoteDeltaPayload
from app.timeutil import TradingCalendar


class PollingSource(QuoteSource):
    def __init__(
        self,
        db_factory: Callable[[], Any],
        redis_client: Any,
        calendar: TradingCalendar,
        poll_interval_seconds: float = 5.0,
        batch_chunk_size: int = 100,
        max_queue_size: int = 5000,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if batch_chunk_size <= 0:
            raise ValueError("batch_chunk_size must be positive")
        self._db_factory = db_factory
        self._redis_client = redis_client
        self._calendar = calendar
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_chunk_size = batch_chunk_size
        self._queue: asyncio.Queue[QuoteDeltaPayload] = asyncio.Queue(maxsize=max_queue_size)
        self._symbols: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._update_event = asyncio.Event()

    @property
    def symbols(self) -> frozenset[str]:
        return frozenset(self._symbols)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_poll_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        self._update_event.set()
        task = self._task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._task = None
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

    async def subscribe(self, symbols: Iterable[str]) -> None:
        self._symbols.update(symbol.strip().upper() for symbol in symbols if symbol.strip())
        self._update_event.set()

    async def unsubscribe(self, symbols: Iterable[str]) -> None:
        self._symbols.difference_update(
            symbol.strip().upper() for symbol in symbols if symbol.strip()
        )
        self._update_event.set()

    async def _fetch(self, symbols: list[str]) -> list[QuoteDeltaPayload]:
        db = self._db_factory()
        try:
            result = await asyncio.to_thread(
                fetch_quotes_batch,
                db,
                self._redis_client,
                symbols,
                datetime.now(UTC),
                self._calendar,
            )
            if isawaitable(result):
                return await result
            return result
        finally:
            close = getattr(db, "close", None)
            if close is not None:
                close()

    async def _run_poll_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while not self._stop_event.is_set():
            if not self._symbols:
                self._update_event.clear()
                await self._update_event.wait()
                continue
            next_tick = max(next_tick, loop.time())
            snapshot = sorted(self._symbols)
            for start in range(0, len(snapshot), self._batch_chunk_size):
                batch = await self._fetch(snapshot[start : start + self._batch_chunk_size])
                for quote in batch:
                    if self._queue.full():
                        self._queue.get_nowait()
                        self._queue.task_done()
                    self._queue.put_nowait(quote)
            next_tick += self._poll_interval_seconds
            await asyncio.sleep(max(0.0, next_tick - loop.time()))

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
