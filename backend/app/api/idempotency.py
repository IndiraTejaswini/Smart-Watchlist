"""Redis-backed idempotency response caching."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.constants import IDEMPOTENCY_TTL_SECONDS

TTL_SECONDS = IDEMPOTENCY_TTL_SECONDS


@dataclass(frozen=True)
class CachedResponse:
    status_code: int
    headers: dict[str, str]
    body: dict[str, Any]


def idempotency_key(user_id: str, key: str) -> str:
    return f"idempotency:{user_id}:{key}"


def load_cached_response(redis_client: Any, user_id: str, key: str) -> CachedResponse | None:
    raw = redis_client.get(idempotency_key(user_id, key))
    if raw is None:
        return None
    payload = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    return CachedResponse(
        status_code=int(payload["status_code"]),
        headers=dict(payload["headers"]),
        body=dict(payload["body"]),
    )


def store_response(
    redis_client: Any,
    user_id: str,
    key: str,
    response: CachedResponse,
) -> None:
    payload = json.dumps(
        {
            "status_code": response.status_code,
            "headers": response.headers,
            "body": response.body,
        }
    )
    redis_client.set(idempotency_key(user_id, key), payload, ex=TTL_SECONDS)
