"""Synchronous cache invalidation after official market data lands."""

from datetime import date
from typing import Any


def handle_bhavcopy_landed(redis_client: Any, trading_date: date) -> int:
    """Purge all brief and symbol caches before ingestion acknowledgement."""
    del trading_date
    keys = list(redis_client.keys("cache:brief:*"))
    keys.extend(redis_client.keys("cache:symbol:*"))
    return int(redis_client.unlink(*keys)) if keys else 0
