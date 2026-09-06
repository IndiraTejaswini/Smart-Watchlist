# BUILD_PLAN.md
## Smart Market Watchlist — ordered execution plan
### Revision 2 · Companion to `ARCHITECTURE.md`. Read that first.
### Stack: Python/FastAPI backend · **React + Vite + JavaScript** frontend · web only · English only

---

## PART A — OPERATING RULES FOR THE CODING AGENT

> Copy Part A verbatim into `.github/copilot-instructions.md` before starting.
> The agent reads that file on every request. These rules are not optional.

### A1. The prime directives

**R1 — Constants are law.**
Every numeric threshold, weight, window length, multiplier, and timeout used
anywhere in this codebase MUST be imported from `backend/app/constants.py`.
- You may NOT write a bare number into business logic. Not `20`, not `0.05`,
  not `300`.
- If you need a number that does not exist in `constants.py`, **STOP. Do not
  invent one. Ask the human and wait.**
- Values marked `[REGULATORY]` in `ARCHITECTURE.md` §21 must never be altered,
  refactored, "simplified", or moved.
- Exception: array indices, `0`, `1`, and HTTP status codes.

**R2 — The signal engine is pure.**
`compute_signals()` and everything it calls must never touch `datetime.now()`,
`date.today()`, `time.time()`, `random`, `uuid4`, the network, the database, or
`os.environ`. All inputs arrive in the `FactBundle` parameter. A test asserts
this by monkeypatching those symbols to raise. Do not disable it.

**R3 — Never invent market-data semantics.**
If you are unsure whether a field means "traded quantity" or "deliverable
quantity", whether a timestamp is IST or UTC, or whether a price is adjusted or
as-traded — **STOP and ask.** Do not guess. A wrong guess here produces numbers
that look plausible and are wrong, which is the worst possible outcome.

**R4 — Every fact row carries provenance.**
`source` and `ingested_at` on every ingested row. `computed_at` on every derived
row. No exceptions, no "we'll add it later".

**R5 — Fail visibly.**
Never render a stale price as though it were live. Never substitute a default for
missing data without a flag. Never swallow an exception in an ingest path. If
data is missing, the UI says so in plain English.

**R6 — Suppression fails safe.**
When you cannot determine whether something is a corporate-action artefact,
suppress it. Suppressing a real signal is a minor loss. Showing a −50% crash that
never happened is catastrophic.

**R7 — English only.**
All user-facing strings are English literals. No i18n library, no locale files,
no `t()` or `useTranslation()` wrappers, no language switcher. Do not add these
"for future flexibility".

**R8 — Web only, React + JavaScript only.**
- No React Native, Expo, Capacitor, or any mobile-app scaffolding.
- **No Next.js.** Plain React 18 SPA on Vite with React Router v6.
- **No TypeScript.** No `.ts` or `.tsx` files, no `tsconfig.json`, no type
  annotations. Use `.js` / `.jsx` with JSDoc `@typedef` blocks in
  `src/lib/types.js` for editor completion.
- Runtime validation with Zod is permitted **at the API boundary only**
  (`src/lib/schemas.js`). Do not use Zod for internal component state.

**R9 — Turnover, never share volume, in any statistic.**
Share volume may be displayed. It may never be fed into a z-score, a baseline,
or a liquidity threshold. Turnover in rupees is split-invariant; share volume is
not. If you find yourself writing `volume / factor`, stop — you are on the wrong
path.

**R10 — Corporate actions: price factor is splits and bonuses only.**
Cash dividends leave `price_factor = 1.0` and populate `tr_factor`. Do not
dividend-adjust the price series. See `ARCHITECTURE.md` §5.3.

**R11 — Tests before implementation for the numerical core.**
For `canonical.py`, `mpm.py`, `factors.py`, `abnormality.py`, `classify.py`,
`ranker.py`: write the test file with hand-computed expected values FIRST, then
implement until green. These are where silent wrongness lives.

**R12 — No banned copy, at build time *and* at runtime.**
User-facing text may never contain `buy`, `sell`, `should`, `consider`,
`opportunity`, `target price`, `undervalued`, `overvalued`, `bullish`,
`bearish`, `act now`, `don't miss`, `hurry`, or an exclamation mark.

Two enforcement points, because they cover different things:
- **Build time:** a lint test greps the copy modules and fails the build. This
  covers templates.
- **Runtime:** any text produced by a model (Task 8.6) is checked against the
  same list **before it is stored or rendered**, and rejected to the template on
  a hit. The lint cannot see generated text, so without this the one place the
  product can emit a recommendation is the one place nothing is checking.

The banned list lives in `constants.py` and both checks import it. There is one
list, not two.

**R13 — Never call this a rules engine.**
In the README, the UI, code comments and commit messages, the scoring path is
described as a **transparent statistical model** or **event-study methodology**,
never as "rules", "rule-based", "heuristics" or "if-then logic". The words shape
how a reader estimates the work. What is in there — OLS market model, CAR/SCAR,
logit z-scores, winsorisation, variance floors — is quantitative modelling, and
the write-up must say so accurately.

### A2. How to work

- **One task at a time.** Complete it, run its acceptance test, report, move on.
  Do not batch tasks.
- **Read before you write.** Before modifying a module, read its "Why" section in
  `ARCHITECTURE.md`. If your change contradicts the Why, say so instead of doing
  it.
- **Small commits.** `feat(P3.2): compute cumulative adjustment factors`
- **Report format after every task:**
  ```
  Task: P3.2
  Files changed: backend/app/pipeline/factors.py, backend/tests/test_factors.py
  Acceptance test: PASS (3/3)
  Constants used: none new
  Open questions: none
  ```
- **When blocked, stop and ask.** Do not produce a placeholder, a `TODO`, a
  `pass`, or a mock and continue. A blocked task reported honestly beats a fake
  one completed.

### A3. Definition of done for any task

