"""Quote delta API contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class FreshnessState(StrEnum):
    LIVE = "LIVE"
    STALE = "STALE"
    HALTED = "HALTED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class CircuitState(StrEnum):
    NORMAL = "NORMAL"
    UPPER_CIRCUIT = "UPPER_CIRCUIT"
    LOWER_CIRCUIT = "LOWER_CIRCUIT"


class StreamMessageType(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    DELTA = "DELTA"
    RESYNC = "RESYNC"
    HEARTBEAT = "HEARTBEAT"


class SyncClientState(StrEnum):
    CONNECTING = "CONNECTING"
    SYNCED = "SYNCED"
    RE_SYNCING = "RE_SYNCING"


class QuoteDeltaPayload(BaseModel):
    symbol: str
    ltp: Decimal
    change: Decimal
    change_pct: float
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal
    upper_band: Decimal | None
    lower_band: Decimal | None
    circuit_state: CircuitState
    freshness_state: FreshnessState
    freshness_age_ms: int
    as_of_ts: datetime
    quality_flag: str


class StreamFrameEnvelope(BaseModel):
    type: StreamMessageType
    seq: int
    as_of: datetime
    quotes: list[QuoteDeltaPayload]


class ClientResyncCommand(BaseModel):
    action: Literal["resync"] = "resync"
    feed: str = "quotes"


class QuotesListResponse(BaseModel):
    as_of: datetime
    quotes: list[QuoteDeltaPayload]
