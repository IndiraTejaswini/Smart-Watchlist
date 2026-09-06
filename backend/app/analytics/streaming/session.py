"""Per-client WebSocket buffering and conflation."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.analytics.constants import (
    WS_CLIENT_OUTBOUND_QUEUE_MAXSIZE,
    WS_SLOW_CLIENT_TIMEOUT_SECONDS,
)
from app.schemas.quote import QuoteDeltaPayload, StreamFrameEnvelope, StreamMessageType


class ClientSession:
    def __init__(
        self,
        session_id: str,
        websocket: Any,
        max_queue_size: int = WS_CLIENT_OUTBOUND_QUEUE_MAXSIZE,
    ) -> None:
        self.session_id = session_id
        self.websocket = websocket
        self.subscribed_symbols: set[str] = set()
        self.conflation_buffer: dict[str, QuoteDeltaPayload] = {}
        self.outbound_queue: asyncio.Queue[Any] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self.stalled_since_ts: float | None = None
        self.is_active = True
        self.current_seq = 0
        self.latest_state_cache: dict[str, QuoteDeltaPayload] = {}

    def update_tick(self, quote: QuoteDeltaPayload) -> None:
        if quote.symbol in self.subscribed_symbols:
            self.conflation_buffer[quote.symbol] = quote
            self.latest_state_cache[quote.symbol] = quote

    def next_sequence(self) -> int:
        self.current_seq += 1
        return self.current_seq

    def generate_snapshot(self) -> StreamFrameEnvelope:
        return StreamFrameEnvelope(
            type=StreamMessageType.SNAPSHOT,
            seq=self.next_sequence(),
            as_of=datetime.now(UTC),
            quotes=list(self.latest_state_cache.values()),
        )

    def generate_delta(self, quotes: list[QuoteDeltaPayload]) -> StreamFrameEnvelope:
        for quote in quotes:
            self.latest_state_cache[quote.symbol] = quote
        return StreamFrameEnvelope(
            type=StreamMessageType.DELTA,
            seq=self.next_sequence(),
            as_of=datetime.now(UTC),
            quotes=quotes,
        )

    def flush_conflated_batch(self, current_time: float) -> list[QuoteDeltaPayload] | None:
        del current_time
        if not self.conflation_buffer:
            return None
        batch = list(self.conflation_buffer.values())
        self.conflation_buffer.clear()
        return batch

    def enqueue_outbound(
        self, batch: Any, current_time: float
    ) -> bool:
        if not batch:
            return True
        if not self.outbound_queue.full():
            self.outbound_queue.put_nowait(batch)
            self.stalled_since_ts = None
            return True
        if self.stalled_since_ts is None:
            self.stalled_since_ts = current_time
        if current_time - self.stalled_since_ts >= WS_SLOW_CLIENT_TIMEOUT_SECONDS:
            return False
        self.outbound_queue.get_nowait()
        self.outbound_queue.task_done()
        self.outbound_queue.put_nowait(batch)
        return True