1. Code written, imports resolve
2. Acceptance test passes
3. `ruff check` and `mypy` clean on changed Python files;
   `eslint` clean on changed JS files
4. No new bare numeric literals in business logic
5. No new user-facing string containing a banned word
6. No `.ts` / `.tsx` file created; no i18n import added
7. Provenance columns populated on any new write path

---

## PART B — PHASED TASK LIST

**P0** = the demo dies without it · **P1** = strongly differentiating ·
**P2** = only if ahead of schedule.
Tasks marked **[R2]** are new in revision 2, arising from the review ledger.

---

### PHASE 0 — Foundations · P0

Do the first three tasks in the first hour. Task 0.1 runs in the background while
you do everything else.

**0.1 — Start the data download immediately.** `P0`
Write `nse_client.py`: homepage warmup, cookie refresh on 401/403, one constant
realistic browser header set, exponential backoff with jitter, 30s timeout,
on-disk cache at `data/cache/{source}/{date}/` **with a SHA-256 sidecar** `[R2]`,
and a `--from-cache-only` flag. Launch a 12-month backfill of bhavcopy +
delivery files in the background.
- *Accept:* `data/cache/bhavcopy/` fills while you continue; each file has a
  `.sha256` sidecar.

**0.2 — Resolve broker API access.** `P0`
Register for a broker developer account (Kite Connect / Upstox / Dhan /
Angel One / ICICI Breeze).
- *Accept:* credentials in `.env`, or a written decision to ship with the
  polling fallback.
- *Why now:* activation can take 24 hours. The `QuoteSource` abstraction means
  this is a config change either way.

**0.3 — Repo skeleton, docker-compose, `constants.py`.** `P0`
Directory tree from `ARCHITECTURE.md` §4.1. `constants.py` containing §21
**verbatim**. Postgres + Redis up.
- *Accept:* `docker compose up` starts postgres and redis;
  `python -c "from app.constants import MPM_TIER_THRESHOLDS; print(...)"` works.

**0.4 — `canonical.py` + determinism test.** `P0` `[R2]`
Canonical JSON per §4.2: sorted keys, floats rounded to `CANONICAL_FLOAT_DP`,
numpy/Decimal coerced, datetimes ISO-8601 UTC with microseconds truncated, sets
sorted, NaN/Infinity raise.
- *Accept:* serialising the same nested structure in two separate Python
  processes produces byte-identical output, twice.
- *Why P0:* `inputs_hash` underpins invariant N1. If serialisation is unstable,
  N1 is a lie and the explain endpoint cannot be trusted.

**0.5 — Alembic migration 001: full schema.** `P0`
Every table in `ARCHITECTURE.md` §5, §6, §7, §9, §12, §20 — including
`symbol_aliases`, `symbol_master_snapshots`, `symbol_adjustment_factors`,
`ingest_quarantine`, `symbol_liquidity_state` `[R2]`.
- *Accept:* `alembic upgrade head` and `alembic downgrade base` both succeed.
- *Note:* `daily_bars` PK is `(symbol, date)` — **not** `(symbol, date, series)`.

**0.6 — `timeutil.py`: IST helpers + tests.** `P0`
`ist_trading_date(ts)`, `session_phase(ts)`, `previous_trading_day(d)`,
`session_close(d)`, `sessions_between(a, b)`.
- *Accept:* `2026-09-04T10:00:00Z` → trading date `2026-09-04`;
  `2026-09-04T19:00:00Z` → `2026-09-05`.

---

### PHASE 1 — Reference data · P0

**1.1 — Symbol master with surrogate key and fallback chain.** `P0` `[R2]`
Parse `EQUITY_L.csv` → `instruments` with `instrument_id BIGSERIAL`. Sector
resolution chain: primary file → index constituent map → vendor metadata →
`'UNASSIGNED'`. Record `sector_source`. Populate `symbol_aliases` for any known
renames.
- *Accept:* ≥1,800 rows; **zero NULL sectors**; `swl_sector_coverage_ratio` ≥ 0.99
  for active symbols; `sector_source` distribution logged.

**1.2 — Trading calendar as a session state machine.** `P0` `[R2]`
All columns from §5.2 including `pre_open_start/end`, `regular_open/close`,
`post_close_end`, `session_type`. Populate the history window plus 90 days
forward.
- *Accept:* `previous_trading_day` crosses a holiday correctly; a Muhurat
  Saturday has `session_type='MUHURAT'`; `session_phase()` returns `PRE_OPEN`
  at 09:05 on a trading day.

**1.3 — Corporate actions ingest + parser + PRI/TRI split.** `P0` `[R2]`
Parse `purpose_raw` → `action_type`, `price_factor` (splits/bonuses only),
`tr_factor` (incl. dividends). Composite detection: multiple action keywords or
` AND ` between ratio clauses → compose in order
`consolidation/split → bonus → rights → dividend`, or mark `COMPOSITE` +
`UNPARSED` and suppress.
- *Accept:* a fixture of 30 real `purpose_raw` strings parses with ≥90%
  correctly typed; **every cash dividend has `price_factor = 1.0`**; every
  unparsed row is recorded, none silently dropped.

**1.4 — Empirical CA factor verification (against `tr_factor`).** `P1` `[R2]`
Morning job: for yesterday's ex-dates compare `prev_adj_close × price_factor`
against `open` on the ex-date. Within `CA_VERIFY_TOLERANCE` → `VERIFIED`, else
`DISCREPANCY` + suppress.
- *Accept:* running over the backfilled history classifies ≥85% of parsed actions
  as `VERIFIED`; every `DISCREPANCY` is listed at `/api/eval/unparsed-actions`.
- *Why:* this is the substitute for a second vendor feed, and it catches parser
  errors using data already on disk.

---

