"""Reference client-side synchronization state machine."""

from app.schemas.quote import (
    QuoteDeltaPayload,
    StreamFrameEnvelope,
    StreamMessageType,
    SyncClientState,
)


class StreamingSyncClient:
    def __init__(self) -> None:
        self.state = SyncClientState.CONNECTING
        self.expected_seq = 0
        self.store: dict[str, QuoteDeltaPayload] = {}
        self.discarded_delta_count = 0

    def handle_message(self, frame: StreamFrameEnvelope) -> str | None:
        if frame.type is StreamMessageType.SNAPSHOT:
            self.store = {quote.symbol: quote for quote in frame.quotes}
            self.expected_seq = frame.seq + 1
            self.state = SyncClientState.SYNCED
            return None
        if frame.type is not StreamMessageType.DELTA:
            return None
        if self.state is SyncClientState.RE_SYNCING:
            self.discarded_delta_count += 1
            return None
        if frame.seq < self.expected_seq:
            return None
        if frame.seq > self.expected_seq:
            self.state = SyncClientState.RE_SYNCING
            self.discarded_delta_count += 1
            return "resync"
        for quote in frame.quotes:
            self.store[quote.symbol] = quote
        self.expected_seq += 1
        return None
