"""Runtime configuration — connection strings, credentials, feature switches.

This file holds NO business thresholds. Every number that shapes a signal, a
score, a window or a cap lives in `constants.py` and only there (R1). What is
configurable here is where things are and who we authenticate as — the sort of
thing that legitimately differs between a laptop and the demo container.

Values come from the environment, or from `.env` at the repository root. See
`.env.example` for the full set.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Market Analytics Engine"
    ENV: str = "development"
    DATABASE_URL: str = "postgresql+psycopg://localhost:5432/swl"
    REDIS_URL: str = "redis://localhost:6379/0"
    legacy_database_url: str = "postgresql+psycopg://localhost:5432/swl"
    legacy_redis_url: str = "redis://localhost:6379/0"
    DEMO_AUTH_ENABLED: bool = True
    STATIC_DIST_PATH: str = "frontend/dist"

    @field_validator("DATABASE_URL", "database_url", "legacy_database_url", mode="after")
    @classmethod
    def _accept_provider_pg_url(cls, value: str) -> str:
        return _normalise_pg_url(value)

    @property
    def project_name(self) -> str:
        return self.PROJECT_NAME

    database_url: str = "postgresql+psycopg://swl:swl@localhost:5432/swl"
    redis_url: str = "redis://localhost:6379/0"

    # -- ingest -------------------------------------------------------------
    cache_root: Path = REPO_ROOT / "data" / "cache"
    from_cache_only: bool = Field(
        default=False,
        description=(
            "Serve every NSE fetch from the local cache and never touch the "
            "network. Offline development and the no-network demo path."
        ),
    )

    # -- live quotes — §14.1 QuoteSource ------------------------------------
    # POLLING is the default and the shipped fallback. A broker is a config
    # change, not a code change: set quote_source plus that broker's
    # credentials and the abstraction resolves the rest. See §0.2 of the
    # BUILD_PLAN and docs/broker-access.md for the decision on this build.
    quote_source: str = "POLLING"
    broker_api_key: str = ""
    broker_api_secret: str = ""
    broker_access_token: str = ""

    # -- app ----------------------------------------------------------------
    log_level: str = "INFO"
    serve_spa: bool = True
    spa_dist_dir: Path = REPO_ROOT / "frontend" / "dist"


# The scheme managed Postgres providers hand out. SQLAlchemy needs an explicit
# driver, and psycopg 3 is what this build installs.
_LEGACY_PG_SCHEMES = ("postgres://", "postgresql://")


def _normalise_pg_url(url: str) -> str:
    """Accept the `postgres://` URL a managed provider hands out.

    Railway, Fly, Render and Heroku all expose DATABASE_URL with a bare
    `postgres://` or `postgresql://` scheme. SQLAlchemy resolves the latter to
    psycopg2, which this build does not install, and rejects the former
    outright. Rewriting here means the deploy can paste the provider's value
    unchanged instead of hand-editing a connection string at 3am.
    """
    for scheme in _LEGACY_PG_SCHEMES:
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url[len(scheme):]
    return url


def assert_production_ready(settings: Settings) -> None:
    """Fail fast, and loudly, on a misconfigured production boot.

    A container that starts and then serves a blank page or an empty Brief is
    far worse than one that refuses to start: the first is discovered by a
    reviewer, the second by the deploy log. Both checks below are for
    misconfiguration that is silent at boot and only visible on the demo path.
    """
    if settings.ENV.lower() not in {"production", "prod"}:
        return

    problems: list[str] = []

    if "localhost" in settings.DATABASE_URL or "127.0.0.1" in settings.DATABASE_URL:
        problems.append(
            "DATABASE_URL still points at localhost — the production database "
            "was not injected into the environment."
        )

    index = Path(settings.STATIC_DIST_PATH) / "index.html"
    if not index.is_file():
        problems.append(
            f"No SPA build at {index} — the image would serve 404s at the root. "
            "Check STATIC_DIST_PATH and that the web build stage ran."
        )

    if problems:
        joined = "\n  - ".join(problems)
        raise RuntimeError("Refusing to start in ENV=production:\n  - " + joined)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