**1.5 — CA factor inference for the unparsed tail.** `P1`
Where a `corporate_actions` row exists but the string did not parse, snap the
observed ex-date gap to `CA_CLEAN_FACTORS` within `CA_INFER_SNAP_TOLERANCE` and
set `verification = 'INFERRED'`. **Only when a scheduled action exists for that
date** — never infer an action from a price gap alone.
- *Accept:* a deliberately mangled purpose string on a known 1:1 bonus recovers
  `price_factor = 0.5` with `verification = 'INFERRED'`.
- *Accept:* a −48% single-day fall on a date with **no** corporate action stays
  unmodified and produces a normal scored signal, not an inferred bonus.

**1.6 — Parser coverage report.** `P1`
`python -m app.ingest.coverage` prints, over the ingested history: CA strings
parsed / inferred / unparsed / discrepant, and announcements resolved by `desc`
/ by regex / as `OTHER`. Write the output into the README.
- *Accept:* the report runs and the four CA buckets sum to the row count.
- *Why:* "our parser covers 94% and the other 6% are suppressed, here is the
  list" is a far stronger answer to a jury than silence, and it tells you during
  the build whether the parser is good enough to stop working on.

### PHASE 2 — EOD ingest · P0

**2.1 — Bhavcopy ingest: idempotent, hashed, validated, quarantined.** `P0` `[R2]`
File hash check before parsing (skip if already ingested). Row validation.
Rejected rows → `ingest_quarantine` with reason. Two-sided count check: active
symbol floor **and** rolling-median deviation, both suppressed on
`MUHURAT`/`HALF_DAY`. One transaction per file.
- *Accept:* re-running the same date produces identical counts and no duplicates;
  a corrupted fixture aborts without committing and lands rows in quarantine; a
  hash-matched re-run reports `SKIPPED_CACHED`.

**2.2 — Delivery ingest.** `P0`
- *Accept:* `deliverable_qty <= traded_qty` for 100% of committed rows.

**2.3 — Index EOD ingest.** `P0`

**2.4 — Index 09:30 snapshot: capture + priority-ordered backfill.** `P0` `[R2]`
Scheduled at 09:30:05 IST. Backfill in strict order: live capture → broker
1-minute candle → index open with `ESTIMATED_FROM_OPEN` and a quality flag.
- *Accept:* every trading date in the window has a row; the count of
  `ESTIMATED_FROM_OPEN` rows is reported in `/api/health`.
- *Why P0:* the MPM index adjustment is frozen at 09:30 and cannot be
  reconstructed from EOD data. Without it, Layer 0 is wrong.

**2.5 — Retry cap, escalation, calendar gating.** `P1` `[R2]`
Four polls; escalate at 20:30 by marking `ESCALATED`, pausing baseline and
restatement jobs, and raising the `/api/market/status` banner. Skip non-trading
days silently.
- *Accept:* simulating four failures produces `ESCALATED`, and the baseline job
  refuses to run for that date.

**2.6 — NSE circuit breaker + `curl_cffi` fallback tier.** `P1` `[R2]`
Three consecutive 403/429 → open the breaker for `NSE_BREAKER_COOLDOWN_S`, then
half-open with a single probe. Tier 3 falls back to `curl_cffi` Chrome
impersonation.
- *Accept:* a mocked 403 sequence opens the breaker instead of exhausting all
  five retries; `nse_breaker_state` is exported.

**2.7 — Backfill runner.** `P0`
`python -m app.ingest.backfill --from 2025-09-01 --to 2026-09-04`
- *Accept:* completes for 12 months; `ingest_runs` shows zero failed dates or a
  documented list of holidays with no file.

**2.8 — Announcements ingest.** `P0`
Poll the NSE corporate-announcements endpoint every
`ANNOUNCEMENT_POLL_SECONDS` and write `announcements` rows: `symbol`,
`filed_at`, `subject`, `category`, `para_ref`, `attachment_url`, `raw_json`.
Dedup on a SHA-256 content hash over `(symbol, subject, filed_at)` — the
exchange re-publishes identical filings with fresh timestamps. Also write a
one-shot historical backfill over the same window as the bhavcopy backfill, so
the eval harness has filings to link against.
- *Accept:* the backfill produces a non-empty `announcements` table covering the
  full history window, with zero duplicate content hashes.
- *Accept:* re-running the poller inside one window inserts no new rows.
- *Accept:* after backfill, `SELECT raw_json->>'desc', count(*) GROUP BY 1
  ORDER BY 2 DESC` is run and the top ~30 values are hand-mapped into
  `CATEGORY_FROM_DESC`. The subject regex is the fallback, not the primary path.
- *Why this is P0 and sits here, not in Phase 6:* Task 6.4 links filings to price
  moves and Task 5.4 treats a material filing as a candidate even with no price
  move. Both read this table. Without it, `EXPLAINED` never fires, which removes
  the single strongest differentiator in the product.

---

### PHASE 3 — Adjustment factors · P0 · **WRITE TESTS FIRST**

**3.1 — Golden corporate-action fixtures.** `P0`
Three verified real events: a 1:1 bonus, a face-value split, a large special
dividend. Hard-code expected as-traded and adjusted values plus the source URL.
- *Accept:* fixture file committed with citations.

**3.2 — `symbol_adjustment_factors` table + `v_adjusted_bars` view.** `P0` `[R2]`
Compute `cum_price_factor` and `cum_tr_factor` per symbol-date. Adjust at read
time through the view. **Do not rewrite `adjusted_bars` rows.**
- *Accept:* for all three golden fixtures, as-traded return ≈ −50% / −80% /
  −(div/price) and adjusted return ≈ 0% within 0.5pp for bonus and split;
  **the dividend fixture shows `cum_price_factor = 1.0`** and its adjusted
  return still reflects the drop (PRI is correct here).
- *Accept:* inserting a new CA rewrites only that symbol's factor rows.

**3.3 — Return-function guard.** `P1`
Naming convention plus a lint: return-computing functions accept `adj_*`
parameters only.
- *Accept:* a test greps `abnormality.py` and fails if `close` (unadjusted) is
  passed to any return function.

