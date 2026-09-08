# DEPLOY.md

One service, pre-seeded. FastAPI serves the API and the built SPA from the same
process (`Dockerfile`, §19.3), so there is no CORS, no second deploy target and
no API base URL to configure.

**Provider: Render (app) + Neon (Postgres), both free tier.** Render's own free
Postgres deletes itself 30 days after creation, so the database is Neon
instead. This supersedes an earlier Fly.io plan — Fly now requires a credit
card up front.

The database is seeded by **restoring a dump over the internet** into Neon, not
by running the pipeline against it — running the pipeline remotely is slow,
fragile, and unnecessary. Use `seed_demo.dump` (built by
`backend/scripts/make_demo_seed.py`), not the full local `seed.dump` — Neon
free is a 0.5 GB ceiling and the full dump restores to over 1 GB.

---

## The free-tier constraints, and what they force

| Limit | Value | Consequence |
|---|---|---|
| Render free web | 512 MB RAM, 0.1 CPU, ephemeral disk, sleeps after 15 min idle, 750 instance-hours/month | Nothing in the request path may depend on local disk surviving a restart (audited — nothing does; see below). An idle service still costs instance-hours once pinged awake, so keep-warm pinging should start only the day before submission. |
| Neon free Postgres | 0.5 GB storage, 100 compute-hours/month, scales to zero after 5 min idle, wakes in a few hundred ms | The seed must be trimmed to fit. `seed_demo.dump` restores to ~70 MB — large headroom. The wake latency is a non-issue: a few hundred ms is invisible next to the page load itself. |
| Render free Postgres | deletes itself 30 days after creation | Not used at all. Neon only. |

Render's 750 free instance-hours/month is *not* enough to keep one service
running continuously for a full month if it's pinged 24/7 from day one — see
**Keep-warm**, below.

## Services

| Service | What |
|---|---|
| Web | This repo's `Dockerfile`, Render **Docker** runtime, free plan (`render.yaml`) |
| Postgres | Neon free project, **pooled** connection string |
| Redis | A managed free Redis add-on (e.g. Upstash) — quotes/cache only, all rebuildable from Postgres |

## Environment variables

