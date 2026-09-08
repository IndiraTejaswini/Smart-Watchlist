"""DATABASE_URL normalisation — Neon compatibility.

Neon hands out a `postgres://` (or `postgresql://`) URL with a pooled host
(contains `-pooler`) and `sslmode=require&channel_binding=require` query
parameters. This project's only database driver is psycopg 3
(`psycopg[binary]` — see backend/pyproject.toml; there is no asyncpg
dependency anywhere in the tree), and psycopg 3 accepts both `sslmode` and
`channel_binding` unchanged as libpq connection parameters passed straight
through the URL's query string — unlike asyncpg, which needs `ssl=` or an
explicit SSLContext and rejects `sslmode` outright. Nothing about those two
parameters needs special handling here; the only real gap was the scheme.
"""

from __future__ import annotations

from app.config import _normalise_pg_url


def test_bare_postgres_scheme_gets_a_driver():
    url = "postgres://user:pass@host/db"
    assert _normalise_pg_url(url) == "postgresql+psycopg://user:pass@host/db"


def test_bare_postgresql_scheme_gets_a_driver():
    url = "postgresql://user:pass@host/db"
    assert _normalise_pg_url(url) == "postgresql+psycopg://user:pass@host/db"


def test_already_driver_qualified_url_is_untouched():
    url = "postgresql+psycopg://user:pass@host/db"
    assert _normalise_pg_url(url) == url


def test_neon_pooled_url_with_sslmode_and_channel_binding():
    """The exact shape Neon's dashboard hands out, pooled endpoint included."""
    url = (
        "postgresql://neondb_owner:secret@ep-example-pooler.c-4"
        ".ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    normalised = _normalise_pg_url(url)
    assert normalised.startswith("postgresql+psycopg://")
    # The query string — including the pooled host — passes through
    # unchanged; psycopg (unlike asyncpg) understands both params natively.
    assert "sslmode=require" in normalised
    assert "channel_binding=require" in normalised
    assert "-pooler" in normalised


def test_non_postgres_url_is_untouched():
    url = "redis://localhost:6379/0"
    assert _normalise_pg_url(url) == url