**3.4 — Live tick ex-date normalisation.** `P2` `[R2]`
Stamp live ticks with today's `cum_price_factor` so the UI renders a correct
previous-close comparison on an ex-date.
- *Accept:* on a simulated ex-date, the watchlist row shows the adjusted
  comparison, not −50%.

---

### PHASE 4 — Baselines · P0

**4.1 — Vectorised market model.** `P0` `[R2]`
Wide returns frame, rolling covariance/variance via pandas, `beta = cov/var`.
120-session window, 5-session gap, 1/99 winsorization, beta clamp, resid_sd
floor, `DEGRADED` path when `n_obs < 60`.
- *Accept:* a large cap has plausible `r2` and `n_obs = 120`; a 40-session symbol
  gets `quality='DEGRADED'` with `beta = 1.0`.
- *Accept:* full-universe, 12-month backfill completes in **under 15 minutes**.
  If it does not, you are looping per symbol — vectorise.

**4.2 — Turnover baseline.** `P0` `[R2]`
`ln(1 + turnover)` over 20 sessions. **Not share volume.**
- *Accept:* a grep confirms `volume` appears in no baseline computation.

**4.3 — Delivery baseline with logit transform.** `P0` `[R2]`
`delivery_logit = ln((p+eps)/(1-p+eps))`, mean and sd over 20 sessions,
zero-volume days excluded.
- *Accept:* a symbol at 95% delivery and one at 50% produce z-scores whose
  relative magnitudes are sane; raw `delivery_pct` is still stored for display.

**4.4 — Extremes and ADV.** `P0`
52-week high/low from adjusted closes over 252 sessions; `adv_20d` in rupees.
- *Accept:* every symbol-date with ≥20 prior sessions has non-null baselines.

---

### PHASE 5 — Signal engine · P0 · **THE CORE. TESTS FIRST.**

**5.1 — `FactBundle`, cold/hot loader, completeness, purity test.** `P0` `[R2]`
Frozen dataclass with explicit optional fields and a `completeness` frozenset.
Cold half cached in Redis at `factbundle:cold:{symbol}:{date}`, TTL 24h, purged
on EOD ingest. A separate loader touches the DB.
- *Accept:* purity test passes (monkeypatch `datetime.now`, `random`, `socket`
  to raise).
- *Accept:* a newly listed symbol with no baseline loads without raising and
  yields `completeness` missing `baseline`.

**5.2 — MPM gate.** `P0`
Both close-to-close and the intraday variant. Intraday uses the **base** tier
threshold, not the index-adjusted one.
- *Accept:* hand-computed table test — ₹95 stock +5.1% triggers; ₹95 +4.9% does
  not; ₹150 +4.2% with Nifty +1.5% same direction does not (threshold 5.5%);
  ₹150 +4.2% with Nifty −1.5% does (threshold stays 4.0%); ₹500 at the upper
  band triggers regardless; a stock that swung 6% intraday and closed flat
  triggers `intraday_triggered`.

**5.3 — Abnormality layer.** `P0` `[R2]`
AR, SAR, CAR, SCAR, `turnover_z`, `delivery_z` (logit-based), 52-week extremes.
`sessions_between` from the calendar for the `sqrt(n)`.
- *Accept:* on a synthetic series with known alpha/beta/sigma, SAR recovers the
  injected shock within 0.05; `SCAR = CAR/(sigma*sqrt(n))` verified by hand for
  n=3 **across a holiday** so the session count is exercised.

**5.4 — Candidate generation + eight signal families.** `P0`
Including the "material filing with no price move is still a candidate" clause.
- *Accept:* a fixture day produces candidates in all eight families at least once
  across the universe.

**5.5 — Refractory window with sign-flip reset.** `P1` `[R2]`
- *Accept:* a three-day slide produces one item; a fourth day 60% larger
  re-surfaces; **a −4% morning followed by a +4% afternoon produces two items,
  not one.**

**5.6 — `inputs_hash` + cross-process determinism.** `P0`
- *Accept:* computing the same symbol-date in two separate processes yields
  identical `inputs_hash` and identical scores.

---

### PHASE 6 — Classification and suppression · P0

**6.1 — CORPORATE_ACTION suppression, notice, ex-date open pause.** `P0` `[R2]`
Window suppression, `CORP_ACTION_NOTICE` with before/after prices, and a 15-minute
pause from `regular_open` on the ex-date.
- *Accept:* replaying the three golden CA dates produces **zero** scored signals
  and exactly one notice each with correct before/after prices.
- *Accept:* a simulated 09:20 tick on an ex-date produces no signal.
- *This is the demo's money shot. It must be perfect.*

**6.2 — MARKET_WIDE attribution + rollup.** `P0`
Ratio test plus the `MARKET_SAR_CEILING` high-beta guard.
- *Accept:* on a day when Nifty fell >2%, ≥60% of high-beta large caps classify
  MARKET_WIDE and collapse into one rollup line; a β=2.5 stock with `SAR = 2.8`
  does **not** classify MARKET_WIDE.

**6.3 — SECTOR_WIDE grouping.** `P1`
- *Accept:* on a known sector-wide day, ≥3 peers group into one line; a symbol
  with `sector='UNASSIGNED'` never classifies SECTOR_WIDE.

**6.4 — EXPLAINED linking: regex, window, multi-filing.** `P0` `[R2]`
Word-boundary compiled patterns. Calendar-driven window
`[session_close(prev_trading_day(D)), session_close(D) + 180min]`.
`linked_announcement_ids` array; highest-priority category wins.
- *Accept:* a results filing at 19:00 on D−1 links to D, not D−1.
- *Accept:* a Friday 19:00 filing links to Tuesday when Monday is a holiday.
- *Accept:* the string `"Download the attachment"` does **not** match ORDER_WIN;
  `"Unconditional undertaking"` does **not** match FUND_RAISE.
- *Accept:* three filings within 10 minutes produce one signal with three linked
  IDs.