Names only — set values in the Render dashboard (Environment tab), never
committed. `render.yaml` declares these same names with `sync: false` so
Render prompts for them on first deploy.

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Paste Neon's connection string **as-is**, using the **pooled** host (contains `-pooler`) — Render's free web service opens and drops connections as it sleeps/wakes, and the pooler is built for exactly that. A bare `postgres://` scheme is rewritten to `postgresql+psycopg://` at load; `sslmode=require` and `channel_binding=require` are libpq parameters psycopg 3 (this project's only driver — no asyncpg anywhere) understands natively, so nothing else needs adjusting |
| `REDIS_URL` | |
| `ENV` | `production` — enables the startup assertion (refuses to boot against `localhost` or with no SPA build) |
| `QUOTE_SOURCE` | `POLLING`. The shipped default; needs no credentials |
| `BROKER_API_KEY` / `_SECRET` / `_ACCESS_TOKEN` | Optional. **The app runs fully without them** — the freshness state machine reports the feed down and the UI labels prices as final exchange data |
| `FROM_CACHE_ONLY` | `true` — the deployed service never has a local NSE cache to fall back to anyway |
| `LOG_LEVEL` | `INFO` |

There is no `JWT_SECRET` and no demo password: this build has no login. Auth is
a header shim (`app/api/auth.py`) that resolves every unauthenticated caller
to `demo_trader`, which is why a reviewer reaches a populated Brief with no
signup. `GET /api/me` resets that one shared identity's watchlist and cursor
to the seeded baseline on every fresh browser tab (`app/api/core.py`,
`_reset_demo_state`) — see **Multiple reviewers**, below.

**Startup assertion.** With `ENV=production` the app refuses to boot if
`DATABASE_URL` still points at localhost, or if there is no SPA build at
`STATIC_DIST_PATH` (`/app/static` in the image). A container that starts and
then serves a blank page is worse than one that fails in the deploy log.

## Deploy

### 1. Neon

Create a project (any region — `ap-southeast-1` is closest to NSE data but
irrelevant to a static demo). Copy the **pooled** connection string from the
dashboard (Connection Details → check "Pooled connection"). It looks like:

```
postgresql://<user>:<password>@ep-<name>-pooler.<region>.aws.neon.tech/<db>?sslmode=require&channel_binding=require
```

### 2. Render

Push this repo to GitHub, then in the Render dashboard: **New → Blueprint**,
point it at the repo. `render.yaml` at the root declares the service; Render
will prompt for the `sync: false` variables above — paste Neon's `DATABASE_URL`
and the Redis add-on's `REDIS_URL` there.

Without the blueprint: **New → Web Service**, runtime **Docker**, root
Dockerfile, free plan, health check path `/api/health`, then set the same
environment variables by hand.

The first deploy builds the image (`alembic upgrade head` runs empty — no
seed yet) and boots against an empty Neon database. That's expected; seed it
next.

### 3. Seed

Build the trimmed dump locally (regenerate it after any pipeline change — see
its own docstring for what it captures and why):

```bash
python backend/scripts/make_demo_seed.py --verify
```

`--verify` restores the dump into a second scratch database and runs
`tests/test_demo_end_to_end.py` against it — confirms the trim didn't produce
an empty or broken Brief before it goes anywhere near Neon. Without a local
`pg_dump`/`pg_restore` install, run the same command inside any Python
container with `postgresql-client` added, on the same Docker network as the
local Postgres.

Restore it into Neon over the internet — the schema is already there from the
Render container's own `alembic upgrade head`, so restore data only:

```bash
pg_restore --no-owner --no-acl --data-only --disable-triggers \
  -d "$NEON_DATABASE_URL" seed_demo.dump
```

Verify the restore landed:

```bash
curl -s https://<your-render-host>/api/health
# expect: "status":"ok" and "last_bhavcopy_date" inside the seeded range
```

`seed_demo.dump` and `seed.dump` are both gitignored. Never commit either.

## Redeploy

Push to the connected branch, or **Manual Deploy** in the Render dashboard.
Migrations are idempotent, so a redeploy against an already-seeded Neon
database is a schema no-op, not a re-seed.

## Rollback

Render keeps prior deploys under the service's **Events**/**Deploys** tab —
**Rollback to this deploy** on the last good one takes effect in under a
minute, no rebuild. If a last-minute change breaks the deploy at T−2 hours,
roll back first and diagnose after.

## Keep-warm

Render free sleeps a web service after 15 minutes idle; the next request pays
a cold start. An external pinger hitting `/api/health` every 10 minutes keeps
it warm — but running one continuously costs roughly 730 of the 750 free
instance-hours a month, leaving almost nothing for anything else on the
account. **Switch the pinger on the day before submission, not before.**
(UptimeRobot or a free cron-ping service both work; nothing in this repo runs
it, since it must not run from inside the service it's keeping warm.)

## Multiple reviewers, one demo login

There is one shared, unauthenticated demo identity (`demo_trader`). Without a
reset, the first reviewer to reorder or delete a watchlist symbol, or whose
browser advances the read cursor, would hand the next reviewer a degraded or
already-caught-up Brief instead of the populated one the demo is built to
show. `GET /api/me` resets `demo_trader`'s watchlist and cursor to the seeded
baseline (`DEMO_WATCHLIST_SYMBOLS`, `DEMO_CURSOR_WEEKS_BACK` in
`app/api/core.py`) every time it's called with that identity — which, because
the frontend fetches `/api/me` once per tab (`staleTime: Infinity`), happens
on every fresh visit or hard refresh and not on ordinary in-app navigation. A
distinct caller-chosen identity (`X-Demo-User: someone-else`) is never reset;
that path exists for local testing, not for reviewers.

## Expected degraded state

Two things are expected not to work from a cloud host, and the app is designed
for both:

- **NSE blocks datacenter IPs.** Announcement polling and bhavcopy downloads may
  return 403. The circuit breaker (task 2.6) absorbs it and `/api/health`
  reports `nse_breaker_state`. Because the database is pre-seeded, the demo is
  unaffected — nothing in the request path re-ingests anything.
- **No broker credentials.** `feed_state` is `CLOSED`/`NO_DATA`, prices render
  as final exchange data and the UI says so in plain English.

Neither should look like a broken deploy. If either renders as a spinner or a
blank table, that is a bug, not a degradation.
