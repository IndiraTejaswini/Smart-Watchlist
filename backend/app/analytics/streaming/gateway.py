"""Multi-tenant WebSocket quote gateway."""

import asyncio
import json
import time
from typing import Any
from uuid import uuid4

from app.analytics.constants import WS_CONFLATION_INTERVAL_MS
from app.analytics.streaming.session import ClientSession
from app.schemas.quote import QuoteDeltaPayload, StreamFrameEnvelope


class WebSocketGateway:
    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}
        self._symbol_to_sessions: dict[str, set[str]] = {}
        self._flush_task: asyncio.Task[None] | None = None

    @property
    def sessions(self) -> dict[str, ClientSession]:
        return self._sessions

    async def start(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._conflation_flusher_loop())

    async def stop(self) -> None:
        task = self._flush_task
        self._flush_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for session in list(self._sessions.values()):
            await self.disconnect_slow_client(session)

    async def register(
        self, websocket: Any, session_id: str | None = None
    ) -> ClientSession:
        await self.start()
        session = ClientSession(session_id or str(uuid4()), websocket)
        self._sessions[session.session_id] = session
        return session

    async def subscribe(self, session: ClientSession, symbols: set[str]) -> None:
        for symbol in symbols:
            self._symbol_to_sessions.setdefault(symbol, set()).add(session.session_id)
        session.subscribed_symbols.update(symbols)
        self._enqueue_priority(session, session.generate_snapshot())

    async def unsubscribe(self, session: ClientSession, symbols: set[str]) -> None:
        session.subscribed_symbols.difference_update(symbols)
        for symbol in symbols:
            subscribers = self._symbol_to_sessions.get(symbol)
            if subscribers is not None:
                subscribers.discard(session.session_id)
                if not subscribers:
                    del self._symbol_to_sessions[symbol]

    async def disconnect_slow_client(self, session: ClientSession) -> None:
        if not session.is_active:
            return
        session.is_active = False
        try:
            await session.websocket.close(
                code=1008, reason="Slow consumer: backpressure exceeded 30s timeout"
            )
        finally:
            await self._remove(session)

    async def disconnect(self, session: ClientSession) -> None:
        session.is_active = False
        await self._remove(session)

    async def _remove(self, session: ClientSession) -> None:
        self._sessions.pop(session.session_id, None)
        await self.unsubscribe(session, set(session.subscribed_symbols))

    async def broadcast_tick(self, quote: QuoteDeltaPayload) -> None:
        for session_id in tuple(self._symbol_to_sessions.get(quote.symbol, ())):
            session = self._sessions.get(session_id)
            if session is not None and session.is_active:
                session.update_tick(quote)

    async def resync(self, session: ClientSession) -> None:
        self._enqueue_priority(session, session.generate_snapshot())

    def _enqueue_priority(
        self, session: ClientSession, envelope: StreamFrameEnvelope
    ) -> None:
        if session.outbound_queue.full():
            session.outbound_queue.get_nowait()
            session.outbound_queue.task_done()
        session.outbound_queue.put_nowait(envelope)

    async def _conflation_flusher_loop(self) -> None:
        interval = WS_CONFLATION_INTERVAL_MS / 1000.0
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            for session in tuple(self._sessions.values()):
                if not session.is_active:
                    continue
                batch = session.flush_conflated_batch(now)
                if batch is not None and not session.enqueue_outbound(
                    session.generate_delta(batch), now
                ):
                    asyncio.create_task(self.disconnect_slow_client(session))

    async def client_writer(self, session: ClientSession) -> None:
        while session.is_active:
            envelope = await session.outbound_queue.get()
            try:
                if isinstance(envelope, StreamFrameEnvelope):
                    payload = envelope.model_dump_json()
                else:
                    payload = json.dumps(
                        [quote.model_dump(mode="json") for quote in envelope]
                    )
                await session.websocket.send_text(payload)
            finally:
                session.outbound_queue.task_done()