**6.5 — Liquidity hysteresis.** `P1` `[R2]`
Two thresholds with state in `symbol_liquidity_state`.
- *Accept:* a symbol oscillating around ₹1 crore ADV does not flip state; it
  flips only on crossing ₹80 lakh down or ₹1.2 crore up.

---

### PHASE 7 — Cursor and watchlist state · P0

**7.1 — Read cursor with `GREATEST` merge.** `P0`
- *Accept:* two concurrent out-of-order updates converge to the max; the test
  runs both orderings and asserts equality.

**7.2 — Delivered vs acknowledged split.** `P1`
- *Accept:* serving a Brief advances `seen_through_ts` only; explicit ack
  advances `acknowledged_through_ts`; the Brief renders against the latter.

**7.3 — Watchlist CRUD, fractional indexing, idempotency in Redis.** `P0` `[R2]`
`Idempotency-Key` responses cached at `idempotency:{user}:{key}` with a 24h TTL.
- *Accept:* inserting between two items generates a strictly-between key with no
  other rows rewritten; replaying a key returns the original response and applies
  nothing; the key disappears after TTL.

**7.4 — Fractional index rebalancing.** `P2` `[R2]`
Background rebalance when any `position_key` exceeds 32 characters.
- *Accept:* 50 repeated insertions at the same position trigger exactly one
  rebalance and preserve order.

**7.5 — Optimistic concurrency (`If-Match` / 409).** `P2`

---

### PHASE 8 — Digest and ranking · P0

**8.1 — Ranker.** `P0`
All weights and multipliers from `constants.py`; `PERSONAL_CAP` enforced;
recency decay in trading sessions.
- *Accept:* hand-computed score for one fixture item matches to 4dp.
- *Accept:* a held + pinned + recently-added + level-crossed item is capped at
  exactly 2.0, not 3.9.

**8.2 — Digest builder + the hard cap.** `P0`
All ten assembly steps.
- *Accept:* a property test over 200 randomised fixture states asserts
  `len(scored_items) <= BRIEF_MAX_ITEMS` **always**. This is invariant N3.

**8.3 — Copy templates.** `P0`
Four-part structure; all templates in `digest/copy.py`.
- *Accept:* the banned-word lint passes; every template renders with as-of time
  and provisional status.

**8.4 — `budget` block.** `P1`
- *Accept:* the counts sum correctly and are persisted to `digest_deliveries`.

**8.5 — `/api/brief/explain/{id}`.** `P1`
Every intermediate value, the classification decision path, every multiplier, the
`completeness` set, the `inputs_hash`.
- *Accept:* the response lets you recompute the final score by hand from the
  values shown.
- *This is invariant N1 and the answer to "why is this ranked second?" in the
  interview.*

**8.6 — Filing summariser (bounded LLM).** `P1`
One sentence for the `cause` line, generated from an already-linked filing.
Input is subject, category and body text **only** — no prices, no z-scores, no
rank. Runs after ranking; cannot influence it. Store the prompt, model version
and source filing with every sentence.

Validation runs **before** the sentence is stored or rendered, in this order —
generate → validate → store with the validation result → render, or fall back to
the template. A sentence that fails any gate is never persisted as user-facing
copy.

- *Accept:* output containing a digit not present in the input is rejected and
  the template is used.
- *Accept:* output containing any word from the R12 banned list is rejected and
  the template is used. Test with a filing about a **buyback** — the word most
  likely to pull a model toward recommendation language — and assert the Brief
  never renders "should", "bullish" or "opportunity".
- *Accept:* output longer than `SUMMARY_MAX_CHARS` is rejected.
- *Accept:* killing the model endpoint leaves the Brief fully functional on
  templates, with no error surfaced to the user.
- *Accept:* generated sentences render with a visible "summarised from the
  filing" marker.
- *Why P1 not P2:* this is the most-read line in the product and the one place
  generation genuinely beats string formatting. It is also the answer to "did you
  use any ML at all" — a scoped, audited, fails-safe use, sitting outside the
  scoring path by construction.

---

### PHASE 9 — REST API · P0

**9.1** App factory, settings, DB session, RFC 7807 errors. `P0`
**9.2** Demo auth. `P0`
**9.3** Watchlist endpoints. `P0`
**9.4** Brief endpoints. `P0`
**9.5** Symbol endpoints. `P0`
**9.6** `/api/market/status`, `/api/health`, `/api/metrics`. `P1`
**9.7** Serve the Vite build via `StaticFiles` with SPA fallback for unmatched
non-`/api` paths. `P0` `[R2]`
- *Phase accept:* OpenAPI renders at `/docs`; an integration test walks
  create-watchlist → add-symbols → set-cursor → get-brief; a deep link to
  `/symbol/RELIANCE` returns `index.html` on hard refresh.

---

**9.8** `GET /api/quotes?symbols=A,B,C` — the polling fallback the frontend uses
when the WebSocket is unavailable or cut. Returns the same per-symbol payload as
a WS delta, freshness state included. `P0` — Task 10.2 is on the cut list, so
this path must exist independently of it.

### PHASE 10 — Live quotes and realtime · P1

**10.1 — `QuoteSource` protocol + `PollingSource`.** `P0`
Abstraction and fallback **before** the broker adapter.
- *Accept:* polling source streams ticks for 20 symbols at 5s intervals.

**10.2 — `BrokerWebSocketSource`.** `P1`
- *Accept:* killing the connection reconnects within 10s and resubscribes.

**10.3 — Freshness state machine with benchmark anchor.** `P0` `[R2]`
Nine states, evaluation order from §14.2. **Always subscribe to the benchmark
anchor** regardless of the user's watchlist.
- *Accept:* a table-driven test covering all nine states.
- *Accept:* a watchlist of 20 illiquid symbols all silent for 90s while the
  benchmark anchor keeps ticking returns `STALE_THIN` per symbol and **not**
  `HALTED_MARKET`.
