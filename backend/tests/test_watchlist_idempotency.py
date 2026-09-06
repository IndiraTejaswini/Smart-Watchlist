from decimal import Decimal

from app.analytics.fractional_index import generate_midpoint_position
from app.api.idempotency import (
    CachedResponse,
    idempotency_key,
    load_cached_response,
    store_response,
)


def test_fractional_positions_do_not_rewrite_neighbors() -> None:
    assert generate_midpoint_position(Decimal("100"), Decimal("200")) == Decimal("150")
    assert generate_midpoint_position(Decimal("100"), Decimal("150")) == Decimal("125")
    assert generate_midpoint_position(None, None) == Decimal("1000.0000000000000000")


def test_idempotency_response_round_trips_with_ttl() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, tuple[str, int]] = {}

        def set(self, key: str, value: str, ex: int) -> None:
            self.values[key] = (value, ex)

        def get(self, key: str) -> str | None:
            item = self.values.get(key)
            return item[0] if item else None

    redis = FakeRedis()
    response = CachedResponse(201, {}, {"symbol": "RELIANCE"})
    store_response(redis, "TRADER", "test-key", response)
    assert idempotency_key("TRADER", "test-key") in redis.values
    assert load_cached_response(redis, "TRADER", "test-key") == response
    assert redis.values[idempotency_key("TRADER", "test-key")][1] == 86400
