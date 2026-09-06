"""NSE HTTP client — ARCHITECTURE.md §6.3.

NSE endpoints need a browser-like session: realistic headers, a prior GET to
the homepage for the `nsit` / `nseappid` cookies, and a delay between requests.
They fail intermittently and their anti-bot rules change.

Three tiers, per §6.3:

  Tier 1  httpx with ONE realistic modern browser header set, kept constant per
          session (rotation makes traffic look MORE synthetic, not less),
          explicit homepage warmup before any call, cookie refresh on 401/403,
          exponential backoff with jitter capped at NSE_MAX_ATTEMPTS, 30s
          timeout.
  Tier 2  Circuit breaker. NSE_BREAKER_FAILURES consecutive 403/429 opens it;
          it stays open for NSE_BREAKER_COOLDOWN_S, then half-opens with a
          single probe. Prevents burning every retry against an active block.
  Tier 3  curl_cffi with Chrome TLS impersonation, used automatically when the
          package is installed. Modern anti-bot tooling fingerprints the TLS
          handshake (JA3/JA4) and HTTP/2 settings, so correct headers alone are
          not sufficient.

  Always  Local disk cache at data/cache/{source}/{date}/ with a SHA-256
          sidecar, and a --from-cache-only flag for offline development.

Why the cache is P0: the network is the least reliable component and the one
most likely to burn irreplaceable hours. Download once, develop offline forever.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.constants import (
    NSE_BREAKER_COOLDOWN_S,
    NSE_BREAKER_FAILURES,
    NSE_MAX_ATTEMPTS,
)

log = logging.getLogger(__name__)

# ─── Session shape ──────────────────────────────────────────────────────────
# Not a tunable threshold: this is the identity of the browser we present, and
# §6.3 requires it be ONE set held constant for the life of the session.
NSE_HOME = "https://www.nseindia.com"
NSE_ARCHIVES = "https://nsearchives.nseindia.com"

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

# Timeout and pacing. §6.3 fixes the timeout at 30s; the inter-request delay and
# the backoff base are transport mechanics, not business thresholds.
REQUEST_TIMEOUT_S = 30.0
BACKOFF_BASE_S = 1.5
BACKOFF_MAX_S = 60.0
INTER_REQUEST_DELAY_S = 0.8
COOKIE_MAX_AGE_S = 600.0

BLOCK_STATUSES = frozenset({403, 429})
AUTH_STATUSES = frozenset({401, 403})
RETRY_STATUSES = frozenset({401, 403, 408, 429, 500, 502, 503, 504})

CACHE_ROOT = Path("data/cache")


class BreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class NSEError(RuntimeError):
    """Base for every failure this client raises."""


class CircuitOpenError(NSEError):
    """The breaker is open; the request was not attempted."""


class CacheMissError(NSEError):
    """--from-cache-only was set and the file is not on disk."""


class FetchFailedError(NSEError):
    """Every attempt was exhausted without a usable response."""


@dataclass
class ClientMetrics:
    """§6.3 client metrics, held in-process until Phase 14 wires Prometheus."""

    requests_total: dict[tuple[str, int], int] = field(default_factory=dict)
    request_duration_seconds: dict[str, float] = field(default_factory=dict)
    cookie_refresh_total: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    breaker_state: BreakerState = BreakerState.CLOSED

    def record_request(self, endpoint: str, status: int, duration: float) -> None:
        key = (endpoint, status)
        self.requests_total[key] = self.requests_total.get(key, 0) + 1
        self.request_duration_seconds[endpoint] = duration

    @property
    def cache_hit_ratio(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0


class CircuitBreaker:
    """Tier 2. Consecutive blocks open it; a cooldown then one probe closes it.

    Only 403/429 count as block failures — a 500 is NSE being broken, not NSE
    refusing us, and burning a cooldown on it would stall the backfill for no
    reason.
    """

    def __init__(
        self,
        failure_threshold: int = NSE_BREAKER_FAILURES,
        cooldown_s: float = NSE_BREAKER_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._opened_wall: float | None = None
        self._state = BreakerState.CLOSED
        self._probe_in_flight = False

    @property
    def state(self) -> BreakerState:
        with self._lock:
            self._maybe_half_open()
            return self._state

    def _maybe_half_open(self) -> None:
        if (
            self._state is BreakerState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self._cooldown_s
        ):
            self._state = BreakerState.HALF_OPEN
            log.info("nse breaker half-open, sending one probe")

    def before_request(self) -> None:
        with self._lock:
            self._maybe_half_open()
            if self._state is BreakerState.OPEN:
                assert self._opened_at is not None
                remaining = self._cooldown_s - (self._clock() - self._opened_at)
                raise CircuitOpenError(
                    f"nse breaker open, {remaining:.0f}s of cooldown remaining"
                )
            if self._state is BreakerState.HALF_OPEN:
                if self._probe_in_flight:
                    raise CircuitOpenError("nse breaker probe already in flight")
                self._probe_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            if self._state is not BreakerState.CLOSED:
                log.info("nse breaker closed after a successful probe")
            self._consecutive_failures = 0
            self._opened_at = None
            self._opened_wall = None
            self._state = BreakerState.CLOSED
            self._probe_in_flight = False

    def record_block(self) -> None:
        """A 403/429. In HALF_OPEN a single failure re-opens immediately."""
        with self._lock:
            if self._state is BreakerState.HALF_OPEN:
                self._opened_at = self._clock()
                self._opened_wall = time.time()
                self._state = BreakerState.OPEN
                self._probe_in_flight = False
                log.warning("nse breaker re-opened, the probe was blocked")
                return
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = self._clock()
                self._opened_wall = time.time()
                self._state = BreakerState.OPEN
                self._probe_in_flight = False
                log.warning(
                    "nse breaker opened after %d consecutive blocks, cooling down %.0fs",
                    self._consecutive_failures,
                    self._cooldown_s,
                )

    def record_transient(self) -> None:
        """A 5xx or a transport error. Does not count toward the breaker."""
        with self._lock:
            self._probe_in_flight = False

    def snapshot(self) -> dict[str, float | int | str | None]:
        """Return stable breaker telemetry for health and market-status APIs."""
        with self._lock:
            self._maybe_half_open()
            remaining = 0.0
            if self._state is BreakerState.OPEN and self._opened_at is not None:
                remaining = max(0.0, self._cooldown_s - (self._clock() - self._opened_at))
            return {
                "state": self._state.value,
                "failure_count": self._consecutive_failures,
                "last_tripped_at": self._opened_wall,
                "cooldown_remaining_s": round(remaining, 3),
            }


NSE_BREAKER = CircuitBreaker()


def nse_breaker_state() -> dict[str, float | int | str | None]:
    """Telemetry from the process-wide NSE breaker used by default clients."""
    return NSE_BREAKER.snapshot()


# ─── Disk cache ─────────────────────────────────────────────────────────────


def cache_path(
    source: str, target_date: date, filename: str, root: Path = CACHE_ROOT
) -> Path:
    """data/cache/{source}/{date}/{filename} — §6.3."""
    return root / source / target_date.isoformat() / filename


def sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_cached(path: Path, payload: bytes) -> str:
    """Write the payload plus its SHA-256 sidecar [R2]. Returns the digest.

    Written under a temporary name and renamed, so an interrupted download never
    leaves a short file that a later run would trust. The sidecar is written
    only after the payload lands, so a sidecar's presence means the pair is
    complete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(payload)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(payload)
    tmp.replace(path)
    sidecar_path(path).write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def read_cached(path: Path) -> bytes | None:
    """Return the cached bytes if the payload and its sidecar agree, else None.

    A digest mismatch means a truncated or corrupted file. §6.2 notes that
    content hashing also catches truncated downloads that returned HTTP 200, so
    a mismatch is treated as a miss and re-fetched rather than parsed.
    """
    sidecar = sidecar_path(path)
    if not path.exists() or not sidecar.exists():
        return None
    payload = path.read_bytes()
    expected = sidecar.read_text(encoding="ascii").split()[0]
    if sha256_bytes(payload) != expected:
        log.warning("cache digest mismatch for %s, treating it as a miss", path)
        return None
    return payload