- *Accept:* silent symbols **and** a silent anchor return `HALTED_MARKET`.
- *Why P0 despite realtime being P1:* the machine also labels EOD data
  (`CLOSED`, stale bhavcopy).

**10.4 — Redis Streams tick transport + `StreamConsumer` protocol.** `P1`

**10.5 — WS gateway: conflation, bounded queue, backpressure.** `P1`
- *Accept:* 50 connections × 60 symbols caps message rate near
  `1/CONFLATION_INTERVAL_MS` per connection; a deliberately slow client is
  disconnected after 30s without affecting others.

**10.6 — Snapshot, delta, sequence, explicit `resync`.** `P1` `[R2]`
- *Accept:* dropping three deltas causes the client to detect the gap, discard
  the next delta, enter `RE_SYNCING`, send `resync`, and recover to a consistent
  snapshot.

---

### PHASE 11 — Restatement · P1

**11.1** Provisional intraday signals (`delivery_z = NULL`). `P1`
**11.2** EOD recompute with revision and supersede. `P1`
**11.3** "Revised after final exchange data" surfacing. `P1`
**11.4 — Redis cache purge on `BHAVCOPY_LANDED`.** `P1` `[R2]`
- *Accept:* an intraday signal cached in a Brief response is evicted the moment
  EOD ingest completes; the next request returns revision 2 with
  `was_restated = true`. **Without this task, restatement is invisible for up to
  60 seconds — that was a real bug in revision 1.**

---

### PHASE 12 — Frontend (React + Vite + JavaScript) · P0

**12.1 — Vite scaffold, tokens, fonts, type scale.** `P0` `[R2]`
`npm create vite@latest frontend -- --template react` (**not** react-ts).
Tailwind v4 via the Vite plugin. Tokens from §17.2 into the theme.
`@fontsource/newsreader` + `@fontsource/public-sans` self-hosted. Global `.tnum`
class with `font-variant-numeric: tabular-nums lining-nums`.
- *Accept:* a token page renders every colour and type role; digits do not shift
  width as values change; no `.ts`/`.tsx` file exists anywhere.

**12.2 — API client, Zod boundary schemas, JSDoc types, Query persistence.** `P0` `[R2]`
`lib/api.js` fetch wrapper; `lib/schemas.js` Zod schemas for `BriefResponse` and
the quote payload; `lib/types.js` JSDoc typedefs; TanStack Query with
`persistQueryClient` on IndexedDB; pending-mutation queue replaying original
idempotency keys.
- *Accept:* a malformed Brief payload throws a clear, named validation error in
  dev; the app still renders a degraded state in prod rather than a white screen.

**12.3 — React Router + app shell.** `P0`
Routes from §17.4, `<Navigate>` from `/`, a `NotFound` route.

**12.4 — `/brief`.** `P0`
Single 66ch column, hairline rules, **no cards**, cursor sentence as hero, quiet
line at full item size, budget line at the bottom, skeleton matching the loaded
layout.
- *Accept:* renders correctly for a cursor 3 weeks back and for one 10 minutes
  back (the empty state, not a broken page); no content shift between skeleton
  and loaded.

**12.5 — Cursor picker.** `P0`
Sets "when did I last look" to any point in retention; items restack with the
single 220ms animation.
- *Accept:* moving the cursor changes Brief contents; `prefers-reduced-motion`
  disables the animation.

**12.6 — `/watchlist/:id` live table.** `P0` `[R2]`
Virtualised via `@tanstack/react-virtual` with pre-allocated row heights.
Red/green direction (this surface only). Freshness dot per row.
Drag-to-reorder. Viewport-scoped WS subscription debounced 200ms.
`contain: content` on rows. `React.memo` comparator firing only on
`ltp`/`chp`/`state`. Zustand selector subscriptions, never whole-store.
- *Accept:* 250 rows scroll smoothly; only visible rows are subscribed;
  React DevTools Profiler shows Brief prose components **not** re-rendering when
  quotes tick; `FEED_DOWN` dims all prices with a plain-English strip.

**12.7 — `/symbol/:symbol`.** `P1`
`lightweight-charts`, a "what we know" panel showing every baseline with its
window and quality flag, signal history, linked filings.

**12.8 — `/eval`.** `P1`
Stepped funnel chart, three suppression case studies side by side, the
continuation table.
- *This page exists for the jury. Make it the best-looking page in the app.*

**12.9 — `/settings`.** `P2`
Cursor controls, the cap (visible, explained as a safety control), and a
data-provenance panel listing every source with its last successful ingest time.

**12.10 — Empty, loading, error states everywhere.** `P0`
Per copy rules 7 and 8.
- *Accept:* every screen has a designed empty state; no spinner-only screens.

---

### PHASE 13 — Evaluation harness · P1 · **THE DIFFERENTIATOR**

**13.1** Replay runner: 200 symbols × 126 sessions. `P1`
**13.2** The funnel, exposed at `/api/eval/funnel`. `P1`
- *Accept:* each step is a strict subset of the previous — assert it.
**13.3** Three suppression case studies as fixtures. `P1`
**13.4** Continuation test: forward 5-session AR by classification. `P1`
- *Accept:* the table renders with n, mean, median, same-direction %. Report the
  result honestly whether or not it reproduces the expected asymmetry.
**13.5** Self-audit: five false positives with explanations, into the README. `P1`

---

### PHASE 14 — Docs, packaging, demo · P0

**14.1 — README.** `P0`
Must include a short **"the model we did not build"** subsection: the v2 learned
re-ranker design — label, position-bias correction, current score as a feature,
offline evaluation on the replay harness, regulatory floor kept outside the
model. Designing it credibly is worth more than shipping a bad version of it.
In order: the one-line thesis; the six decisions with evidence; the gap analysis;
the business case; **data provenance and limitations stated openly** (NSE only,
cash equity only, no BSE, PRI not TRI, turnover-not-volume caveat, no SSR);
considered-and-rejected (§23); the review ledger (§26); the failure-modes
catalogue; setup; references.

