from datetime import UTC, datetime
from decimal import Decimal

from app.analytics.streaming.client_state import StreamingSyncClient
from app.analytics.streaming.session import ClientSession
from app.schemas.quote import (
    CircuitState,
    FreshnessState,
    QuoteDeltaPayload,
    StreamFrameEnvelope,
    StreamMessageType,
    SyncClientState,
)


def quote(symbol: str, value: str) -> QuoteDeltaPayload:
    return QuoteDeltaPayload(
        symbol=symbol,
        ltp=Decimal(value),
        change=Decimal("0"),
        change_pct=0,
        open=Decimal(value),
        high=Decimal(value),
        low=Decimal(value),
        close=Decimal(value),
        volume=0,
        turnover=Decimal("0"),
        upper_band=None,
        lower_band=None,
        circuit_state=CircuitState.NORMAL,
        freshness_state=FreshnessState.LIVE,
        freshness_age_ms=0,
        as_of_ts=datetime.now(UTC),
        quality_flag="OK",
    )


def frame(kind: StreamMessageType, seq: int, *quotes: QuoteDeltaPayload) -> StreamFrameEnvelope:
    return StreamFrameEnvelope(
        type=kind, seq=seq, as_of=datetime.now(UTC), quotes=list(quotes)
    )


def test_gap_detection_and_snapshot_recovery() -> None:
    client = StreamingSyncClient()
    assert client.handle_message(
        frame(StreamMessageType.SNAPSHOT, 1, quote("RELIANCE", "2500"), quote("TCS", "3500"))
    ) is None
    assert client.state is SyncClientState.SYNCED
    assert client.expected_seq == 2
    assert client.handle_message(
        frame(StreamMessageType.DELTA, 2, quote("RELIANCE", "2505"))
    ) is None
    assert client.handle_message(frame(StreamMessageType.DELTA, 3, quote("TCS", "3510"))) is None
    assert client.handle_message(
        frame(StreamMessageType.DELTA, 7, quote("TCS", "3525"))
    ) == "resync"
    assert client.state is SyncClientState.RE_SYNCING
    assert client.store["TCS"].ltp == Decimal("3510")
    assert client.handle_message(frame(StreamMessageType.DELTA, 8, quote("TCS", "3525"))) is None
    assert client.discarded_delta_count == 2
    assert client.handle_message(
        frame(StreamMessageType.SNAPSHOT, 9, quote("RELIANCE", "2515"), quote("TCS", "3525"))
    ) is None
    assert client.expected_seq == 10
    assert client.handle_message(
        frame(StreamMessageType.DELTA, 10, quote("RELIANCE", "2520"))
    ) is None
    assert client.store["RELIANCE"].ltp == Decimal("2520")


def test_session_sequences_snapshot_and_delta() -> None:
    session = ClientSession("session", object())
    session.subscribed_symbols.update({"RELIANCE", "TCS"})
    session.update_tick(quote("RELIANCE", "2500"))
    snapshot = session.generate_snapshot()
    assert snapshot.type is StreamMessageType.SNAPSHOT
    assert snapshot.seq == 1
    delta = session.generate_delta([quote("RELIANCE", "2505")])
    assert delta.type is StreamMessageType.DELTA
    assert delta.seq == 2