# ─── The client ─────────────────────────────────────────────────────────────


class NSEClient:
    """A warmed, cookie-bearing, breaker-guarded, disk-cached NSE session.

    Not thread-safe by design — one client per worker. The backfill is
    deliberately serial: parallel requests are what gets a session blocked.
    """

    def __init__(
        self,
        *,
        from_cache_only: bool = False,
        cache_root: Path = CACHE_ROOT,
        impersonate: bool = True,
    ) -> None:
        self.from_cache_only = from_cache_only
        self.cache_root = Path(cache_root)
        self.metrics = ClientMetrics()
        self.breaker = NSE_BREAKER
        self._session: Any = None
        self._transport = "none"
        self._impersonate = impersonate
        self._waf_blocks = 0
        self._transport_failures = 0
        self._cookies_at: float | None = None
        self._last_request_at: float | None = None

    # -- transport ----------------------------------------------------------

    def _ensure_session(self):
        if self._session is not None:
            return self._session
        if self.from_cache_only:
            raise CacheMissError("--from-cache-only is set; no session is opened")

        import httpx

        self._session = httpx.Client(
            headers=dict(BROWSER_HEADERS),
            timeout=REQUEST_TIMEOUT_S,
            follow_redirects=True,
        )
        self._transport = "httpx"
        log.info("nse transport: httpx browser session (tier 1)")
        return self._session

    def _switch_to_impersonation(self) -> None:
        if not self._impersonate or self._transport == "curl_cffi":
            return
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            log.warning("tier 3 unavailable: curl_cffi is not installed")
            return
        if self._session is not None:
            self._session.close()
        self._session = curl_requests.Session(
            headers=dict(BROWSER_HEADERS),
            timeout=REQUEST_TIMEOUT_S,
            impersonate="chrome",
        )
        self._transport = "curl_cffi"
        log.warning("nse tier switch: curl_cffi Chrome impersonation (tier 3)")

    @property
    def transport(self) -> str:
        return self._transport

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> NSEClient:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- warmup and cookies -------------------------------------------------

    def warmup(self, *, force: bool = False) -> None:
        """GET the homepage for the nsit / nseappid cookies.

        Called before any archive or /api/ request, and again whenever the
        session returns 401/403 — the §6.3 cookie refresh.
        """
        if self.from_cache_only:
            return
        fresh = (
            self._cookies_at is not None
            and time.monotonic() - self._cookies_at < COOKIE_MAX_AGE_S
        )
        if fresh and not force:
            return

        session = self._ensure_session()
        if force:
            self.metrics.cookie_refresh_total += 1
            try:
                session.cookies.clear()
            except Exception:
                log.debug("cookie jar could not be cleared, continuing with warmup")

        self._pace()
        self.breaker.before_request()
        started = time.monotonic()
        try:
            response = session.get(NSE_HOME, headers={"Referer": NSE_HOME + "/"})
        except Exception:
            self.breaker.record_transient()
            raise
        self.metrics.record_request(
            "homepage", response.status_code, time.monotonic() - started
        )
        if response.status_code in BLOCK_STATUSES:
            self.breaker.record_block()
        elif response.status_code < 400:
            self.breaker.record_success()
        if response.status_code >= 400:
            raise FetchFailedError(
                f"homepage warmup returned HTTP {response.status_code}"
            )
        self._cookies_at = time.monotonic()
        log.debug("nse homepage warmup ok via %s", self._transport)

    def _pace(self) -> None:
        """A delay between requests — §6.3."""
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < INTER_REQUEST_DELAY_S:
                time.sleep(INTER_REQUEST_DELAY_S - elapsed)
        self._last_request_at = time.monotonic()

    # -- fetch --------------------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        source: str,
        target_date: date,
        filename: str,
        endpoint: str | None = None,
        referer: str = NSE_HOME + "/all-reports",
        accept_missing: bool = False,
    ) -> bytes | None:
        """Fetch a URL through the disk cache.

        A cache hit short-circuits the network entirely. A miss under
        --from-cache-only raises CacheMissError rather than reaching out.

        accept_missing=True returns None on a 404 instead of raising: NSE has no
        file for a non-trading day, and during a backfill that is an expected
        outcome, not a failure.
        """
        endpoint = endpoint or source
        path = cache_path(source, target_date, filename, self.cache_root)

        cached = read_cached(path)
        if cached is not None:
            self.metrics.cache_hits += 1
            log.debug("cache hit %s", path)
            return cached
        self.metrics.cache_misses += 1

        if self.from_cache_only:
            raise CacheMissError(f"--from-cache-only and no cached file at {path}")

        payload = self._fetch_over_network(
            url, endpoint=endpoint, referer=referer, accept_missing=accept_missing
        )
        if payload is None:
            return None
        write_cached(path, payload)
        return payload

    def _fetch_over_network(
        self,
        url: str,
        *,
        endpoint: str,
        referer: str,
        accept_missing: bool,
    ) -> bytes | None:
        self.breaker.before_request()
        self.warmup()
        session = self._ensure_session()
        last_error = "no attempt was made"

        for attempt in range(1, NSE_MAX_ATTEMPTS + 1):
            self._pace()
            started = time.monotonic()
            try:
                response = session.get(url, headers={"Referer": referer})
            except Exception as exc:
                self.breaker.record_transient()
                self._transport_failures += 1
                if self._transport_failures >= 2:
                    self._switch_to_impersonation()
                self.metrics.record_request(endpoint, 0, time.monotonic() - started)
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "attempt %d/%d for %s failed: %s",
                    attempt,
                    NSE_MAX_ATTEMPTS,
                    url,
                    last_error,
                )
                self._sleep_backoff(attempt)
                continue

            status = response.status_code
            self._transport_failures = 0
            self.metrics.record_request(endpoint, status, time.monotonic() - started)

            if status == 200:
                self.breaker.record_success()
                self.metrics.breaker_state = self.breaker.state
                body = response.content
                if not body:
                    last_error = "HTTP 200 with an empty body"
                    log.warning("%s returned 200 with no body, retrying", url)
                    self._sleep_backoff(attempt)
                    continue
                return body

            if status == 404 and accept_missing:
                self.breaker.record_success()
                log.info("no file published at %s (HTTP 404)", url)
                return None

            if status in BLOCK_STATUSES:
                self.breaker.record_block()
                self.metrics.breaker_state = self.breaker.state
                self._waf_blocks += 1
                if self._waf_blocks >= 2:
                    self._switch_to_impersonation()
            else:
                self.breaker.record_transient()

            if status in AUTH_STATUSES:
                log.info("HTTP %d on %s, refreshing cookies", status, url)
                try:
                    self.warmup(force=True)
                except NSEError as exc:
                    log.warning("cookie refresh failed: %s", exc)

            last_error = f"HTTP {status}"
            if status not in RETRY_STATUSES:
                raise FetchFailedError(f"{url} returned {last_error}")

            log.warning(
                "attempt %d/%d for %s: %s", attempt, NSE_MAX_ATTEMPTS, url, last_error
            )
            self.breaker.before_request()
            self._sleep_backoff(attempt)

        raise FetchFailedError(
            f"{url} failed after {NSE_MAX_ATTEMPTS} attempts, last error: {last_error}"
        )

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        """Exponential backoff with jitter — §6.3.

        Full jitter: the sleep is drawn uniformly from [0, base * 2^(attempt-1)],
        so a fleet of retries does not re-converge on the same instant.
        """
        ceiling = min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_MAX_S)
        time.sleep(random.uniform(0.0, ceiling))
