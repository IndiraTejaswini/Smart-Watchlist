# Smart Market Watchlist — single-service production image.
#
# One container serves both halves: FastAPI answers /api and /ws, and the same
# process serves the built SPA with an index.html fallback (§19.3, task 9.7).
# Deploying the frontend separately would buy nothing and cost CORS, a second
# deploy target, an API-base-URL to configure and a half-up failure mode.

# ─── Stage 1: build the SPA ─────────────────────────────────────────────────
FROM node:20-slim AS web
WORKDIR /web

# Dependencies first, so a source-only change does not reinstall them.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# VITE_USE_MOCK must be false in the image. frontend/.env.production sets it,
# and this restates it so the build cannot silently inherit a mock transport
# from a stray .env — the mock renders a convincing but fabricated Brief.
ENV VITE_USE_MOCK=false
ENV VITE_API_BASE=/api
RUN npm run build && test -f dist/index.html

# ─── Stage 2: the runtime ───────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# curl is the healthcheck; libpq5 is not strictly needed by psycopg[binary]
# but costs little and makes psql-family tooling work if we exec into the box.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist ./static

# The SPA lives at /app/static in the image, not at the repo-relative
# frontend/dist that app.config defaults to for local development.
ENV STATIC_DIST_PATH=/app/static \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:${PORT:-8000}/api/health || exit 1

# Migrations run at boot so a fresh database reaches head before the first
# request. They are idempotent, so a redeploy against a seeded database is a
# no-op rather than a re-seed.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
