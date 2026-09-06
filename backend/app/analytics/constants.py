"""Digest constants not already owned by the canonical registry.

The overlapping ranking and budget values are imported from ``app.constants`` so
Section 21 remains the only source of truth.
"""

from app.constants import (
    DECAY_TAU_SESSIONS,
    W_DELIVERY,
    W_EXTREME,
    W_SCAR,
    W_TURNOVER,
)

WEIGHT_SAR: float = W_SCAR
WEIGHT_TURNOVER_Z: float = W_TURNOVER
WEIGHT_DELIVERY_Z: float = W_DELIVERY
WEIGHT_EXTREME: float = W_EXTREME
RECENCY_DECAY_TAU_SESSIONS: float = DECAY_TAU_SESSIONS

BOOST_HELD: float = 1.0
BOOST_PINNED: float = 1.0
BOOST_RECENTLY_ADDED: float = 0.5
BOOST_LEVEL_CROSSED: float = 1.4

MAX_ITEMS_PER_SECTOR: int = 3
SECTOR_DIVERSITY_SAR_OVERRIDE: float = 4.0

# Freshness State Machine Timing Thresholds (Milliseconds)
FRESHNESS_LIVE_MAX_AGE_MS: int = 5_000
FRESHNESS_FLOW_MAX_AGE_MS: int = 90_000
FRESHNESS_THIN_SILENCE_MS: int = 90_000
FRESHNESS_ANCHOR_SILENCE_MS: int = 15_000

# Canonical benchmark used to distinguish thin symbols from feed-wide silence.
BENCHMARK_ANCHOR_SYMBOL: str = "NIFTY 50"

# Redis Streams Tick Transport
STREAM_TICKS_KEY: str = "stream:market:ticks"
STREAM_TICKS_DLQ_KEY: str = "stream:market:ticks:dlq"
STREAM_TICKS_MAXLEN: int = 100_000
STREAM_CONSUMER_BATCH_SIZE: int = 100
STREAM_CONSUMER_BLOCK_MS: int = 2_000
STREAM_CLAIM_MIN_IDLE_TIME_MS: int = 5_000
STREAM_MAX_DELIVERY_ATTEMPTS: int = 3

# WebSocket Gateway & Conflation
WS_CONFLATION_INTERVAL_MS: int = 250
WS_CLIENT_OUTBOUND_QUEUE_MAXSIZE: int = 50
WS_SLOW_CLIENT_TIMEOUT_SECONDS: float = 30.0
WS_MAX_SUBSCRIPTIONS_PER_CLIENT: int = 100
WS_HEARTBEAT_INTERVAL_SECONDS: float = 15.0
