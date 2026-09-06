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

from pydantic import Field
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