**14.2 — `make seed` for offline demo.** `P0`
Loads cached NSE files and runs the full pipeline with no network.
- *Accept:* tested on a clean container with networking disabled.

**14.3 — Deploy.** `P0`
- *Accept:* the deployed URL works in a fresh incognito browser; deep links
  survive hard refresh.

**14.4 — Demo video (90 seconds).** `P0` — script in Part D. Record twice.

**14.5 — Architecture diagram image.** `P1`

---

## PART C — CUT ORDER

```
NEVER CUT ─────────────────────────────────────────────────
  Canonical JSON + determinism (0.4, 5.6)
  Corporate action correctness (Phase 3, Task 6.1)
  MPM gate (5.2)
  Abnormality layer (5.3)
  Digest + hard cap (8.2)
  /brief + cursor picker (12.4, 12.5)
  README with evidence (14.1)
  Offline seed (14.2)

CUT LAST ──────────────────────────────────────────────────
  Announcements ingest + EXPLAINED linking (2.8, 6.4)
    ↑ these two are one unit. Cutting 2.8 silently disables 6.4.
  Eval funnel + suppression cases (13.2, 13.3)
  Explain endpoint (8.5)
  Market-wide rollup (6.2)
  Benchmark-anchored halt detection (10.3)

CUT IF NEEDED ─────────────────────────────────────────────
  Broker WebSocket adapter (10.2)  → ship PollingSource only
  Restatement pipeline (Phase 11)  → ship EOD-only signals
  Continuation test (13.4)
  Sector grouping (6.3)
  Symbol detail page (12.7)
  CA empirical verification (1.4)
  Filing summariser (8.6)  → templates already cover the cause line

CUT FIRST ─────────────────────────────────────────────────
  Settings page (12.9)
  Fractional index rebalancing (7.4)
  Optimistic concurrency (7.5)
  Live tick ex-date normalisation (3.4)
  Return-function guard (3.3)
```

**When time runs out: cut live streaming before you cut the signal engine.** A
polling watchlist with an excellent, honest, well-defended Brief beats a
beautiful real-time table with an arbitrary 5% threshold. The Brief is graded;
the socket is assumed.

**Hard feature freeze at T−8 hours.** After that: bug fixes on the demo path,
docs, video, deploy. Anything not working is deleted from the demo, not fixed.

---

## PART D — THE 90-SECOND DEMO SCRIPT

| Time | Show | Say |
|---|---|---|
| 0:00 | The live table, 15 red/green rows | "Here's a normal watchlist. Which of these deserves your next 30 seconds? You can't tell. Neither can any product shipping today." |
| 0:15 | Move the cursor to three weeks ago | "I last looked on the 12th." The Brief renders: 4 items plus "eleven others: nothing notable." |
| 0:30 | Read the top item | It names the move, says it's the largest three-day stock-specific move in 14 months, names the filing that caused it, and timestamps its own data. |
| 0:45 | Point at item 2 | "Unexplained. Turnover 3× normal, but delivery *below* its own average. Churn, not conviction — and that distinction is only possible because NSE publishes delivery data. That's why it ranks below the explained move." |
| 1:00 | The suppression case, side by side | "On this date a normal watchlist showed minus fifty percent. It was a 1:1 bonus. We showed nothing, and here's the log entry saying why." |
| 1:15 | The MPM circular | "Our thresholds aren't invented. This is SEBI's own Material Price Movement framework — five, four, three percent by price tier, index-adjusted. Here's the circular." |
| 1:30 | The funnel chart | "We looked at forty-one changes and showed four." Stop talking. |

Pre-record any segment that can fail live. The cursor picker makes the whole demo
work offline at any hour, which is the point of building it that way.

---

## PART E — JURY Q&A PREPARATION

**"Why these thresholds?"** The exchange's own Material Price Movement
framework, published 21 May 2024 under SEBI LODR Reg 30(11). Five/four/three
percent by price tier, index-adjusted when the benchmark moved ≥1% at 09:30 in
the same direction. Here is the circular. Then: the z-score layer sits on top,
because a flat percentage is wrong across volatility regimes.

**"Which numbers are yours and which are the regulator's?"** Answer precisely.
MPM tiers, Reg 30 timelines, circuit-breaker stages: regulatory, unchanged. The
four ranking weights, window lengths, and classification multipliers: ours, tuned
against the eval harness. Pretending everything is regulation-derived would not
survive scrutiny.

**"Isn't this just an alert system?"** No — it's budgeted. The cap is a safety
control. The FCA ran an experiment on 9,000 consumers: push notifications raised
trade count 11% and the share of trades in risky investments 8%, with larger
effects on people with low financial literacy. Surfacing everything is the
failure mode this is designed against.

**"How does it scale?"** Users are millions; symbols are thousands. Groww
reported 13.12 million active clients against maybe 2,500 meaningfully-watched
cash equities. Compute per symbol, join per user at read time — never fan out on
write. Then the production fan-out design: subject-based pub/sub, binary
payloads, conflation — the pattern Groww's own 915 team documented.

**"What breaks?"** Volunteer all of it: corporate actions (the number one silent
bug, and here is the test that catches it, plus the empirical factor
verification); halts indistinguishable from feed failure, which is why we anchor
on a guaranteed-liquid instrument; dual-listing divergence on thin venues; and
provisional intraday statistics that get restated after the bhavcopy lands around
18:00, with a cache purge so the restatement is actually visible.

**"Why no ML?"** Lead with the correction, not the defence: this is not a rules
engine. The scoring path is event-study econometrics — an OLS market model with a
leakage gap, standardised abnormal returns, CAR with `sqrt(n)` scaling, a logit
transform on a bounded variable, winsorisation and variance floors. It is a
quantitative model that happens to be transparent.

