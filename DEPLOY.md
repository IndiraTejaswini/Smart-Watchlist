# DEPLOY.md

One service, pre-seeded. FastAPI serves the API and the built SPA from the same
process (`Dockerfile`, §19.3), so there is no CORS, no second deploy target and
no API base URL to configure.

The database is **seeded by dump and restore**, not by running the pipeline
against the remote host. NSE blocks datacenter IPs, so a remote ingest may fail
outright; a restore takes minutes and is reproducible.

---

## Services

| Service | What |
|---|---|
| Web | This repo's `Dockerfile`, one always-on instance |
| Postgres | Managed, ≥2 GB storage (the seed restores to ~1.1 GB) |
| Redis | Managed. Quotes and caches only — all rebuildable from Postgres |

**The one disqualifying property is spin-down on inactivity.** A free tier that
sleeps costs 30–60 s on the first request and loses the reviewer. Use Railway
Hobby or Fly with `auto_stop_machines = false` (already set in `fly.toml`).

## Environment variables

Names only. Set them in the provider's dashboard; nothing is baked into the
image and nothing is committed.

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Paste the provider's value as-is — a `postgres://` scheme is rewritten to `postgresql+psycopg://` at load |
| `REDIS_URL` | |
| `ENV` | `production` — enables the startup assertion below |
| `STATIC_DIST_PATH` | `/app/static` (already set in the image) |
| `PORT` | Usually injected by the provider |
| `QUOTE_SOURCE` | `POLLING`. The shipped default; needs no credentials |
| `BROKER_API_KEY` / `_SECRET` / `_ACCESS_TOKEN` | Optional. **The app runs fully without them** — the freshness state machine reports the feed down and the UI labels prices as final exchange data |
| `FROM_CACHE_ONLY` | `true` to make NSE fetches serve from the local cache and never touch the network |
| `LOG_LEVEL` | `INFO` |

There is no `JWT_SECRET` and no demo password: this build has no login. Auth is
a header shim (`app/api/auth.py`) that resolves every caller to `demo_trader`,
which is why the reviewer reaches a populated Brief with no signup. It is also
why the demo is read-mostly by construction — there is no second user's data to
reach.

**Startup assertion.** With `ENV=production` the app refuses to boot if
`DATABASE_URL` still points at localhost, or if there is no SPA build at
`STATIC_DIST_PATH`. A container that starts and then serves a blank page is
worse than one that fails in the deploy log.

## Deploy — Railway

```bash
railway login
railway init                       # or: railway link  <existing project>
railway add --database postgres
railway add --database redis
railway up                         # builds the Dockerfile and deploys
```

Set `ENV=production` in the service variables; Railway injects `DATABASE_URL`,
`REDIS_URL` and `PORT`. Confirm the plan does not sleep the service.

## Deploy — Fly.io

```bash
fly launch --no-deploy             # fly.toml is already in the repo
fly postgres create --name swl-db && fly postgres attach swl-db
fly redis create                   # sets REDIS_URL
fly secrets set ENV=production
fly deploy
```

## Seed the database

Run against the production database once, after the first deploy. Migrations
have already run at container boot, so restore into the existing schema.

```bash
# 1. Locally, after the full pipeline has run
pg_dump --no-owner --no-acl -Fc swl > seed.dump      # ~1.1 GB → ~100 MB compressed

# 2. Against production — schema is already there from the container's own
# `alembic upgrade head` at boot, so restore data only.
pg_restore --no-owner --no-acl --data-only --disable-triggers \
  -d "$PROD_DATABASE_URL" seed.dump
```

`seed.dump` is gitignored. Never commit it.

Verify the restore landed:

```bash
curl -s https://<your-host>/api/health
# expect: "status":"ok" and a "last_bhavcopy_date" inside the seeded range
```

## Redeploy

```bash
railway up          # or: fly deploy
```

Migrations are idempotent, so a redeploy against a seeded database is a no-op
rather than a re-seed.

## Rollback

Keep the previous image tag. Both providers roll back without a rebuild:

```bash
fly releases                     # find the previous version
fly deploy --image <previous-image-ref>
# or
fly releases rollback

railway rollback                 # or redeploy the previous deployment from the dashboard
```

Under five minutes, no debugging. If a last-minute change breaks the deploy,
roll back first and diagnose after.

## Expected degraded state

Two things are expected not to work from a cloud host, and the app is designed
for both:

- **NSE blocks datacenter IPs.** Announcement polling and bhavcopy downloads may
  return 403. The circuit breaker (task 2.6) absorbs it and `/api/health`
  reports `nse_breaker_state`. Because the database is pre-seeded, the demo is
  unaffected.
- **No broker credentials.** `feed_state` is `CLOSED`/`NO_DATA`, prices render
  as final exchange data and the UI says so in plain English.

Neither should look like a broken deploy. If either renders as a spinner or a
blank table, that is a bug, not a degradation.
