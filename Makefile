# Smart Market Watchlist — docs/BUILD_SPEC.md §4.1.
#
# `make seed` (Task 14.2) is the offline path: everything it runs reads only
# from data/cache/ and the database, no network. The individual targets above
# it are its building blocks, useful on their own when iterating on one stage.

PY := python
BACKFILL := $(PY) backend/scripts/backfill.py
# The ingest modules are packages under backend/, so they run with backend/ on
# the path rather than as scripts.
BACKEND := PYTHONPATH=backend $(PY) -m

.PHONY: help up down logs backfill backfill-verify symbols symbols-verify calendar calendar-verify actions actions-verify verify-actions infer-actions coverage api env seed pipeline

help:
	@echo "up              start postgres and redis"
	@echo "down            stop them, keeping the postgres volume"
	@echo "logs            follow the infrastructure logs"
	@echo "backfill        download 12 months of bhavcopy + delivery files"
	@echo "backfill-verify re-check the cache offline, no network"
	@echo "symbols         build the symbol master from NSE reference data"
	@echo "symbols-verify  rebuild it from the cached snapshot, no network"
	@echo "calendar        build the trading calendar: history + 90 days forward"
	@echo "calendar-verify rebuild it from the cached snapshot, no network"
	@echo "actions         ingest corporate actions and parse the purpose strings"
	@echo "actions-verify  re-parse from the cached snapshot, no network"
	@echo "verify-actions  check parsed CA factors against the ex-date price gap"
	@echo "infer-actions   recover factors for the unparsed tail from that gap"
	@echo "coverage        print + write parser coverage numbers into README.md"
	@echo "seed            offline: symbols, calendar, actions, bhavcopy/delivery/index,"
	@echo "                announcements, baselines and candidates, all from data/cache/"
	@echo "pipeline        recompute baselines and candidates only (DB already ingested)"
	@echo "api             run the full API"
	@echo "env             create .env from .env.example if it is absent"

up:
	docker compose up -d postgres redis

down:
	docker compose down

logs:
	docker compose logs -f postgres redis

backfill:
	$(BACKFILL) --months 12

backfill-verify:
	$(BACKFILL) --months 12 --from-cache-only

symbols:
	$(BACKEND) app.ingest.symbol_master

symbols-verify:
	$(BACKEND) app.ingest.symbol_master --from-cache-only

calendar:
	$(BACKEND) app.ingest.calendar

calendar-verify:
	$(BACKEND) app.ingest.calendar --from-cache-only

actions:
	$(BACKEND) app.ingest.corporate_actions

actions-verify:
	$(BACKEND) app.ingest.corporate_actions --from-cache-only

verify-actions:
	$(BACKEND) app.ingest.ca_verify --history

infer-actions:
	$(BACKEND) app.ingest.ca_infer --history

coverage:
	$(BACKEND) app.ingest.coverage

seed:
	$(PY) backend/scripts/seed.py

pipeline:
	$(PY) backend/scripts/run_full_pipeline.py

api:
	cd backend && $(PY) -m uvicorn app.main:app --reload

env:
	@test -f .env || cp .env.example .env
	@echo ".env is present"