Then the actual reason: **ranking is supervised and there is no label on day
one.** Anyone claiming a learned ranker here either invented a synthetic target
or built something else. If the target is forward return, it is a
return-prediction model on a retail broker surface, which is an unregistered
advice engine. Then the explain endpoint: the jury will ask why an item ranks
second, and a boosted-tree score cannot answer that.

Close by drawing the line rather than refusing: models *are* used — filing
summarisation and residual category classification — both strictly after scoring,
neither able to emit a number. Then sketch the v2: label is Brief-item opens,
inverse-propensity weighting for position bias, current score kept as a feature
so the model learns a residual re-rank, offline evaluation on the existing replay
harness, and the regulatory floor stays outside the model permanently.

**"Why not unsupervised anomaly detection? That needs no labels."** Expect this
follow-up; it is the sharp version of the question. An isolation forest over
return, turnover and delivery finds broadly the same outliers and loses three
things we need: a decomposable score — the copy says *"volume 3× normal but
delivery below its own average"*, and that sentence requires separated
components; a unit the user can reason about (3.9σ); and any link between a
threshold and a regulation. Strictly worse here, not simpler.

**"Why turnover instead of volume?"** Turnover in rupees is invariant to splits
and bonuses; share volume is not. Using turnover removes an entire class of
adjustment bug. The caveat is price-level drift over long windows, which is
negligible over our 20-session baseline.

**"Why not adjust for dividends?"** Price Return versus Total Return. Adjusting
the price series for cash dividends would make our 52-week highs disagree with
every other quote site in India. We store the total-return factor separately and
leave it unused in v1. Large-dividend ex-dates are still suppressed and explained.

**"Why is this item ranked second?"** Open `/api/brief/explain/{id}` live. Show
alpha, beta, residual sigma, sample size, SAR, CAR, SCAR, the MPM tier and
threshold, every classification branch, every multiplier, and the inputs hash.
This is why invariant N1 exists.

**"Did you consider X?"** Point at §26, the review ledger. It lists every
proposal, what was accepted, what was rejected, and why — including one proposal
that was technically incorrect and why.

---

## PART F — RISK REGISTER

| Risk | Prob. | Impact | Mitigation | When |
|---|---|---|---|---|
| Broker API activation >24h | High | High | `QuoteSource` abstraction + `PollingSource` first | 0.2, hour one |
| NSE blocks or rate-limits | High | High | Cookie warmup, breaker, `curl_cffi` tier, disk cache | 0.1, 2.6 |
| CA parser misses a case | Med | Critical | Fail safe: unparsed/composite/discrepancy → suppress | 1.3, 1.4, 6.1 |
| Missing 09:30 snapshots | High | Med | Priority matrix with `ESTIMATED_FROM_OPEN` flag | 2.4 |
| Baseline backfill too slow | Med | Med | Vectorised pandas, not per-symbol loops | 4.1 |
| Non-deterministic hash | Med | Critical | Canonical JSON with float rounding, cross-process test | 0.4 |
| Frontend consumes the schedule | High | High | 12h budget, one strong visual idea, component reuse | Phase 12 |
| Judging outside market hours | Certain | High | Cursor picker + offline seed | 12.5, 14.2 |
| Agent invents a threshold | High | Critical | Rule R1 + bare-literal lint | Part A |
| Agent adds TypeScript / Next.js / i18n | Med | Low | Rules R7, R8 + a CI check for `.ts` files | Part A |
| Demo breaks live | Med | Critical | Offline seed; pre-record risky segments | 14.2, Part D |

---

## PART G — PRE-SUBMISSION CHECKLIST

Run at T−4 hours. Every line must be ticked.

**Correctness**
- [ ] All three golden corporate-action fixtures produce zero scored signals
- [ ] The `announcements` table is populated and at least one Brief item in the
      demo is classified `EXPLAINED` with a real filing link
- [ ] The dividend fixture has `cum_price_factor = 1.0` (PRI, not TRI)
- [ ] Brief cap invariant test passes over 200 randomised states
- [ ] Signal-engine purity test passes
- [ ] `inputs_hash` determinism test passes across two processes
- [ ] `SCAR` across-a-holiday test passes (session count, not calendar days)
- [ ] Sign-flip refractory test passes (−4% then +4% → two items)
- [ ] Illiquid-watchlist test does **not** produce `HALTED_MARKET`
- [ ] No bare numeric literals in business logic (lint clean)
- [ ] No banned words in any user-facing string (lint clean)
- [ ] Banned-word check runs at **runtime** on model-generated copy, verified
      with a buyback filing (Task 8.6) — or 8.6 is cut and no generated text ships
- [ ] Parser coverage report run; CA and announcement coverage numbers in README
- [ ] No `volume` used in any baseline or z-score (grep clean)

**Demo readiness**
- [ ] `make seed` works on a clean container with networking disabled
- [ ] Deployed URL loads in a fresh incognito browser
- [ ] Deep links survive hard refresh (SPA fallback works)
- [ ] Cursor picker works for a 3-week-back and a 10-minute-back cursor
- [ ] `/eval` renders the funnel and all three suppression cases
- [ ] `/api/brief/explain/{id}` returns a full trace for a real surfaced item
- [ ] Every screen has a designed empty state — no spinner-only screens
- [ ] Video recorded, under 100 seconds, audio audible

**Documentation**
- [ ] README states the thesis in the first three lines
- [ ] Every threshold carries its source link
- [ ] Data provenance and limitations stated openly
- [ ] Considered-and-rejected section present
- [ ] Review ledger (§26) present
- [ ] Failure-modes catalogue present
- [ ] Self-audit of five false positives present
- [ ] `ARCHITECTURE.md` and `BUILD_PLAN.md` committed

**Scope compliance**
- [ ] Zero `.ts` or `.tsx` files; no `tsconfig.json`
- [ ] No Next.js dependency in `package.json`
- [ ] No React Native / Expo / Capacitor anywhere
- [ ] No i18n framework, no locale files; all strings English literals
- [ ] No recommendation language anywhere in the product
