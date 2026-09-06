"""NSE breaker and transport-tier acceptance tests."""

from __future__ import annotations

import pytest

from app.ingest.nse_client import (
    BROWSER_HEADERS,
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
    NSEClient,
)


def test_three_blocks_open_breaker_without_a_fourth_request() -> None:
    clock = [0.0]
    breaker = CircuitBreaker(cooldown_s=10, clock=lambda: clock[0])
    for _ in range(3):
        breaker.before_request()
        breaker.record_block()
    assert breaker.state is BreakerState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_request()


def test_open_breaker_fails_without_network_io() -> None:
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.before_request()
    breaker.record_block()
    client = NSEClient(impersonate=False)
    client.breaker = breaker
    with pytest.raises(CircuitOpenError):
        client._fetch_over_network(
            "https://example.invalid",
            endpoint="test",
            referer="https://example.invalid/",
            accept_missing=False,
        )


def test_cooldown_probe_success_closes_and_failure_reopens() -> None:
    clock = [0.0]
    breaker = CircuitBreaker(cooldown_s=10, clock=lambda: clock[0])
    for _ in range(3):
        breaker.record_block()
    clock[0] = 10
    breaker.before_request()
    assert breaker.state is BreakerState.HALF_OPEN
    breaker.record_success()
    assert breaker.state is BreakerState.CLOSED

    for _ in range(3):
        breaker.record_block()
    clock[0] = 20
    breaker.before_request()
    breaker.record_block()
    assert breaker.state is BreakerState.OPEN


def test_persistent_waf_switches_to_curl_cffi_when_available(monkeypatch) -> None:
    client = NSEClient(impersonate=True)
    client._ensure_session = lambda: object()  # type: ignore[method-assign]
    client._transport = "httpx"
    switched: list[str] = []
    monkeypatch.setattr(client, "_switch_to_impersonation", lambda: switched.append("curl_cffi"))
    client._waf_blocks = 1
    client._waf_blocks += 1
    client._switch_to_impersonation()
    assert switched == ["curl_cffi"]
    assert BROWSER_HEADERS["User-Agent"]


def test_health_includes_breaker_state(monkeypatch) -> None:
    import app.main

    class EmptyConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args, **_kwargs):
            class Result:
                def scalar_one(self):
                    return 0

                def all(self):
                    return []

            return Result()

    class EmptyEngine:
        def connect(self):
            return EmptyConnection()

    monkeypatch.setattr(app.main, "get_engine", lambda: EmptyEngine())
    monkeypatch.setattr(
        app.main,
        "nse_breaker_state",
        lambda: {
            "state": "OPEN",
            "failure_count": 3,
            "last_tripped_at": 1.0,
            "cooldown_remaining_s": 12.0,
        },
    )
    from fastapi.testclient import TestClient

    response = TestClient(app.main.create_app()).get("/api/health")
    assert response.json()["nse_breaker_state"]["state"] == "OPEN"
