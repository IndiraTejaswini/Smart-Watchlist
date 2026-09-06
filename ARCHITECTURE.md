# ARCHITECTURE.md
## Smart Market Watchlist — "The Brief"
### Groww Hiring Challenge · System architecture and design rationale
### Revision 2 — incorporates external review. Section 26 is the review ledger.

---

## 0. How to read this document

This is the **single source of truth** for what gets built and why.
`BUILD_PLAN.md` holds the ordered task list and the agent operating rules.
This document explains the *system*; that one explains the *work*.

### 0.1 Reading rules for the coding agent

1. **Section 21 (Constants Registry) is law.** Every numeric threshold used
   anywhere comes from Section 21. If you need a number that is not there,
   **stop and ask the human.** Do not invent one.
2. Constants are `[REGULATORY]` (copied from an exchange or regulator document,
   never changeable) or `[TUNED]` (ours, changed only via the eval harness).
3. Every module has a **Why**. Before changing a module's behaviour, read it. If
   the change contradicts the Why, flag that instead of doing it.
4. Implement formulas exactly as written, including floors, caps, and minimum
   sample sizes. Do not "improve" the maths.

### 0.2 The three non-negotiables

**N1 — Reproducibility.** Every displayed number must be recomputable from
stored inputs. Every signal row stores an `inputs_hash`.
`/api/brief/explain/{id}` returns the full input trace. A number that cannot be
explained is a bug.

**N2 — Provenance.** Every displayed number carries its source, as-of timestamp,
and provisional status. There is no bare price in this system.

**N3 — Restraint.** The Brief has a hard cap and must be able to say "nothing
happened" with no special-casing. Rendering more than `BRIEF_MAX_ITEMS` scored
items is a P0 bug.

---

## 1. The product thesis

### 1.1 The claim

> A watchlist's job is not to maximise salience. It is to allocate a scarce,
> fixed attention budget to the changes that carry information — and to spend
> zero of it when nothing informative happened.

The product is an **attention allocator with a budget**, not a notification pipe.

### 1.2 Why — the four findings this rests on

**F1. Attention decides the choice set before preferences do.**
Barber & Odean (RFS 2008): individual investors are net buyers of
attention-grabbing stocks — names in the news, names with abnormal trading
volume, names with extreme one-day returns. Investors manage the search problem
across thousands of stocks by only considering ones that recently caught their
attention. A watchlist is literally an attention-allocation device. Whatever
sits at the top *becomes* the choice set.

*Consequence:* ranking is the product's primary causal lever on user behaviour.

**F2. Untargeted notification measurably increases trading and risk-taking.**
The FCA ran an experimental trading app on 9,000+ consumers. Push notifications
raised trade count by 11%; the share of trades in risky investments rose 8%.
Effects were larger for low financial literacy and for 18–34 year olds.

*Consequence:* `BRIEF_MAX_ITEMS` is a safety control, not a UI preference.

**F3. Attention itself is not the problem — undifferentiated attention is.**
Gargano & Rossi (RFS 2018) found attention positively related to performance at
both portfolio and trade level, and *especially* profitable for stocks with high
uncertainty but a lot of available public information.

*Consequence:* route attention to high-uncertainty, high-public-information
situations. That is what Section 11 operationalises.

**F4. Explained and unexplained moves are different objects.**
Boudoukh, Feldman, Kogan & Richardson (NBER 18725): once relevant news is
correctly identified, conditional on extreme moves, price reversals occur on
no-news days while identified-news days show continuation. Volatility on
identified news days is more than double that of other days.

*Consequence:* the keystone. A big move with an identified cause and one without
have **opposite expected forward behaviour**. Every existing watchlist renders
them identically as a red number. `classification` is load-bearing, and a
primary ranking multiplier.

### 1.3 The gap being filled

Every mainstream watchlist computes change against **previous close** — a
reference point chosen by the exchange calendar, not by the user. Apple Stocks
offers sparklines and sortable percentage columns. MarketBeat's headline
watchlist upgrade was optional 60-second refresh and column selection.

Zerodha diagnosed the right problem in their Kite Marketwatch post — watchlists
get messier over time because traders keep adding instruments and rarely delete
them — and answered it with **capacity and manual filing**: 25 watchlists × 250
instruments, custom groups, pre-built collections. That is a storage answer to
an attention problem.

| # | Hole in the market | Our fill |
|---|---|---|
| 1 | No product has a read cursor for markets | §12 |
| 2 | Nobody separates market-explained from stock-specific for retail | §11 |
| 3 | Nobody suppresses corporate-action pseudo-events at the alert layer | §11.1 |
| 4 | Delivery % — free, official, daily, India-only — is in no mainstream watchlist | §10.2 |
| 5 | Nobody ever says "nothing happened" | §13.5 |

---

## 2. Scope

### 2.1 In scope

- **Web application only** (desktop-first, responsive to 768px)
- **English only**, single locale, `Asia/Kolkata` throughout
- NSE cash equities (EQ / BE / BZ series)
- One demo user, multi-user-capable schema
- Live quote streaming with conflation, plus a polling fallback
- Full EOD pipeline with provisional → final restatement
- Evaluation harness producing publishable numbers

### 2.2 Explicitly out of scope

| Excluded | Why |
|---|---|
| Mobile app (React Native / Capacitor / native) | User decision. Web only. |
| **Next.js / SSR** | User decision. Plain React SPA on Vite. |
| **TypeScript** | User decision. JavaScript + JSDoc types + runtime validation at the API boundary only. |
| Internationalisation | User decision. English string literals; no i18n framework, no locale files, no `t()` wrappers. |
| BSE as a live venue | Schema and policy in place (`primary_venue`); NSE only ingested. Documented limitation. |
| Derivatives (F&O) instruments | Cash equity only. F&O names carry no fixed price band, which breaks the band-hit branch of the MPM gate. |
| Order placement | Out of the brief, and avoids the regulated-advice surface. |
| ML ranking · CRDTs · Kafka · custom charting | §23 |

### 2.3 A note on "advice"

The system never issues a recommendation, buy/sell signal, target, or rating. It
describes what changed and how unusual it is. Investment advice is a registered
activity in India, and SEBI's own study found close to 93% of individual F&O
traders lost money — a broker surface that says "act" points the wrong way.
Copy rules in §17.6 enforce this with a build-failing lint.

---

## 3. System overview

### 3.1 Component diagram

```
┌────────────────────────────────────────────────────────────────────┐
│ SOURCES                                                            │
│ NSE bhavcopy (EOD)        NSE announcements (3-min poll)          │
│ NSE delivery file (EOD)   NSE corporate actions (07:00 daily)     │
│ Index EOD + 09:30 snap    Broker WS / polled quotes (intraday)    │
└─────────────┬──────────────────────────────────┬───────────────────┘
              │                                  │
       ┌──────▼─────────┐              ┌─────────▼────────┐
       │ EOD INGEST     │              │ LIVE INGEST      │
       │ idempotent     │              │ reconnecting     │
       │ hashed+cached  │              │ benchmark-       │
       │ quarantine DLQ │              │ anchored         │
       └──────┬─────────┘              └─────────┬────────┘
              │        ┌───────────────────────── ┘
              ▼        ▼
       ┌──────────────────────────────┐
       │ NORMALISER                   │
       │ symbol/alias resolution      │
       │ live ex-date factor applied  │
       │ timestamp → IST trading date │
       └──────┬─────────────┬─────────┘
              ▼             ▼
   ┌──────────────────┐ ┌──────────────────────┐
   │ POSTGRES         │ │ REDIS                │
   │ facts + factors  │ │ quotes:latest        │
   │ + signals        │ │ feed:heartbeat       │
   │ (source of truth)│ │ stream:ticks         │
   └────────┬─────────┘ │ factbundle:cold:*    │
            │           │ idempotency:*        │
            │           │ cache:brief:*        │
            │           └──────┬───────────────┘
            ▼                  ▼
   ┌──────────────────┐ ┌──────────────────────┐
   │ SIGNAL ENGINE    │ │ WS GATEWAY           │
   │ pure function    │ │ per-conn subscribe   │
   │ f(facts ≤ T)     │ │ 400ms conflation     │
   │ → SignalEvent    │ │ seq + resync         │
   └────────┬─────────┘ └──────┬───────────────┘
            ▼                  │
   ┌──────────────────┐        │
   │ DIGEST BUILDER   │        │
   │ join(cursor,     │        │
   │      signals)    │        │
   │ rank → cap       │        │
   └────────┬─────────┘        │
            ▼                  ▼
   ┌────────────────────────────────────┐
   │ FASTAPI (REST + WS)                │
   │ also serves the built SPA          │
   └───────────────┬────────────────────┘
                   ▼
   ┌────────────────────────────────────┐
   │ REACT SPA (Vite, JavaScript)       │
   │ /brief /watchlist /symbol /eval    │
   └────────────────────────────────────┘
```

### 3.2 Technology choices and why

| Layer | Choice | Why this and not the alternative |
|---|---|---|
| Backend language | Python 3.11 | The signal engine is numerical: pandas/numpy/statsmodels do the market-model regression and rolling statistics in a few lines. |
| API | FastAPI + Uvicorn | Native async for the WS gateway; Pydantic models double as the API contract; OpenAPI at `/docs` the frontend can read. |
| Durable store | PostgreSQL 16 | Transactional writes, window functions for rolling baselines, `ON CONFLICT` for idempotent ingest. |
| Cache, stream, latest value | Redis 7 | `quotes:latest`, Redis Streams for tick transport with consumer groups, cold-FactBundle cache, idempotency keys, Brief cache. |
| Stream transport | **Redis Streams, not Kafka** | §23.3. Consumer interface abstracted so Kafka is a swap. |
| **Frontend** | **React 18 + Vite + JavaScript** | User decision: no Next.js, no TypeScript. Vite's sub-second HMR matters more than SSR at this size. |
| Routing | React Router v6 | SPA routing; FastAPI serves `index.html` for unmatched non-`/api` paths. |
| Server state | TanStack Query v5 | Caching, retries, `persistQueryClient` → IndexedDB for offline reads. |
| Tick state | Zustand | Groww's own 915 team documented choosing Zustand precisely because its hook-centric API allows granular updates so only affected components re-render, avoiding context-based re-render problems at tick frequency. Same tool, same reason, citable. |
| API boundary validation | Zod | JavaScript has no compile-time contract. Zod validates Brief and quote payloads **at the boundary only** — this recovers most of what TypeScript would have caught, at runtime, where it matters. Not used for internal state. |
| Styling | Tailwind CSS v4 (Vite plugin) | §17.2 tokens map directly to the theme. |
| Charts | `lightweight-charts` (TradingView, Apache-2.0) | Groww integrated TradingView's charting library rather than building from scratch. Same reasoning, smaller scale. |
| Serving | FastAPI `StaticFiles` serves the Vite build | One fewer container than a separate nginx; simplifies the demo deploy. |
| Deploy | Docker Compose | `docker compose up` reproducibility for the jury. |

**What dropping Next.js costs, and the mitigation.** No SSR means the Brief has
a loading state on first paint. Mitigation: a skeleton whose layout exactly
matches the loaded state — same column width, same rule positions, same
placeholder count — so there is no content shift. State this in the README
rather than pretending it is free.

**What dropping TypeScript costs, and the mitigation.** No compile-time contract
against the API. Mitigation: (a) Zod schemas at the API boundary that throw
loudly in dev and degrade gracefully in prod; (b) JSDoc `@typedef` blocks in
`lib/types.js` so editors still give completion; (c) the backend OpenAPI schema
is canonical, and the Zod schemas are written from it.

---

## 4. Foundations

### 4.1 Repository layout

```
smart-watchlist/
├── docker-compose.yml
├── Makefile                        # seed, backfill, eval, ingest-retry
├── .env.example
├── ARCHITECTURE.md · BUILD_PLAN.md · README.md
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   └── app/
│       ├── main.py · config.py · db.py
│       ├── constants.py            # ⚠ §21. Frozen.
│       ├── canonical.py            # canonical JSON + inputs_hash   §4.2
│       ├── timeutil.py             # ist_trading_date, session phase §4.3
│       ├── models/ · schemas/
│       ├── ingest/
│       │   ├── nse_client.py       # cookies, backoff, breaker, hash
│       │   ├── symbol_master.py · calendar.py
│       │   ├── bhavcopy.py · delivery.py · index_data.py
│       │   ├── corporate_actions.py · ca_parser.py
│       │   ├── announcements.py · quarantine.py
│       │   └── live/ base.py · broker_ws.py · polling.py
│       ├── pipeline/
│       │   ├── factors.py          # adjustment factor table  §7.1
│       │   ├── adjust.py · baselines.py
│       │   ├── mpm.py              # Layer 0
│       │   ├── abnormality.py      # Layer 1
│       │   ├── classify.py         # Layer 2
│       │   ├── factbundle.py       # cold/hot split + loader
│       │   ├── signal_engine.py    # pure fn
│       │   └── restate.py
│       ├── digest/ ranker.py · builder.py · copy.py
│       ├── realtime/ freshness.py · conflator.py · ws_gateway.py
│       ├── api/ · eval/
│   └── tests/ fixtures/ · test_*.py
└── frontend/
    ├── package.json · vite.config.js · index.html
    └── src/
        ├── main.jsx · App.jsx
        ├── pages/ BriefPage.jsx · WatchlistPage.jsx · SymbolPage.jsx
        │          EvalPage.jsx · SettingsPage.jsx
        ├── components/
        ├── store/ quotes.js        # Zustand tick store
        ├── lib/ api.js · schemas.js (Zod) · types.js (JSDoc)
        │        ws.js · format.js
        └── styles/index.css
```

### 4.2 The determinism contract

**Why this exists.** Intraday delivery and turnover statistics are provisional
until the bhavcopy lands in the evening. The system *must* recompute and
restate. If scoring is not a pure function of stored inputs, you cannot restate
— you can only overwrite, and you can never explain why yesterday's Brief
changed. Non-determinism in a pricing surface is a P0 defect.

```python
# app/pipeline/signal_engine.py
def compute_signals(symbol: str, as_of: datetime, facts: FactBundle) -> list[SignalEvent]:
    """
    PURE FUNCTION.
      compute_signals(s, T, facts) == compute_signals(s, T, facts)
      for any number of invocations, in any process, on any day.

    FORBIDDEN inside this function and everything it calls:
      datetime.now / date.today / time.time
      random / uuid4 / hash() over unordered collections
      any network call, any database read, os.environ
    """
```

`FactBundle` is a frozen dataclass. A separate loader assembles it and *is*
allowed to touch the database.

Pass `as_of = now()` and it is a live engine. Pass a historical timestamp and it
is a replay engine. **There is no "demo mode" branch anywhere in the code.**
This is what makes the eval harness free, makes restatement possible, and makes
the app demoable at 2am on a Sunday.

**Canonical serialisation `[REVIEW-ACCEPTED]`.** `json.dumps` cannot serialise
numpy scalars, `Decimal`, or `datetime`, and unrounded float repr is not stable
across platforms. Since `inputs_hash` underpins N1, the serialiser is part of
the contract, not an implementation detail.

```python
# app/canonical.py
def to_canonical_json(obj) -> bytes:
    """
    Mandatory rules:
      - dict keys sorted
      - all floats rounded to CANONICAL_FLOAT_DP (=8) before serialisation
      - numpy scalars → python scalars; Decimal → float, then rounded
      - datetimes → ISO 8601 with explicit UTC offset, microseconds truncated
      - None handled consistently (omit, never sometimes-null)
      - sets → sorted lists
      - NaN / Infinity → raise, never emit non-standard JSON
    """

def inputs_hash(bundle) -> str:
    return hashlib.sha256(to_canonical_json(bundle)).hexdigest()
```

Test: serialise the same bundle in two processes across two runs; assert byte
equality.

**FactBundle completeness `[REVIEW-ACCEPTED]`.** A newly listed stock has no
120-day baseline; an announcement poll may have timed out. The loader must never
raise on absent data — it declares explicit fallbacks.

```python
@dataclass(frozen=True)
class FactBundle:
    instrument:        Instrument
    bars:              tuple[Bar, ...]            # () if none
    factors:           tuple[Factor, ...]         # () if none
    delivery:          tuple[Delivery, ...]       # () if none
    baseline:          Baseline | None            # None → DEGRADED path
    index_bars:        tuple[Bar, ...]
    index_0930:        Index0930 | None           # None → no index adjustment
    corporate_actions: tuple[CorporateAction, ...]
    announcements:     tuple[Announcement, ...]
    sector_peers:      tuple[PeerAR, ...]         # () → no SECTOR_WIDE possible
    completeness:      frozenset[str]
```

`completeness` is carried into `signal_events` and surfaced in the explain
endpoint. A signal computed on partial facts is labelled as such, never silently
scored as if complete.

**Cold/hot split and caching `[REVIEW-ACCEPTED, REFRAMED]`.** The review warned
about assembling a FactBundle per tick. The deeper point is that we do not
recompute signals per tick at all — but the loader still benefits from a split:

- **Cold half** — baselines, factors, corporate actions, announcements, peers,
  instrument. Changes at most once a day. Cached in Redis at
  `factbundle:cold:{symbol}:{trading_date}`, TTL 24h, purged when EOD ingest
  completes for that date.
- **Hot half** — today's bar-so-far, assembled from `quotes:latest`.

Signals are evaluated every `SIGNAL_EVAL_INTERVAL_SECONDS` (=30) for subscribed
symbols, plus immediately on a band hit or a new linked announcement. **Never
per raw tick.**

### 4.3 Time handling

- Postgres `TIMESTAMPTZ`; compute in UTC; display in `Asia/Kolkata`.
- Trading dates are IST `DATE`, obtained only via `ist_trading_date(ts)`.
  Never `.date()` on a UTC timestamp.
- **Corporate-action ex-dates match on IST trading date `[REVIEW-ACCEPTED]`:**
  `ca_applies(symbol, ts) = exists ca where ca.ex_date == ist_trading_date(ts)`.
  Matching on a UTC date applies a split a day early or late, silently
  corrupting every price on the boundary.
- **Why this matters:** IST is UTC+5:30. Naive truncation puts a 19:00 IST
  announcement on the previous UTC day. This is the most common silent bug in
  Indian market-data pipelines.

---

## 5. Reference data

### 5.1 Symbol master

```sql
CREATE TABLE instruments (
  instrument_id   BIGSERIAL PRIMARY KEY,    -- immutable surrogate [REVIEW-ACCEPTED]
  symbol          TEXT UNIQUE NOT NULL,     -- natural key; FK in fact tables
  isin            TEXT,
  name            TEXT NOT NULL,
  series          TEXT NOT NULL,
  sector          TEXT NOT NULL DEFAULT 'UNASSIGNED',
  sector_source   TEXT NOT NULL,            -- PRIMARY_FILE|INDEX_MAP|VENDOR|UNASSIGNED
  industry        TEXT,
  face_value      NUMERIC(12,4),
  listing_date    DATE,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  primary_venue   TEXT NOT NULL DEFAULT 'NSE',
  has_derivatives BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE symbol_aliases (               -- rename handling [REVIEW-ACCEPTED, CHEAPER]
  old_symbol     TEXT PRIMARY KEY,
  instrument_id  BIGINT REFERENCES instruments(instrument_id),
  effective_date DATE NOT NULL,
  note           TEXT
);

CREATE TABLE symbol_master_snapshots (      -- audit trail [SCD2 REPLACEMENT]
  snapshot_date DATE,
  instrument_id BIGINT,
  payload       JSONB NOT NULL,
  PRIMARY KEY (snapshot_date, instrument_id)
);
```

**Why a surrogate key but `symbol` as the FK.** Exchanges do reassign tickers
(`TATAMOTORS` → `TMPV`), and ticker-only identity breaks historical joins. But
putting `instrument_id` into every fact table means every ad-hoc query and log
line during a fast build loses readability, which costs real hours. Compromise:
`instrument_id` is the immutable identity on `instruments`; fact tables key on
`symbol`; `symbol_aliases` resolves renames at load time so history stitches
together. Most of the benefit, a fraction of the friction.

**Why snapshots rather than SCD Type 2.** Bi-temporal `valid_from`/`valid_to` is
correct for institutional point-in-time reconstruction, but it adds an `as_of`
predicate to every reference-data query, including inside the pure loader. A
nightly JSONB snapshot gives the same audit trail and the same ability to
reconstruct later, at zero query cost now.

**Sector fallback chain `[REVIEW-ACCEPTED]`:**

```
1. NSE sector classification file
2. Index constituent mapping (Nifty sectoral indices)
3. Vendor/broker instrument metadata, if available
4. 'UNASSIGNED'   — never NULL
```

`sector_source` records which tier resolved it. `UNASSIGNED` symbols can never
be classified `SECTOR_WIDE`, which biases them toward being surfaced — so
coverage is a tracked metric, target >99% of active symbols.

### 5.2 Trading calendar — a session state machine `[REVIEW-ACCEPTED]`

A boolean `is_trading_day` is too thin. Pre-open equilibrium prices between
09:00 and 09:15 otherwise generate false gap alerts at open, and Muhurat and
half-day sessions break naive session-window logic.

```sql
CREATE TABLE trading_calendar (
  calendar_date  DATE PRIMARY KEY,
  is_trading_day BOOLEAN NOT NULL,
  pre_open_start TIMESTAMPTZ,
  pre_open_end   TIMESTAMPTZ,
  regular_open   TIMESTAMPTZ,
  regular_close  TIMESTAMPTZ,
  post_close_end TIMESTAMPTZ,
  session_type   TEXT NOT NULL DEFAULT 'REGULAR',  -- REGULAR|MUHURAT|HALF_DAY|CLOSED
  notes          TEXT
);
```

Derived helpers, all calendar-driven, never date arithmetic:

```python
session_phase(ts)        -> CLOSED | PRE_OPEN | REGULAR | POST_CLOSE
previous_trading_day(d)  -> date
session_close(d)         -> datetime      # announcement linking window
sessions_between(a, b)   -> int           # the sqrt(n) in SCAR
```

**Why:** "the previous trading day" is not "yesterday". A holiday inside the
cursor window changes the session count, which changes the `sqrt(n)`
denominator in SCAR. Without a real calendar this is wrong and invisible.

### 5.3 Corporate actions

#### 5.3.0 What is actually parsed — the risk model

Most of this system does no text parsing at all. Stating the split explicitly,
because it determines where parsing effort is worth spending:

| Data | Form | How read | Risk |
|---|---|---|---|
| Bhavcopy OHLC, volume, turnover, trades, bands | CSV, fixed columns | pandas | Schema drift only — column renames. Caught by the validators in §6.2 |
| Delivery quantities | CSV | pandas | Same |
| Index EOD and 09:30 snapshot | CSV / API | pandas | Same |
| Symbol master | CSV | pandas | Same |
| Live ticks | Broker SDK | typed | None |
| CA **dates** (`ex_date`, `record_date`) | API date fields | typed | None |
| Announcement `symbol`, `filed_at`, `attachment_url` | API fields | typed | None |
| **CA `purpose_raw` → adjustment factor** | **free text** | **regex** | **High** |
| **Announcement subject → category** | **semi-structured** | **`desc` field, regex fallback** | **Low** |

**Every number that reaches the signal engine — every price, volume, turnover
and delivery quantity — arrives as a typed column.** No regex touches them. The
z-scores, the market model, the MPM gate and the ranking are all computed from
structured input.

Only two things are parsed from text, and they carry very different stakes:

- **Corporate-action purpose strings.** A wrong factor renders a −50% phantom
  crash. This is the one place where parse failure is catastrophic, so it gets
  three independent defences: parse, verify against the observed price gap, and
  suppress on any doubt (below).
- **Announcement subjects.** A wrong category costs a multiplier — `EXPLAINED`
  at 1.15 instead of 1.35. The user never sees a wrong number, only a slightly
  misordered list. This does not deserve heavy engineering, and §9.2 removes most
  of the regex dependency by using the exchange's own category field first.

**Regex will not extract everything, and the design does not need it to.** What
it needs is to *know when it failed*. Coverage is reported as a metric (§19.2),
not assumed.

```sql
CREATE TABLE corporate_actions (
  id            BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL,
  ex_date       DATE NOT NULL,
  record_date   DATE,
  action_type   TEXT NOT NULL,   -- BONUS|SPLIT|CONSOLIDATION|DIVIDEND|RIGHTS
                                 -- |DEMERGER|COMPOSITE|UNPARSED
  ratio_text    TEXT,
  purpose_raw   TEXT NOT NULL,
  price_factor  NUMERIC(18,10),  -- splits+bonuses only (PRI)  [REVIEW-ACCEPTED]
  tr_factor     NUMERIC(18,10),  -- incl. cash dividends (TRI) [REVIEW-ACCEPTED]
  verification  TEXT NOT NULL,   -- VERIFIED|INFERRED|DISCREPANCY|UNVERIFIED
                                 -- |UNPARSED
  observed_gap  NUMERIC(12,6),
  source        TEXT NOT NULL,
  ingested_at   TIMESTAMPTZ NOT NULL,
  UNIQUE (symbol, ex_date, action_type, purpose_raw)
);
```

**Parsing:**

| Action | Example purpose string | `price_factor` |
|---|---|---|
| Bonus 1:1 | `BONUS 1:1` | 0.5 |
| Bonus 3:7 | `BONUS 3:7` | 7/10 = 0.7 |
| Split FV 10 → 2 | `FACE VALUE SPLIT FROM RS.10 TO RS.2` | 0.2 |
| Consolidation 10 → 1 | `CONSOLIDATION FROM RE.1 TO RS.10` | 10.0 |
| Cash dividend ₹12 on ₹840 | `DIVIDEND - RS 12 PER SHARE` | **1.0** (PRI); `tr_factor` = 0.98571 |

**PRI vs TRI `[REVIEW-ACCEPTED — corrects revision 1]`.**
Revision 1 folded cash dividends into the price adjustment. That is wrong for a
consumer product. Standard practice adjusts the price series for splits and
bonuses only (Price Return). Dividend-adjusting would make our 52-week highs and
percentage changes disagree with every other quote site in India — which a jury
may well spot on a familiar name.

So `price_factor` handles splits, bonuses, consolidations, demergers and rights.
Cash dividends leave `price_factor = 1.0` and populate `tr_factor` only.
`tr_factor` is stored and unused in v1, so total-return analysis is possible
later without re-ingesting.

This does not weaken dividend handling for the user: large-dividend ex-dates
still fall inside the suppression window (§11.1) and still produce a
`CORP_ACTION_NOTICE` explaining the drop.

**Multi-action strings `[REVIEW-ACCEPTED, SIMPLIFIED]`.** Exchanges do publish
combined events (`SUB-DIVISION FROM RS 10 TO RS 2 AND BONUS IN 1:1 RATIO`). A
formal grammar parser is not warranted here. Instead:

1. Detect the composite case — more than one action keyword, or ` AND ` between
   two ratio-bearing clauses.
2. If detected and both clauses parse cleanly, compose in **exchange execution
   order**: `consolidation/split → bonus → rights → dividend`.
3. If detected and either clause fails: `action_type = 'COMPOSITE'`,
   `price_factor = NULL`, `verification = 'UNPARSED'` — and suppress.

**Empirical factor verification `[REVIEW-ADAPTED]`.** The review proposed a
second vendor feed to cross-check parsed factors. No free second source exists in
this timebox — but **the market itself is a second source.** A parsed factor
makes a falsifiable prediction about the ex-date open.

Verify against `tr_factor`, **not** `price_factor`. The market gaps by the full
economic adjustment, which includes the dividend going ex; `price_factor` is
deliberately 1.0 for a pure dividend under PRI, so verifying against it would
mark every large special dividend as a discrepancy. Define `tr_factor` as the
combined factor — `price_factor × (prev − div_per_share) / prev` — so it equals
`price_factor` when there is no dividend and equals the dividend gap when there
is no split or bonus.

```python
prev     = close(symbol, previous_trading_day(ex_date))   # as-traded
expected = prev * tr_factor
observed = open_price(symbol, ex_date)
observed_gap = observed / prev

verification = 'VERIFIED' if abs(observed / expected - 1.0) <= CA_VERIFY_TOLERANCE \
               else 'DISCREPANCY'     # and suppress the window
```

This catches parser errors, wrong ratios, and missed composite actions using
data already on disk. It runs the morning after the ex-date, so it cannot gate
the ex-date itself — but it flags every historical factor, which is exactly what
the golden fixtures and the eval harness depend on.

**Inference — recovering the unparsed tail `[NEW]`.** Verification runs in one
direction: parse first, then check. It also runs in the other. If a
`corporate_actions` row exists for `(symbol, ex_date)` — so we know an action
occurred — but the purpose string did not parse, the observed gap is itself an
estimate of the factor:

```python
observed_gap = open_price(symbol, ex_date) / close(symbol, previous_trading_day(ex_date))
snapped = nearest(CA_CLEAN_FACTORS, observed_gap)      # 0.5, 0.2, 0.25, 1/3, 0.7 ...

if abs(observed_gap / snapped - 1.0) <= CA_INFER_SNAP_TOLERANCE:
    price_factor = snapped
    verification = 'INFERRED'        # usable, but flagged everywhere it appears
else:
    verification = 'UNPARSED'        # suppress
```

`CA_CLEAN_FACTORS` is the fixed set of factors produced by standard bonus ratios
(1:1, 1:2, 2:1, 3:5, 1:5 …) and standard face-value splits (10→1, 10→2, 10→5,
5→1, 2→1). It is a lookup table, not a parser.

**Why this is safe, and why it is not circular.** The guard is that a scheduled
corporate action must already exist for that date. Without that guard a genuine
−50% crash would be silently reinterpreted as a 1:1 bonus, which is the worst
failure this system can produce. With it, we are only choosing *which* clean
ratio applies to an action we already know happened.

The result is **two independent estimators of the same quantity**: the text and
the price gap. When they agree, confidence is high. When they disagree, suppress.
When only one exists, use it and flag it. That is a much stronger position than
"the regex must be right", and it is the honest answer to how far string parsing
can be trusted.

**Fail-safe rule.** `UNPARSED`, `COMPOSITE`, or `DISCREPANCY` → suppress the
symbol's ex-date window anyway. Suppressing a real signal is a minor loss.
Showing a −50% crash that never happened is catastrophic.

**Why corporate actions come before anything numerical.** After the ex-bonus
date a 1:1 bonus roughly halves the price; shareholder value is unchanged, just
spread over more shares. The exchange's own stated principle is that a
participant's position value on the cum and ex dates should remain the same as
far as possible. If this table is wrong, every return, volatility, beta and
signal downstream is wrong.

---

## 6. EOD ingest

### 6.1 Sources and timing

| Source | Contents | Published | Our poll |
|---|---|---|---|
| CM bhavcopy (UDiFF) | OHLC, prev close, volume, turnover, trades, series | evening after close, typically from ~16:00 IST | 18:00, retry 18:30 / 19:00 / 20:00 |
| Security-wise deliverable positions | deliverable quantity, delivery % | with the EOD bhavcopy, around 18:00 IST | same |
| Index EOD | Nifty 50 OHLC | evening | same |
| Index 09:30 snapshot | Nifty 50 value at 09:30 | captured by us intraday | 09:30:05 IST daily |
| Corporate actions | ex-dates | continuous | 07:00 daily, before the session |

**The 09:30 index snapshot is a hard requirement.** The MPM framework freezes
the benchmark index change at 09:30 and uses that frozen value for the whole
session. It cannot be reconstructed from EOD data.

**Backfill priority matrix `[REVIEW-ACCEPTED]` — resolve in strict order:**

```
1. Live snapshot at 09:30:05 IST            → source = CAPTURED_LIVE
2. Broker 1-minute candle, 09:30 close      → source = BROKER_CANDLE
3. Index open price                         → source = ESTIMATED_FROM_OPEN
                                              + data-quality flag on every
                                                signal derived from that date
```

Never silently substitute the open for the 09:30 value.

**Retry cap and escalation `[REVIEW-ACCEPTED, SIMPLIFIED]`.** If all four polls
fail by 20:30 IST: mark `ingest_runs` `ESCALATED`, **pause dependent baseline
and restatement jobs** (never run them on partial data), raise the banner on
`/api/market/status`, require a manual `make ingest-retry`. No paging
integration — there is no on-call.

**Calendar awareness `[REVIEW-ACCEPTED]`.** Check `trading_calendar` before
scheduling. Non-trading day → skip silently, no missing-data alert. `MUHURAT` or
`HALF_DAY` → adjust the poll time and suppress the row-count anomaly check,
since volumes are legitimately abnormal.

### 6.2 Ingest contract

1. **Idempotent.** `INSERT ... ON CONFLICT (symbol, date) DO UPDATE`.
   **Note:** the primary key is `(symbol, date)`. A symbol has exactly one series
   on a given day; adding `series` to the key would *permit* duplicate rows for
   one symbol-date rather than prevent them. Series is a column.
2. **Writes an `ingest_runs` row:** source, target date, status, row count,
   `file_hash`, start, finish, error.
3. **Content-hashes the raw file first `[REVIEW-ACCEPTED]`.** SHA-256 over the
   downloaded bytes. If it matches a prior successful run for the same source
   and date, skip parsing entirely. Also catches truncated downloads that
   returned HTTP 200.
4. **Validates before committing.** `high >= low`, `high >= max(open, close)`,
   `low <= min(open, close)`, `volume >= 0`, `deliverable_qty <= traded_qty`.
5. **Quarantines rejected rows `[REVIEW-ACCEPTED]`** rather than dropping them:

```sql
CREATE TABLE ingest_quarantine (
  id BIGSERIAL PRIMARY KEY,
  ingest_run_id    BIGINT REFERENCES ingest_runs(id),
  source_file      TEXT,
  raw_payload      JSONB NOT NULL,
  rejection_reason TEXT NOT NULL,   -- HIGH_LT_LOW | DELIVERY_GT_TRADED | ...
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

6. **Two-sided count check `[REVIEW-ACCEPTED]`.** The ±20% rolling-median test
   alone is fragile around index reconstitution and short sessions. Add a
   deterministic floor:

```
expected_active = COUNT(*) FROM instruments WHERE is_active
abort if rows < ACTIVE_ROW_FLOOR_FRAC (=0.98) * expected_active
abort if abs(rows - median5)/median5 > ROW_COUNT_DEVIATION (=0.20)
         AND session_type = 'REGULAR'
abort if quarantined/total > QUARANTINE_ABORT_FRAC (=0.02)
```

7. **One transaction per file.** Never partially commits.

**Why the count checks:** NSE occasionally publishes a truncated file. A silent
40%-short bhavcopy makes every missing symbol look like it stopped trading —
which the freshness machine reads as stale and which corrupts the 20-day rolling
baselines for weeks.

### 6.3 NSE HTTP client

NSE endpoints need a browser-like session: realistic headers, a prior GET to the
homepage for `nsit`/`nseappid` cookies, and a delay between requests. They fail
intermittently and their anti-bot rules change.

```
Tier 1  httpx with ONE realistic modern browser header set, kept constant per
        session (rotation makes traffic look MORE synthetic, not less)
        + explicit homepage warmup before any /api/ call
        + cookie refresh on 401/403
        + exponential backoff with jitter, max NSE_MAX_ATTEMPTS (=5)
        + 30s timeout

Tier 2  circuit breaker  [REVIEW-ACCEPTED]
        NSE_BREAKER_FAILURES (=3) consecutive 403/429 → open the breaker,
        pause NSE_BREAKER_COOLDOWN_S (=300), then half-open with one probe.
        Prevents burning all retries against an active block.

Tier 3  curl_cffi with Chrome TLS impersonation  [REVIEW-ACCEPTED]
        Modern anti-bot tooling fingerprints the TLS handshake (JA3/JA4) and
        HTTP/2 settings, so correct headers alone are not sufficient.
        curl_cffi is a near-drop-in replacement costing one dependency.
        (Playwright rejected — §23.6.)

Always  local disk cache at data/cache/{source}/{date}/ with a SHA-256 sidecar,
        and a --from-cache-only flag for offline development.
```

Client metrics `[REVIEW-ACCEPTED]`: `nse_http_requests_total{endpoint,status}`,
`nse_http_request_duration_seconds{endpoint}`, `nse_cookie_refresh_total`,
`nse_cache_hit_ratio`, `nse_breaker_state`.

**Why the cache is P0:** the network is the least reliable component and the one
most likely to burn irreplaceable hours. Download once, develop offline forever.

---

## 7. Adjusted price series

### 7.1 Factor table, not row rewriting `[REVIEW-ACCEPTED — improves revision 1]`

Revision 1 recomputed and rewrote a symbol's entire `adjusted_bars` history
whenever a corporate action landed. That is high write churn and it invalidates
every cached slice of the series.

Store factors; adjust at read time:

```sql
CREATE TABLE symbol_adjustment_factors (
  symbol           TEXT,
  trade_date       DATE,
  cum_price_factor NUMERIC(18,10) NOT NULL DEFAULT 1.0,  -- PRI: splits + bonuses
  cum_tr_factor    NUMERIC(18,10) NOT NULL DEFAULT 1.0,  -- TRI: + cash dividends
  PRIMARY KEY (symbol, trade_date)
);
-- cum_price_factor(symbol, D) = product of price_factor for ex_dates strictly AFTER D

CREATE VIEW v_adjusted_bars AS
SELECT b.symbol, b.date,
       b.open  * COALESCE(f.cum_price_factor, 1.0) AS adj_open,
       b.high  * COALESCE(f.cum_price_factor, 1.0) AS adj_high,
       b.low   * COALESCE(f.cum_price_factor, 1.0) AS adj_low,
       b.close * COALESCE(f.cum_price_factor, 1.0) AS adj_close,
       b.turnover                                   AS adj_turnover,   -- §7.2
       COALESCE(f.cum_price_factor, 1.0)            AS cum_price_factor
FROM daily_bars b
LEFT JOIN symbol_adjustment_factors f
  ON f.symbol = b.symbol AND f.trade_date = b.date;
```

Only that symbol's factor rows are rewritten when a new action lands (thousands
of rows, not millions). A `MATERIALIZED VIEW` refreshed after EOD is the
optimisation if the view proves slow — measure before doing it.

### 7.2 Turnover, not share volume `[REVIEW-ACCEPTED — best catch in the review]`

Revision 1 computed `adj_volume = volume / cum_factor`, which introduces
rounding artefacts on large splits and requires the factor to be correct.

**Turnover in rupees is invariant to splits and bonuses.** A 1:10 split
multiplies share count by 10 and divides price by 10; turnover is unchanged.

> **Rule: every abnormality statistic over trading activity uses turnover (₹),
> never share volume.** Share volume is displayed to the user but never fed to a
> z-score.

This deletes an entire class of adjustment bug at zero cost.

*Honest caveat for the README:* turnover is not invariant to price-level drift —
a stock that doubled in price has doubled turnover at constant share count. Over
the 20-session baseline window this drift is negligible; over a multi-year window
it would not be. Our windows are short, so the trade is clean.

### 7.3 The ex-date return rule

Never compute a return across an ex-date from the as-traded series. Enforce with
a naming convention plus a lint: return-computing functions accept parameters
named `adj_*` only, and a test greps for `close` being passed into
`abnormality.py`.

### 7.4 Live tick normalisation on ex-date mornings `[REVIEW-ACCEPTED, NARROWED]`

On an ex-date morning, broker ticks carry as-traded prices while our baselines
are adjusted. Comparing them directly produces a false anomaly at open.

Signal-side this is **already covered** by the corporate-action suppression in
§11.1 — that symbol generates no scored signal across its ex-date window
regardless. So it is not a signal-correctness bug.

It *is* a display-correctness issue. The normaliser therefore stamps every live
tick with the symbol's `cum_price_factor` as of today, and the UI uses it to
render a correct previous-close comparison on the ex-date rather than a
meaningless −50%.

### 7.5 Golden fixtures — write these before the implementation

Three verified real events from the ingested history:
1. A 1:1 bonus — as-traded ≈ −50%, adjusted ≈ 0%, scored signals = 0
2. A face-value split (10 → 2) — as-traded ≈ −80%, adjusted ≈ 0%, signals = 0
3. A large special dividend — as-traded shows the drop; **`price_factor` stays
   1.0** (PRI); a `CORP_ACTION_NOTICE` is emitted; scored signals = 0

Commit each with its source URL. The demo depends on these.

---

## 8. Baselines

### 8.1 Market model

```
Estimation window: BETA_WINDOW_DAYS (=120) sessions,
                   ending BETA_GAP_DAYS (=5) sessions before `date`.

r_i,t = ln(adj_close_i,t / adj_close_i,t-1)
r_m,t = ln(adj_close_nifty,t / adj_close_nifty,t-1)
OLS:    r_i,t = alpha + beta * r_m,t + eps_t
Store:  alpha, beta, resid_sd = std(eps, ddof=2), n_obs, r2, quality
```

Guards:
- `n_obs < BETA_MIN_OBS` (=60) → `beta = 1.0`, `alpha = 0.0`,
  `resid_sd = std(r_i)`, `quality = 'DEGRADED'`
- Winsorize both series at the 1st/99th percentile of the estimation window
- Clamp `beta` to `[0.0, 3.0]`
- Floor `resid_sd` at `RESID_SD_FLOOR` (=0.004)

**Why the 5-session gap:** prevents pre-event information leakage from
contaminating the normal-return estimate. Standard event-study practice.

**Why winsorize:** one unadjusted corporate action or data error in the window
would inflate `resid_sd` and permanently mute that symbol.

**Why clamp beta:** a thin stock regressed on the Nifty can produce a beta of 7
from noise, which would make the MARKET_WIDE classifier attribute nearly any move
to the market and suppress everything.

**Vectorised computation `[REVIEW-ACCEPTED]`.** Do not loop per symbol. Build a
wide returns frame (dates × symbols), compute rolling covariance and variance
with pandas, derive `beta = cov/var` across the universe at once. Per-symbol OLS
loops over 2,000 symbols × 250 dates will not finish in an acceptable window.

**Why single-factor and plain OLS** — §23.7 and §23.8. The two-factor sector
model and robust regression were considered and rejected for specific reasons,
not overlooked.

### 8.2 Turnover baseline

```
lt_t        = ln(1 + turnover_t)          # ₹, split-invariant — §7.2
mean_log_to = mean(lt over VOL_WINDOW_DAYS (=20) sessions, excluding `date`)
sd_log_to   = std(same)
```

**Why log:** raw turnover is heavily right-skewed and heteroskedastic across
symbols. Log turnover is approximately normal, so a z-score is meaningful and
comparable between a large cap and a small cap.

### 8.3 Delivery baseline — logit transform `[REVIEW-ACCEPTED]`

```
delivery_pct_t   = deliverable_qty_t / traded_qty_t     ∈ [0,1]
delivery_logit_t = ln((p + eps) / (1 - p + eps))        eps = DELIVERY_LOGIT_EPS (=1e-4)
mean_delivery_logit = mean over DELIVERY_WINDOW_DAYS (=20) sessions
sd_delivery_logit   = std(same)
```

Rows with `traded_qty = 0` are excluded from the window, not zero-filled.

**Why the logit:** delivery percentage is bounded on [0,1] and skewed. A z-score
on a bounded variable is distorted near its bounds — a move from 90% to 95% and
one from 45% to 50% are not comparable on a raw scale, but they are on a logit
scale. This is the standard transform for proportion data and it costs one line.

The raw percentage is still stored and displayed, because "delivery was 76%
against a 20-day average of 41%" is what the user should read. The logit is used
only for the z-score.

### 8.4 Extremes and liquidity

```
high_52w, low_52w   from adj_close, trailing 252 sessions (PRI — §7.2)
adv_20d             average daily turnover (₹), trailing 20 sessions
```

Turnover-based ADV is split-invariant, which is why the liquidity floor in §11.6
uses it rather than share count.

---

## 9. Announcements

### 9.1 Source, schema, dedup

Polled every `ANNOUNCEMENT_POLL_SECONDS` (=180) from 09:00 to 20:00 on trading
days — three minutes balances near-real-time detection against exchange rate
limits.

```sql
CREATE TABLE announcements (
  id             BIGSERIAL PRIMARY KEY,
  symbol         TEXT NOT NULL,
  filed_at       TIMESTAMPTZ NOT NULL,
  subject        TEXT NOT NULL,
  category       TEXT NOT NULL,
  schedule_iii   TEXT,                  -- 'A' | 'B' | NULL
  attachment_url TEXT,
  raw_json       JSONB NOT NULL,
  content_hash   CHAR(64) NOT NULL,     -- [REVIEW-ACCEPTED]
  ingested_at    TIMESTAMPTZ NOT NULL,
  UNIQUE (content_hash)
);
```

**Content hash `[REVIEW-ACCEPTED]`:**
`sha256(normalize(symbol) || normalize(subject) || filed_at.isoformat())`.
Exchanges re-publish identical filings with refreshed timestamps or minor
formatting changes; without this you emit the same signal repeatedly.

### 9.2 Category mapping — structured field first, regex second

**Resolution order. Regex is the fallback, not the primary.** The NSE
announcements payload carries its own category field (`desc` in the JSON —
values such as *Financial Results*, *Change in Directorate*, *Award of Order /
Receipt of Order*, *Credit Rating*). That is a controlled vocabulary maintained
by the exchange, and it is a far better signal than anything we can recover from
free text.

```
1. NSE `desc` field → CATEGORY_FROM_DESC lookup      (exact, normalised match)
2. subject line     → CATEGORY_PATTERNS regex        (fallback)
3. neither matches  → OTHER
```

Build `CATEGORY_FROM_DESC` empirically: after the announcement backfill (Task
2.8), run `SELECT raw_json->>'desc', count(*) GROUP BY 1 ORDER BY 2 DESC` and map
the top values by hand. There are on the order of thirty of them and they cover
the large majority of filings. **This is twenty minutes of work that removes most
of the regex dependency in this module.** Do it before tuning any pattern.

**The regex fallback.** Revision 1 used case-insensitive substring matching.
That is broken: `"loa"` matches *Download*, `"ncd"` matches *Unconditional*,
`"order"` matches *in order to* and *Reorder*. Compile anchored patterns:

```python
CATEGORY_PATTERNS = [
  ("RESULTS",       "A", r"\b(financial|unaudited|audited|quarterly)\s+results?\b"),
  ("BOARD_MEETING", "A", r"\b(board\s+meeting|outcome\s+of\s+board\s+meeting)\b"),
  ("CORP_ACTION",   "A", r"\b(dividend|bonus\s+issue|stock\s+split|sub-?division|buy-?back)\b"),
  ("MNA",           "A", r"\b(acquisition|amalgamation|merger|scheme\s+of\s+arrangement|divestment)\b"),
  ("FUND_RAISE",    "A", r"\b(qip|preferential\s+(issue|allotment)|rights\s+issue|fund\s+rais\w*|ncd|debenture)\b"),
  ("RATING",        "A", r"\b(credit\s+rating|rating\s+action|icra|crisil|care\s+ratings|india\s+ratings)\b"),
  ("KMP_CHANGE",    "A", r"\b(resignation|cessation|appointment\s+of|managing\s+director|chief\s+executive|cfo)\b"),
  ("LITIGATION",    "A", r"\b(litigation|penalt\w+|show\s+cause|tribunal|nclt|adjudication)\b"),
  ("ORDER_WIN",     "B", r"\b(order\s+(win|received|bagged)|letter\s+of\s+award|\bloa\b|new\s+contract|bagged)\b"),
  ("OTHER",        None, r".*"),
]
```

Evaluated in order; first match wins. `OTHER` still counts as an explanation but
gets the smaller multiplier. Being wrong toward "there was *some* filing" is a
safe error; being wrong toward a spurious ORDER_WIN is not.

### 9.3 The linking window — calendar-driven `[REVIEW-ACCEPTED]`

An announcement explains a move on trading date `D` if:

```
filed_at ∈ [ session_close(previous_trading_day(D)),
             session_close(D) + ANNOUNCEMENT_TAIL_MINUTES ]
```

`ANNOUNCEMENT_TAIL_MINUTES` = 180 (up to 18:30 on day D).

**Both bounds come from `trading_calendar`, never from date arithmetic.** A
literal `D − 1 day` breaks across weekends and multi-day holidays: a Friday
evening filing explains Tuesday's open after a Monday holiday, and naive
arithmetic misses it entirely.

**Why this window and not "same calendar day":** SEBI Reg 30(6) sets disclosure
timelines — within 30 minutes of a board meeting closing, within 12 hours for
events arising inside the entity, within 24 hours for events arising outside it.
A filing at 20:00 Monday explains Tuesday's gap, not Monday's. Results cluster
in the evening, so a same-day window would misattribute a large share of them.

### 9.4 Multi-filing resolution `[REVIEW-ACCEPTED]`

A company routinely files board outcome + results + dividend within minutes.
Linking a signal to one arbitrary row is a race condition.

`signal_events.linked_announcement_ids` is a `BIGINT[]`. All filings in the
window are attached, ordered by `filed_at DESC`. The **highest-priority
category** present determines the classification multiplier (Para A beats Para B
beats OTHER). The copy names the most specific one.

### 9.5 Why we do not classify materiality ourselves

SEBI's materiality regime is already quantified: Schedule III Para A events are
*deemed* material with no judgment required; Para B events are tested against
quantitative thresholds — 2% of turnover, 2% of net worth, or 5% of the
three-year average absolute PAT.

For corporate events we need **a parser and a lookup, not a classifier.** The
regulator did the hard part. (Automated Para B verification is not attempted —
§23.9 explains why it is infeasible here, not merely costly.)

---

## 10. The signal engine

### 10.1 Layer 0 — the MPM gate `[REGULATORY]`

SEBI's rumour-verification regime (LODR Reg 30(11)) is triggered by a **Material
Price Movement**. NSE and BSE published the framework on 21 May 2024. It sets a
percentage threshold on the share price move and benchmarks it against the index
— Nifty 50 for NSE-listed entities, Sensex for BSE — on the same trading day.
Percentage variation is calculated against the previous trading day's close, and
the trigger can fire at any point during the day.

| Previous close (₹) | Index move at 09:30 < 1% | Index move at 09:30 ≥ 1% **and** same direction as the stock move |
|---|---|---|
| 0 – 99.99 | ≥ 5% | ≥ (5% + index % change at 09:30) |
| 100 – 199.99 | ≥ 4% | ≥ (4% + index % change at 09:30) |
| 200 and above | ≥ 3% | ≥ (3% + index % change at 09:30) |

Hitting the price band also counts as an MPM in all cases.

```python
def mpm_gate(prev_close, price, index_pct_0930, band_hit) -> MpmResult:
    if   prev_close < 100:  base = 5.0
    elif prev_close < 200:  base = 4.0
    else:                   base = 3.0

    pct = (price - prev_close) / prev_close * 100.0

    if index_pct_0930 is not None and abs(index_pct_0930) >= 1.0 \
       and sign(index_pct_0930) == sign(pct):
        threshold = base + abs(index_pct_0930)
    else:
        threshold = base

    return MpmResult(pct, base, threshold,
                     triggered=abs(pct) >= threshold or band_hit,
                     band_hit=band_hit)
```

**The intraday variant.** For price movement after 09:30, only the
price-range-based variation in the scrip is considered, irrespective of index
movement:

```python
intraday_excursion = max(abs(high - prev_close), abs(low - prev_close)) / prev_close * 100.0
intraday_triggered = intraday_excursion >= base      # base, NOT threshold
```

A stock that swung 6% intraday and closed flat still triggers. No consumer
product surfaces this.

**Why use the regulator's numbers.** Four reasons, the strongest defensive card
in the project:
1. Already index-relative — abnormal-return logic written by the exchange.
2. Price-tier aware. Cheap stocks are noisier and need a wider band; a
   hand-rolled "5% is a big move" gets this wrong across the price spectrum.
3. Covers both the overnight gap and the intraday excursion.
4. Auditable. "Why 3%?" has a circular reference as its answer, not a preference.

### 10.2 Layer 1 — statistical abnormality

**Standardised abnormal return:**

```
AR_T  = r_i,T - (alpha + beta * r_m,T)
SAR_T = AR_T / resid_sd
CAR   = Σ AR_t over the cursor window of n sessions
SCAR  = CAR / (resid_sd * sqrt(n))          # n from trading_calendar
```

**Why standardise:** textbook event-study machinery — estimate a normal-return
model over a pre-event window, take abnormal return as actual minus expected,
weight by statistical precision, which materially boosts test power over
unstandardised tests. In product terms: a 2% move in a low-volatility FMCG name
can and should outrank a 6% move in a small-cap that swings 6% in a normal week.

**Abnormal turnover** (not share volume — §7.2):

```
turnover_z = (ln(1 + turnover_T) - mean_log_to) / max(sd_log_to, LOG_TO_SD_FLOOR)
```

**Why activity at all, and why carefully:** abnormal-volume event studies date to
Beaver (1968) and the event-study logic extends to trading activity, not just
price level. But Barber & Odean identify abnormal volume as one of the primary
attention triggers driving retail buying — so this is the axis to handle with
most care rather than amplify. It carries a smaller weight than SCAR and is never
sufficient alone.

**Abnormal delivery — the India-specific differentiator:**

```
delivery_z = (delivery_logit_T - mean_delivery_logit)
             / max(sd_delivery_logit, DELIVERY_LOGIT_SD_FLOOR)
```

NSE publishes deliverable quantity for every security every evening alongside
the bhavcopy. Delivery % is the fraction of traded volume that actually settled
into demat accounts rather than being squared off intraday — one of very few
India-specific institutional-intent signals that is fully public. High turnover
with low delivery is day traders passing stock between each other; the same move
with high delivery means buyers carried it home.

Measured **relative to the stock's own trailing average**, not an absolute
threshold: very liquid large caps normally run lower delivery percentages, so a
jump versus the stock's own norm is more telling than the absolute level.

**Why this matters to the thesis:** the product separates churn from conviction.
Delivery % is the only public Indian dataset that speaks directly to that, and it
is absent from every mainstream watchlist.

**52-week extremes:** `new_52w_high = adj_close_T >= high_52w` (and the low). A
booster only, never primary. The copy states explicitly that a 52-week high is
not a sell and a 52-week low is not a buy — the item describes state, not action.

### 10.3 Candidate generation

```
mpm.triggered
OR mpm.intraday_triggered
OR abs(SAR)        >= SAR_CANDIDATE_MIN        (=2.0)
OR turnover_z      >= TURNOVER_Z_CANDIDATE_MIN (=2.5)
OR abs(delivery_z) >= DELIVERY_Z_CANDIDATE_MIN (=2.0)
OR new_52w_high OR new_52w_low
OR band_hit
OR has_linked_announcement(category != OTHER)
```

The last clause matters: **a material filing is a candidate even if the price did
not move.** A results announcement the market shrugged at is still something the
holder wants to know happened. This inverts the usual price-first logic.

### 10.4 Signal families

| Family | Fires when | Notes |
|---|---|---|
| `PRICE_MOVE` | MPM close-to-close triggered, or `abs(SCAR) >= SCAR_MIN` | Primary |
| `INTRADAY_SWING` | intraday excursion triggered, close-to-close did not | "Swung 6% and came back" |
| `TURNOVER_SURGE` | `turnover_z >= TURNOVER_Z_CANDIDATE_MIN` | Suppressed if it is the only family and `delivery_z < 0` — pure churn |
| `DELIVERY_SHIFT` | `abs(delivery_z) >= DELIVERY_Z_CANDIDATE_MIN` | Direction matters: high delivery + up is accumulation-shaped, + down is distribution-shaped. **Describe, do not label.** |
| `RANGE_EXTREME` | new 52w high/low | Booster |
| `BAND_HIT` | LTP at a price band | Always surfaced if the user holds it |
| `FILING` | linked announcement, category ≠ OTHER | Fires with or without a price move |
| `CORP_ACTION_NOTICE` | ex-date in the cursor window | Informational, never scored — §11.1 |

### 10.5 Deduplication and refractory period

```python
def should_emit(prev, new_mag, new_sign) -> bool:
    if prev is None:
        return True
    if new_sign != prev.sign:              # [REVIEW-ACCEPTED]
        return True                        # direction reversal is a NEW event
    if new_mag >= prev.magnitude * (1.0 + REFRACTORY_ESCALATION):
        return True
    if hours_since(prev.at) >= REFRACTORY_HOURS:
        return True
    return False
```

**Why the sign-flip clause matters.** Revision 1 gated only on magnitude
escalation. A stock that fell 4% in the morning and rallied 4% in the afternoon
has equal magnitude, so the reversal — arguably the more interesting event — was
silently blocked inside the 24-hour window. A change of direction always resets
the refractory state.

**Why the refractory period exists at all:** without it, a three-day slide
produces three near-identical items and consumes the entire budget.

---

## 11. Classification and suppression

One classification per candidate. First match wins.

### 11.1 `CORPORATE_ACTION` → suppress

```
if exists corporate_action(symbol) with ex_date in [window_start, window_end]:
    classification = CORPORATE_ACTION
    scored = False
    emit CORP_ACTION_NOTICE (informational)
```

**Ex-date open pause `[REVIEW-ACCEPTED]`.** Additionally suppress *all* signal
generation for a symbol from `regular_open` to `regular_open +
EX_DATE_OPEN_PAUSE_MINUTES` (=15) on its ex-date. Broker feeds and exchange
reference prices take minutes to align at open while our baselines are already
adjusted. Three lines of code that prevent an embarrassing demo-time false alarm.

**Why suppression rather than adjust-and-continue.** Even with the adjusted
series correct, the *user's* mental model on an ex-date is anchored to the
as-traded price they last saw. Showing "0% change" against a screen reading
₹1,240 down from ₹2,480 is confusing. The right output is explicit:
*"1:1 bonus, ex-date 14 Aug. Price adjusted from ₹2,480 to ₹1,240. Your holding
value is unchanged."* It does not consume a scored slot.

This is the demo's money shot: the naive view screams −50%, ours explains.

### 11.2 `MARKET_WIDE` → roll up

```
market_component = beta * r_m,T
if abs(market_component) >= MARKET_ATTRIB_RATIO (=0.70) * abs(r_i,T)
   and abs(SAR) < MARKET_SAR_CEILING:
       classification = MARKET_WIDE
```

The `abs(SAR)` ceiling is the high-beta guard: for a β = 2.5 stock a 1% Nifty
move predicts 2.5%, so the ratio test alone would attribute a sharp drop to the
market. The ceiling prevents that. Its value (1.5) is `[TUNED]` and calibrated on
the eval harness — tightening toward 1.0 is a legitimate outcome of calibration,
not a design change.

Rendered once at the top: *"The market was down. Nifty −2.3%. Eleven of your 14
names moved with it."*

**Why:** a stock down 2.1% when the Nifty is down 2.3% is not news about the
stock. Rendering it fourteen times spends fourteen units of attention on one
piece of information.

### 11.3 `SECTOR_WIDE` → heavy downweight

```
peers = active symbols, same sector, with a bar on T (min SECTOR_MIN_PEERS = 4)
sector_median_ar = median(AR of peers)
if sign(AR_i) == sign(sector_median_ar)
   and abs(AR_i - sector_median_ar) < SECTOR_TOLERANCE_SD (=1.0) * resid_sd:
       classification = SECTOR_WIDE
```

Rendered as one grouped line: *"IT fell together — INFY, TCS, WIPRO, HCLTECH all
down 3–4%."*

### 11.4 `EXPLAINED`

Linked announcement, category ≠ OTHER. Highest multiplier, justified by Boudoukh
et al.: identified-news days show continuation while extreme moves on no-news
days show reversal.

### 11.5 `UNEXPLAINED`

Everything else that passed the gates, framed honestly: *"No filing found.
Turnover 3.4× normal, delivery below its own average — activity without a
disclosed cause."*

**Why surface these at all:** they are the highest-uncertainty situations, which
is precisely where Gargano & Rossi found attention most valuable — provided
public information exists to process. We surface them with an honest account of
what we do and do not know.

### 11.6 Liquidity floor with hysteresis `[REVIEW-ACCEPTED]`

```
state ∈ {ACTIVE, SUPPRESSED}, persisted per symbol
ACTIVE     → SUPPRESSED  when adv_20d < SUPPRESS_TURNOVER_FLOOR  (₹80 lakh)
SUPPRESSED → ACTIVE      when adv_20d > ACTIVATE_TURNOVER_FLOOR  (₹1.2 crore)
```

**Why two thresholds rather than one.** A single ₹1 crore cutoff makes a stock
hovering at ₹9.9 lakh / ₹10.1 lakh flicker between suppressed and active day to
day, which is visible and confusing. A hysteresis band with state memory costs
one column and removes the flicker.

**Why a floor at all:** in a stock trading ₹4 lakh a day, a single 500-share
trade moves the price 8%. Every statistic in §10 becomes noise. Surfacing these
points retail attention at the least liquid, most manipulable end of the market.
The UI says so: *"Too thinly traded for us to assess reliably."*

---

## 12. Cursor and state model

### 12.1 The read cursor

```sql
read_cursors(
  user_id, scope_type, scope_id,          -- SYMBOL | WATCHLIST | GLOBAL
  seen_through_ts         TIMESTAMPTZ,
  acknowledged_through_ts TIMESTAMPTZ,
  updated_at, last_device_id,
  PRIMARY KEY (user_id, scope_type, scope_id)
)
```

Merge rule is **`max`**, nothing else:

```sql
ON CONFLICT (user_id, scope_type, scope_id) DO UPDATE SET
  seen_through_ts = GREATEST(read_cursors.seen_through_ts, EXCLUDED.seen_through_ts),
  acknowledged_through_ts = GREATEST(read_cursors.acknowledged_through_ts,
                                     EXCLUDED.acknowledged_through_ts);
```

**Why `max` is provably sufficient.** A last-read pointer merges by "take the
further position" — a max over a total order, which is a join-semilattice:
commutative, associative, idempotent. Concurrent updates from two devices
converge regardless of arrival order, with no conflict-resolution logic.

Not a shortcut. Matrix reached the same conclusion: MSC2285 added a private read
receipt syncing a user's own unread state across their own devices without
reaching other users. Slack, Discord and IRC all solved cross-device read state
the same way. No CRDT, no vector clocks, no OT — §23.2.

### 12.2 Delivered vs acknowledged

`seen_through_ts` advances when a Brief is served. `acknowledged_through_ts`
advances only on explicit user action — expanding an item, opening the symbol
page, or "Mark all as read". The Brief renders against the acknowledged cursor.

**Why:** glancing at the Brief on a laptop should not silently destroy the same
Brief waiting on a desktop.

### 12.3 The watchlist

Server-authoritative. `version` bumped on every mutation. `If-Match` for
optimistic concurrency, 409 with current state on mismatch.

**Fractional indexing** for `position_key` — a lexicographically sortable string
(`a0`, `a0V`, `a1`). Inserting between two items generates a key between theirs;
no reindexing of the list.

**Rebalancing `[REVIEW-ACCEPTED]`.** Repeated insertion at the same point grows
keys without bound (`a0VVVVVVVV1`). If any `position_key` in a list exceeds
`POSITION_KEY_MAX_LEN` (=32), enqueue a background rebalance that re-spaces all
keys in that list uniformly. Cheap insurance against slow degradation.

### 12.4 Idempotency `[REVIEW-ACCEPTED]`

Every mutating request carries an `Idempotency-Key` header. Responses are cached
in Redis at `idempotency:{user_id}:{key}` with `IDEMPOTENCY_TTL_SECONDS`
(=86400). A replayed key returns the original response and applies nothing.

**Why Redis with a TTL rather than a Postgres table:** the keys are write-heavy,
short-lived and worthless after a day. A relational table would bloat with rows
nobody reads.

### 12.5 Client-side cache

The web client renders from a local store, not directly from network responses —
the same model that works for intermittently-connected clients: a local
database, pending mutations, sync cursors, read state, and a persisted last-sync
timestamp so it pulls incremental updates rather than full snapshots.

For this build: TanStack Query with `persistQueryClient` on IndexedDB, a
pending-mutations queue that survives reload and replays with original
idempotency keys, and a reconnect path that pulls `changed_since=<ts>` then
requests a fresh quote snapshot.

### 12.6 Retention

`signal_events` retained `SIGNAL_RETENTION_DAYS` (=90).

**Why 90 and not 7:** someone returning after three weeks must get a
three-week-shaped summary, not an empty screen. This is what makes absence
*increase* the product's value — the entire commercial argument in §22.

---

## 13. Digest and ranking

### 13.1 The score

```
base =  W_SCAR     * clamp(abs(SCAR),          0, 6) / 6
      + W_TURNOVER * clamp(max(turnover_z, 0), 0, 5) / 5
      + W_DELIVERY * clamp(abs(delivery_z),    0, 4) / 4
      + W_EXTREME  * (1.0 if new_52w_high or new_52w_low or band_hit else 0.0)
```

Weights `[TUNED]`: `W_SCAR = 0.45`, `W_TURNOVER = 0.25`, `W_DELIVERY = 0.20`,
`W_EXTREME = 0.10`.

**Be honest about this in the interview.** The MPM thresholds are regulatory and
non-negotiable. These four weights are ours, tuned against the harness rather
than chosen by feel. Distinguishing the two classes of number clearly is itself a
credibility signal; pretending everything is regulation-derived would not survive
scrutiny.

*On `W_EXTREME`.* It is a binary indicator, so a 52-week breakout on 5× turnover
gets the same bump as a stock touching a band briefly. That imprecision is
bounded by the weight itself at 10% of `base`, which is why a continuous
ATR-scaled alternative was considered and rejected — §23.10.

### 13.2 Classification multiplier

| Classification | Multiplier | Why |
|---|---|---|
| `EXPLAINED` (Para A) | 1.35 | Identified news → continuation (Boudoukh et al.) |
| `EXPLAINED` (Para B / OTHER) | 1.15 | Weaker evidence of materiality |
| `UNEXPLAINED` | 1.00 | Baseline |
| `SECTOR_WIDE` | 0.55 | Partly explained by something other than the company |
| `MARKET_WIDE` | 0.25 | Rolled up separately |
| `CORPORATE_ACTION` | 0.00 | Suppressed |

### 13.3 Personal multiplier

Multiplicative, product capped at `PERSONAL_CAP` (=2.0):

| Condition | Multiplier |
|---|---|
| Holds the stock | 1.35 |
| Price level set, not crossed | 1.30 |
| Price level **crossed** in the window | 1.80 |
| Pinned | 1.20 |
| Added < 30 days ago | 1.15 |
| Never opened by this user | 1.10 |

The cap prevents multi-condition inflation — a held, pinned, recently-added
symbol with a crossed level would otherwise reach 3.9×.

**Why "never opened" gets a boost:** a symbol added but never looked at is the
highest-uncertainty item in the user's own list. Gargano & Rossi applied
personally.

### 13.4 Recency decay

```
final = base * classification_mult * personal_mult * exp(-age_sessions / DECAY_TAU_SESSIONS)
```

Age in **trading sessions** from the calendar, never calendar days.

### 13.5 Assembly and the cap

```
1. Load the user's watchlist symbols
2. Load signal_events with as_of > acknowledged_through_ts, not superseded
3. Drop CORPORATE_ACTION scored signals; collect their notices
4. Collapse MARKET_WIDE into one rollup line
5. Collapse SECTOR_WIDE into one grouped line per sector
6. Rank the remainder by `final`, descending
7. Take the top BRIEF_MAX_ITEMS (=5)
8. Emit the quiet line: "N others: nothing notable."
9. Append corporate-action notices, unranked
10. Record the delivery in digest_deliveries with the full funnel counts
```

**The cap is a hard invariant** — a property test asserts it over randomised
states. This is N3.

**Why "N others: nothing notable" is a first-class element, not a footnote:** the
product's claim is that silence is information. It is set at the same type size
as the items. Engagement metrics punish saying nothing, which is exactly why no
incumbent ships it and exactly why it differentiates.

### 13.6 Item copy structure

Four parts, always:
1. **What moved**, relative to the cursor: *"Down 7.2% across the three sessions
   since you last looked."*
2. **How unusual, in this stock's own terms:** *"Its largest three-day
   stock-specific move in 14 months."*
3. **Whether there is a cause:** *"Q2 results, filed Tuesday 18:40."* or
   *"No filing found. The sector moved −0.4%."*
4. **Freshness and confidence:** *"As of 15:29. Delivery data provisional until
   18:30."*

Generated from templates in `digest/copy.py`, never free-form.

---

## 14. Live quotes, freshness, fan-out

### 14.1 Quote source abstraction

```python
class QuoteSource(Protocol):
    async def subscribe(self, symbols: set[str]) -> None: ...
    async def unsubscribe(self, symbols: set[str]) -> None: ...
    def stream(self) -> AsyncIterator[Tick]: ...
    @property
    def heartbeat_age_seconds(self) -> float: ...
```

`BrokerWebSocketSource` (primary), `PollingSource` (fallback).

**Why the abstraction exists before either implementation:** most Indian broker
APIs require an account with that broker, and some require a paid subscription or
same-day app approval. If activation takes 24 hours you lose a third of the
budget. With this interface, swapping is a config change.

### 14.2 The freshness state machine

```
LIVE · DELAYED · STALE_THIN · BAND_LOCKED · HALTED_MARKET
FEED_DOWN · PRE_OPEN · CLOSED · NO_DATA
```

**Benchmark-anchored halt detection `[REVIEW-ACCEPTED — corrects a real bug in
revision 1]`.** Revision 1 declared `HALTED_MARKET` when >90% of subscribed
symbols went silent for 60s. On a watchlist full of illiquid names during the
mid-session lull (roughly 11:30–13:30 IST), that condition fires routinely with
the market wide open.

Fix: **always subscribe to a benchmark anchor** — the index feed, or a
guaranteed-liquid proxy such as NIFTYBEES — regardless of the user's watchlist.
A market-wide halt is declared only when the anchor is *also* silent.

```python
def freshness(symbol, ctx) -> State:
    if ctx.session == "CLOSED":                          return CLOSED
    if ctx.session == "PRE_OPEN":                        return PRE_OPEN
    if ctx.feed_hb_age > FEED_HEARTBEAT_MAX_S:           return FEED_DOWN
    if ctx.silent_frac > MARKET_HALT_SILENT_FRAC \
       and ctx.benchmark_tick_age > MARKET_HALT_MIN_S:   return HALTED_MARKET
    if ctx.tick_age is None:                             return NO_DATA
    if ctx.tick_age > BAND_LOCK_MIN_S and at_band(ctx):  return BAND_LOCKED
    if ctx.tick_age > STALE_THIN_S:                      return STALE_THIN
    if ctx.tick_age > DELAYED_S:                         return DELAYED
    return LIVE
```

**Why this is the hardest part of the data layer.** A halted stock and a broken
feed look identical from the client: a circuit halt is invisible in the data feed
— the stream simply stops for that symbol, with no error, no notification and no
status flag. The last trade prints at the circuit price and then nothing. The
only way to disambiguate is to triangulate: feed heartbeat, the behaviour of the
benchmark anchor, and the price's position relative to its band.

Two India-specific facts encoded here:
- **Market-wide halts** operate in three stages of index movement — 10%, 15%,
  20% — triggered by whichever of Nifty 50 or Sensex breaches first, with halt
  duration depending on the stage and the time of day, and a 20% move halting
  trading for the remainder of the day.
- **A stock hitting its band is not a halt.** For individual stocks, hitting the
  upper band does not halt trading; it means no orders can be placed beyond the
  band, and trading may resume within the band later. `BAND_LOCKED` is a distinct
  state and the copy must never say "halted".

### 14.3 Conflation, backpressure, resync

Per-connection buffer: `dict[symbol, Tick]`, last-value-wins, flushed every
`CONFLATION_INTERVAL_MS` (=400) as one batch.

**Why conflation is correct here, not a compromise:** a watchlist needs latest
state, not every tick. Batching at a fixed interval reduces message count
dramatically during volatile periods, at the cost of at most one interval of
latency. 400ms is invisible to a reader and saves an order of magnitude.

Bounded queue `WS_QUEUE_MAX` (=500), drop-oldest — safe because the stream is
snapshot-recoverable. A connection saturated >30s is disconnected rather than
allowed to degrade the worker.

**Explicit resync protocol `[REVIEW-ACCEPTED, CONCRETISED]`.** Revision 1
specified sequence numbers and "re-request a snapshot on gap" but left the
handshake implicit:

```jsonc
// client → server
{"op":"subscribe","symbols":["RELIANCE"],"req_id":"r1"}
{"op":"unsubscribe","symbols":["TCS"],"req_id":"r2"}
{"op":"resync","last_seen_seq":1042,"req_id":"r3"}
{"op":"ping"}

// server → client
{"type":"snapshot","seq":1042,"data":{"RELIANCE":{...}}}
{"type":"delta","seq":1043,"data":[{"s":"RELIANCE","ltp":2481.5,"ch":12.4,
                                    "chp":0.50,"ts":"...","state":"LIVE"}]}
{"type":"heartbeat","ts":"...","feed_state":"OK"}
{"type":"market_status","session":"REGULAR","banner":null}
{"type":"error","req_id":"r1","code":"SUBSCRIPTION_LIMIT","message":"..."}
```

Client rule: if `incoming.seq != last_seen_seq + 1`, **drop the delta**, set UI
state `RE_SYNCING`, send `resync`. Applying a delta after a gap silently corrupts
local state, which is worse than a visible resync.

**Subscribe to the viewport, not the list.** A 250-name watchlist streams only
rendered rows. Virtualised list, subscription set updated on scroll (debounced
200ms). Server cap `WS_MAX_SUBSCRIPTIONS_PER_CONN` (=60).

### 14.4 The scale argument

**The asymmetry that dictates the architecture:** users are in the millions,
distinct symbols in the low thousands. Groww reported 13.12 million active
clients at 28.9% NSE market share in July 2026, against perhaps 2,000–2,500
meaningfully-watched cash equities.

**Never fan out on write.** Signals are computed per symbol (O(thousands)) and
joined to users at read time. A Nifty-wide move produces ~50 signal rows, not 13
million per-user feed rows. Most users are dormant on any given day.

Built consequences: `signal_events` is keyed by symbol, never by user; the digest
is a read-time join cached per `(user, cursor)` for `BRIEF_CACHE_TTL_SECONDS`
(=60); per-symbol rendered payloads are cached in Redis and shared across every
user watching that symbol — a large fraction of all watchlists contain the same
~200 names, so this cache does most of the work.

**Documented, not built** (§23.3, §23.11): partitioned log instead of Redis
Streams; subject-based pub/sub fan-out with binary payloads; Redis write-behind
for cursor updates. Groww's own 915 team documented needing exactly the first two
— a lightweight, reliable publish-subscribe framework supporting thousands of
clients subscribing to many different instrument ticks simultaneously, chosen
over plain WebSockets for subject-based filtering, client reconnection logic and
server-side load balancing, plus compact binary messages instead of large JSON
payloads. Mirroring the incumbent's validated pattern is a strength in review.

---

## 15. Provisional and final restatement

### 15.1 Lifecycle

```
09:15–15:30  intraday signals from live quotes
             provisional = true, delivery_z = NULL (no data yet)
             turnover figures are partial-session

~18:00       bhavcopy + delivery land
             recompute every signal for today
             revision = previous + 1, previous.superseded_by = new_id
             flag any already-served item as restated
             ── then, atomically ──
             PUBLISH cache:purge "BHAVCOPY_LANDED:<trading_date>"
```

### 15.2 Cache invalidation `[REVIEW-ACCEPTED — corrects a real bug in revision 1]`

Revision 1 specified a 60-second Brief cache (§14.4) and a restatement pipeline,
and never connected them. For up to a minute after restatement, sessions would
read stale provisional data while the database held the final state — the exact
failure restatement exists to prevent.

Fix: on successful EOD batch completion, publish a purge on Redis. Every API
worker subscribes and evicts all `cache:brief:*` entries for that trading date.
The next request rebuilds from the restated rows with `was_restated = true`.

### 15.3 Why restatement exists at all

The bhavcopy publishes in the evening after close, typically from around 16:00
onward, and any daily statistic dated today is only final once that file lands;
delivery data arrives with the end-of-day security-wise file around 18:00.

Any intraday number is provisional by construction. Two honest options: hide
intraday signals, or show and restate. We show and restate, because a watchlist
that goes blind during market hours is useless. The UI says *"Provisional.
Delivery data lands after 18:00,"* and later *"Revised after final exchange
data."*

Almost no consumer product admits its intraday numbers are provisional.
`restatement_rate` becomes a reportable data-quality SLO.

---

## 16. API contract

JSON. RFC 7807 errors. Cursor pagination. ISO 8601 with offset.

```
POST   /api/auth/demo-login            GET /api/me

GET    /api/watchlists                 POST   /api/watchlists
PATCH  /api/watchlists/{id}            DELETE /api/watchlists/{id}
GET    /api/watchlists/{id}/items      POST   /api/watchlists/{id}/items
POST   /api/watchlists/{id}/items/bulk
PATCH  /api/watchlists/{id}/items/{sym}
DELETE /api/watchlists/{id}/items/{sym}

GET    /api/brief?watchlist_id=&as_of=
POST   /api/brief/ack                  POST /api/brief/mark-unread
GET    /api/brief/explain/{signal_id}          ⚠ N1

GET    /api/symbols/search?q=&limit=
GET    /api/symbols/{symbol}
GET    /api/symbols/{symbol}/signals?days=
GET    /api/symbols/{symbol}/candles?tf=1D&from=&to=

GET    /api/market/status              GET /api/quotes?symbols=A,B,C
WS     /ws/quotes

GET    /api/eval/funnel                GET /api/eval/cases
GET    /api/eval/suppression-cases     (compatibility alias)
GET    /api/eval/continuation          GET /api/eval/unparsed-actions
GET    /api/health                     GET /api/metrics
```

### 16.1 `BriefResponse`

```jsonc
{
  "generated_at": "2026-09-05T10:14:22+05:30",
  "cursor": { "acknowledged_through": "2026-08-12T21:04:00+05:30",
              "sessions_elapsed": 17, "calendar_days_elapsed": 24 },
  "headline": "Since you last looked on Tue 12 Aug at 21:04, four things changed.",
  "market_rollup": {
    "present": true,
    "text": "The market fell over this period. Nifty 50 −4.1%. Eleven of your 14 names moved with it.",
    "index_change_pct": -4.1,
    "symbols_attributed": ["HDFCBANK", "ICICIBANK"]
  },
  "items": [{
    "signal_event_id": "se_01J...", "symbol": "TATAMOTORS",
    "company_name": "Tata Motors Ltd", "family": "PRICE_MOVE",
    "classification": "EXPLAINED", "rank": 1, "score": 1.42,
    "what": "Down 7.2% across the three sessions since you last looked.",
    "how_unusual": "Its largest three-day stock-specific move in 14 months.",
    "cause": "Q2 results, filed Tue 18:40.",
    "freshness": "As of 15:29 on 4 Sep. Final.",
    "metrics": { "pct_move": -7.2, "scar": -3.9, "turnover_z": 2.1,
                 "delivery_z": 0.4, "delivery_pct": 0.61,
                 "mpm_triggered": true, "mpm_threshold_used": 3.0 },
    "provisional": false, "revision": 2, "was_restated": true,
    "completeness": ["bars","baseline","delivery","announcements"],
    "linked_announcement_ids": [88213, 88209],
    "links": { "announcement": "https://...",
               "explain": "/api/brief/explain/se_01J..." }
  }],
  "sector_groups": [{ "sector": "IT",
      "text": "IT fell together — INFY, TCS, WIPRO, HCLTECH all down 3–4%.",
      "symbols": ["INFY","TCS","WIPRO","HCLTECH"] }],
  "corporate_action_notices": [{ "symbol": "IDEA", "action_type": "BONUS",
      "ex_date": "2026-08-14",
      "text": "1:1 bonus, ex-date 14 Aug. Price adjusted from ₹2,480 to ₹1,240. Your holding value is unchanged." }],
  "quiet": { "count": 9, "text": "Nine others: nothing notable." },
  "budget": { "candidates_detected": 41, "suppressed_corporate_action": 2,
              "rolled_up_market_wide": 11, "grouped_sector_wide": 4,
              "below_cap": 20, "surfaced": 4, "cap": 5 },
  "data_quality": { "last_bhavcopy_date": "2026-09-04",
                    "delivery_final_through": "2026-09-04",
                    "symbols_below_liquidity_floor": ["XYZ"],
                    "degraded_baselines": [],
                    "index_0930_source": "CAPTURED_LIVE" }
}
```

**The `budget` block is returned on every response and rendered.** It is the
product's own argument made visible: *we looked at 41 things and showed you 4.*

### 16.2 `ExplainResponse` — the N1 endpoint

Returns the full `FactBundle` inputs, every intermediate value (alpha, beta,
resid_sd, n_obs, r2, AR, SAR, CAR, SCAR, turnover_z, delivery_logit,
delivery_z), the MPM tier and threshold used, the classification decision path
with the branch taken at each step, every weight and multiplier, the final score,
the `completeness` set, and the `inputs_hash`.

**Why it exists:** it is the live answer to "why is this ranked second?" Being
able to answer that from the running app is worth more than any feature.

---

## 17. Frontend — React + Vite + JavaScript

### 17.1 The design problem

The thesis is restraint and provenance. The interface must be comfortable saying
"nothing happened" and must never manufacture urgency. A conventional
trading-terminal aesthetic — dark ground, neon red and green, blinking numbers —
would contradict the argument the product is making. So would a SaaS card grid.

### 17.2 Design tokens

**The organising idea: colour is spent on confidence, not on direction.**

On the Brief, price direction is carried typographically — a signed number and a
magnitude bar extending left or right of a centre rule — *not* by red and green.
Colour is reserved for data state: final, provisional, stale. That inversion is
the product thesis rendered as a design decision, and it is what to point at when
the jury asks about the interface.

On the live watchlist table, red and green **are** used for direction, because
fighting that muscle memory helps nobody. The contrast is deliberate: the Brief
is calm, the table looks like a market.

```css
--ground:      #F7F8F6;   /* faintly cool paper — not cream, not white */
--ink:         #16191C;
--ink-muted:   #5C6670;
--rule:        #DDE1DE;
--bar:         #2C4A7C;   /* magnitude bar; direction by side, not hue */

/* state colours — ONLY for data confidence */
--final:       #1F6F5C;
--provisional: #A5761B;
--stale:       #8A8F94;

/* table surface only */
--up:          #0F7B4F;
--down:        #B3261E;
```

**Type.** Two faces with distinct roles.
- **Newsreader** (serif) — the Brief's sentences, 17px / 1.55, max 66ch. Brief
  items are sentences to be *read*, so they get a reading face. Used at body
  size, never as a large display headline.
- **Public Sans** — chrome, labels, table text, and all figures.

Self-hosted via `@fontsource/newsreader` and `@fontsource/public-sans` — no
`next/font`, no CDN dependency at demo time.

**Tabular figures are mandatory `[REVIEW-ACCEPTED]`**, globally on every numeric
container:

```css
.tnum { font-variant-numeric: tabular-nums lining-nums; }
```

Without this, digit widths shift as prices tick and the whole table jitters.

**Layout.** The Brief is a single left-aligned column, max 66ch, items separated
by hairline rules. **No cards on the Brief** — each item is a paragraph, because
that is what it is. Cards would impose equal visual weight on unequal items,
the opposite of what a ranked brief means.

**Motion.** One orchestrated moment: when the cursor moves, items restack with a
220ms reorder. Nothing else animates. Respect `prefers-reduced-motion`.

### 17.3 Render performance `[REVIEW-ACCEPTED]`

Live ticks at a 400ms cadence next to serif paragraph blocks will cause layout
thrashing unless isolated:

1. **`contain: content`** on every live quote row, so a price change cannot
   trigger layout recalculation outside that row.
2. **Memo boundary on `ltp`.** Rows are `React.memo` with a comparator that
   returns false only when `ltp`, `chp`, or `state` changed. The Brief's prose
   components must never re-render because a background quote ticked.
3. **Zustand selector subscriptions** — components subscribe to
   `useQuoteStore(s => s.quotes[symbol])`, never to the whole store.
4. **Virtualised list** (`@tanstack/react-virtual`) with pre-allocated row
   heights so scrolling does not reflow.

### 17.4 Routes

```
/                 → <Navigate to="/brief" replace />
/brief            BriefPage
/watchlist/:id    WatchlistPage
/symbol/:symbol   SymbolPage
/eval             EvalPage
/settings         SettingsPage
*                 NotFound
```

FastAPI serves `index.html` for any unmatched non-`/api` path so deep links work
on refresh.

### 17.5 `/brief` — the hero surface

```
┌────────────────────────────────────────────────────────────┐
│  Since you last looked on Tue 12 Aug at 21:04,             │
│  four things changed.                              [edit]  │
│                                                            │
│  The market fell over this period. Nifty 50 −4.1%.         │
│  Eleven of your 14 names moved with it.                    │
│  ──────────────────────────────────────────────────────    │
│  TATA MOTORS                              −7.2%   ▐▊▊▊▊    │
│  Down 7.2% across the three sessions since you last        │
│  looked. Its largest three-day stock-specific move in      │
│  14 months. Q2 results, filed Tue 18:40.                   │
│  As of 15:29 on 4 Sep · Final              [why this?]     │
│  ──────────────────────────────────────────────────────    │
│  ...three more items...                                    │
│  ──────────────────────────────────────────────────────    │
│  Nine others: nothing notable.                             │
│  ──────────────────────────────────────────────────────    │
│  IDEA — 1:1 bonus, ex-date 14 Aug. Price adjusted from     │
│  ₹2,480 to ₹1,240. Your holding value is unchanged.        │
│  ──────────────────────────────────────────────────────    │
│  We looked at 41 changes and showed you 4.   [see how]     │
└────────────────────────────────────────────────────────────┘
```

**The hero is the cursor sentence.** `[edit]` opens a picker setting "when did I
last look" to any point in the retained history. Not a demo mode — the product's
central concept made directly manipulable, which also means the app demos
correctly at any hour, market open or shut.

**Loading state.** With no SSR, first paint is a skeleton whose layout matches
the loaded state exactly — same column width, same rule positions, same
placeholder count as the last known item count. No content shift.

**"Nine others: nothing notable"** is set at full item size. Not a footnote.

### 17.6 Copy rules — enforced by a build-failing lint

1. **No recommendations.** Banned: `buy`, `sell`, `should`, `consider`,
   `opportunity`, `target price`, `undervalued`, `overvalued`, `bullish`,
   `bearish`. A test greps `digest/copy.py` and the frontend string modules.
2. **No urgency.** No `act now`, `don't miss`, `hurry`, no exclamation marks.
3. **Describe, don't label.** "Delivery was 76% against a 20-day average of 41%"
   — not "institutional accumulation detected".
4. **Every number carries its as-of time and provisional status.**
5. **Sentence case.** No ALL-CAPS labels.
6. **Active voice.** "We suppressed this", not "this was suppressed".
7. **Empty states are direction, not mood.** "Nothing notable in your list this
   week. Add symbols to widen what we watch." — not "All quiet! 🎉".
8. **Errors say what happened and what to do.** "The exchange file for 4 Sep has
   not arrived. Showing 3 Sep. Retrying at 19:00."
9. **English only.** String literals in the codebase. No i18n framework.

---

## 18. The evaluation harness

**This is what moves the submission from "good build" to "shortlisted".** Almost
nobody builds measurement, and it converts the argument from an opinion into a
result.

### 18.1 Replay

`compute_signals` across `EVAL_SYMBOLS` (≈200 liquid names) × `EVAL_DAYS`
(≈126 sessions) ≈ 25,000 stock-days. The same code path as production with a
different `as_of` — that is what the purity contract buys.

### 18.2 The funnel

```
25,200  stock-days evaluated
18,400  had a non-zero price change
 2,140  cleared the exchange's own MPM threshold
   610  survived index adjustment as stock-specific
   143  suppressed as corporate-action artefacts
   287  classified market-wide or sector-wide and rolled up
   467  would have been surfaced under the cap
```

**This chart is the product.** It shows in one image that the system's job is
subtraction. Each step must be a strict subset of the previous — assert it.

### 18.3 Suppression case studies

Three verified real ex-dates, side by side: the naive view's −50% red number
against our silence plus the notice. Stored as fixtures so they render
identically every time. The demo's strongest 15 seconds.

### 18.4 The continuation test — the research result

Forward 5-session market-model-adjusted return for every surfaced signal, grouped
by classification:

```
                 n      mean fwd 5d AR    median    % same-direction
EXPLAINED      218          ?               ?             ?
UNEXPLAINED    249          ?               ?             ?
```

Boudoukh et al. predict continuation on identified-news days and reversal on
extreme moves with no news. **If the Indian-data result reproduces that
asymmetry, you have empirically validated your own ranking criterion on the
market you are building for.**

If it does not reproduce, report the null result honestly with the numbers and
discuss why. Reporting a null correctly is still stronger than not measuring.

### 18.5 The self-audit

Five items the system surfaced that, on inspection, it probably should not have.
Volunteering your own false positives is the strongest credibility move available
and it pre-empts the jury finding them.

---

## 19. Operations

### 19.1 Scheduling (IST, all calendar-gated)

| Job | Schedule |
|---|---|
| Corporate actions refresh | 07:00 daily — before the session, so ex-dates are known |
| CA factor verification | 07:15, for yesterday's ex-dates |
| Index 09:30 snapshot | 09:30:05 trading days |
| Announcement poll | every 3 min, 09:00–20:00 trading days |
| Signal evaluation (subscribed symbols) | every 30s during REGULAR |
| Bhavcopy + delivery ingest | 18:00, retry 18:30 / 19:00 / 20:00, escalate 20:30 |
| Factor + baseline recompute | after successful ingest |
| EOD signal recompute + restatement + cache purge | after baselines |
| Calendar refresh | weekly |
| Symbol master snapshot | nightly |

APScheduler in-process for the timebox; documented as a cron/Celery-beat swap.

### 19.2 Observability

```
swl_ingest_last_success_timestamp{source}   swl_ingest_rows_total{source}
swl_ingest_quarantined_total{reason}
swl_signal_events_total{family,classification}
swl_signals_suppressed_total{reason}
swl_brief_items_surfaced   swl_brief_candidates_total
swl_restatement_rate
swl_ws_connections  swl_ws_dropped_messages_total  swl_ws_resyncs_total
swl_quote_staleness_seconds{state}   swl_feed_heartbeat_age_seconds
swl_sector_coverage_ratio  swl_ca_unparsed_total  swl_ca_discrepancy_total
swl_ca_parse_coverage_ratio          swl_ca_inferred_total
swl_announcement_desc_hit_ratio      swl_announcement_regex_fallback_total
swl_announcement_other_ratio
nse_http_requests_total{endpoint,status}   nse_breaker_state
```

`/api/health` returns per-dependency status plus `last_bhavcopy_date`, and 503s
if the last successful bhavcopy is more than 2 trading days old.

### 19.3 Deployment

`docker compose up` brings up postgres, redis, backend-api (which also serves the
built SPA), backend-worker, backend-feed. `make seed` loads the cached NSE files
and runs the full pipeline so a fresh clone reaches a working demo **with no
network access.** Test this on a clean machine before the deadline.

---

## 20. Data model additions

```sql
CREATE TABLE signal_events (
  id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL, as_of TIMESTAMPTZ NOT NULL, trading_date DATE NOT NULL,
  window_start TIMESTAMPTZ, window_end TIMESTAMPTZ,
  family TEXT NOT NULL, classification TEXT NOT NULL,
  sign SMALLINT NOT NULL,                      -- refractory sign-flip  §10.5
  pct_move NUMERIC(12,6), ar NUMERIC(18,10), sar NUMERIC(12,6),
  car NUMERIC(18,10), scar NUMERIC(12,6),
  turnover_z NUMERIC(12,6), delivery_z NUMERIC(12,6), delivery_pct NUMERIC(8,5),
  mpm_triggered BOOLEAN, mpm_base_threshold NUMERIC(6,3),
  mpm_effective_threshold NUMERIC(6,3), band_hit BOOLEAN,
  linked_announcement_ids BIGINT[],            -- multi-filing  §9.4
  explained_by_ca_id BIGINT,
  score_base NUMERIC(12,6),
  completeness TEXT[] NOT NULL,                -- FactBundle completeness §4.2
  provisional BOOLEAN NOT NULL,
  revision INT NOT NULL DEFAULT 1,
  superseded_by TEXT REFERENCES signal_events(id),
  inputs_hash CHAR(64) NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON signal_events (symbol, as_of DESC) WHERE superseded_by IS NULL;

CREATE TABLE symbol_liquidity_state (          -- hysteresis  §11.6
  symbol TEXT PRIMARY KEY,
  state TEXT NOT NULL DEFAULT 'ACTIVE',
  changed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE ingest_runs (
  id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, target_date DATE,
  status TEXT NOT NULL,                        -- OK|FAILED|ESCALATED|SKIPPED_CACHED
  rows INT, file_hash CHAR(64),
  started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, error TEXT
);

CREATE TABLE daily_bars (
  symbol TEXT, date DATE,
  open NUMERIC(18,4), high NUMERIC(18,4), low NUMERIC(18,4),
  close NUMERIC(18,4), prev_close NUMERIC(18,4), vwap NUMERIC(18,4),
  volume BIGINT, turnover NUMERIC(24,4), trades BIGINT,
  upper_band NUMERIC(18,4), lower_band NUMERIC(18,4),
  series TEXT, source TEXT NOT NULL, ingested_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (symbol, date)                   -- NOT (symbol, date, series) — §6.2
);
```

Plus `delivery_stats`, `index_snapshots_0930`, `baselines`, `users`,
`watchlists`, `watchlist_items`, `read_cursors`, `digest_deliveries`,
`signal_feedback` as specified inline above.

**Provenance columns are mandatory.** Every fact table carries `source` and
`ingested_at`; every derived table carries `computed_at`. This is N2.

**Dual listing — documented, not built.** Over 5,000 stocks are listed on BSE and
over 3,200 also on NSE, so many smaller companies are thinly traded on at least
one venue and stale quotes there produce visible mismatches. Policy encoded via
`instruments.primary_venue`: one primary venue per symbol chosen by trailing
liquidity, always labelled, never silently mixed, divergence treated as a
data-quality signal. Only NSE is ingested; state this in the README.

---

## 21. Constants registry — **THE LAW**

Implement verbatim in `backend/app/constants.py`. Nothing numeric appears
anywhere else in the codebase.

```python
# ─── [REGULATORY] — NEVER CHANGE ────────────────────────────────────────────
# Framework on Material Price Movement (Equity Cash Markets), NSE/BSE,
# 21 May 2024, under SEBI LODR Reg 30(11).
MPM_TIER_THRESHOLDS = ((100.00, 5.0), (200.00, 4.0), (float("inf"), 3.0))
MPM_INDEX_ADJUST_MIN_PCT = 1.0
MPM_INDEX_SNAPSHOT_TIME  = "09:30"
MPM_INTRADAY_USES_INDEX  = False

# SEBI LODR Reg 30(6) disclosure timelines
REG30_BOARD_MEETING_MINUTES = 30
REG30_INTERNAL_EVENT_HOURS  = 12
REG30_EXTERNAL_EVENT_HOURS  = 24

# NSE/BSE index-based market-wide circuit breaker stages
MARKET_CIRCUIT_STAGES_PCT = (10.0, 15.0, 20.0)

# Session defaults, IST (trading_calendar overrides per date)
SESSION_PRE_OPEN_START = "09:00"
SESSION_OPEN           = "09:15"
SESSION_CLOSE          = "15:30"

# ─── [TUNED] — ours; change only via the eval harness ───────────────────────
CANONICAL_FLOAT_DP = 8

# Market model
BETA_WINDOW_DAYS = 120
BETA_GAP_DAYS    = 5
BETA_MIN_OBS     = 60
BETA_MIN, BETA_MAX = 0.0, 3.0
RESID_SD_FLOOR   = 0.004
WINSOR_PCT       = 0.01

# Rolling baselines
VOL_WINDOW_DAYS      = 20
DELIVERY_WINDOW_DAYS = 20
EXTREME_WINDOW_DAYS  = 252
LOG_TO_SD_FLOOR         = 0.15
DELIVERY_LOGIT_EPS      = 1e-4
DELIVERY_LOGIT_SD_FLOOR = 0.15

# Candidate gates
SAR_CANDIDATE_MIN        = 2.0
TURNOVER_Z_CANDIDATE_MIN = 2.5
DELIVERY_Z_CANDIDATE_MIN = 2.0
SCAR_MIN                 = 2.0

# Classification
MARKET_ATTRIB_RATIO = 0.70
MARKET_SAR_CEILING  = 1.5
SECTOR_MIN_PEERS    = 4
SECTOR_TOLERANCE_SD = 1.0
SUPPRESS_TURNOVER_FLOOR    = 8_000_000     # ₹80 lakh   — hysteresis low
ACTIVATE_TURNOVER_FLOOR    = 12_000_000    # ₹1.2 crore — hysteresis high
EX_DATE_OPEN_PAUSE_MINUTES = 15

# Corporate actions
CA_VERIFY_TOLERANCE     = 0.08
CA_INFER_SNAP_TOLERANCE = 0.02
SUMMARY_MAX_CHARS       = 180
CA_CLEAN_FACTORS = (      # standard bonus ratios and face-value splits
    0.1, 0.125, 1/6, 0.2, 0.25, 1/3, 0.4, 0.5, 0.6, 0.625,
    2/3, 0.7, 0.75, 0.8, 5/6, 2.0, 5.0, 10.0,
)

# Announcements
ANNOUNCEMENT_TAIL_MINUTES = 180
ANNOUNCEMENT_POLL_SECONDS = 180

# Dedup
REFRACTORY_HOURS      = 24
REFRACTORY_ESCALATION = 0.50

# Ranking
W_SCAR, W_TURNOVER, W_DELIVERY, W_EXTREME = 0.45, 0.25, 0.20, 0.10
MULT_EXPLAINED_A   = 1.35
MULT_EXPLAINED_B   = 1.15
MULT_UNEXPLAINED   = 1.00
MULT_SECTOR_WIDE   = 0.55
MULT_MARKET_WIDE   = 0.25
MULT_CORP_ACTION   = 0.00
MULT_HOLDING       = 1.35
MULT_LEVEL_SET     = 1.30
MULT_LEVEL_CROSSED = 1.80
MULT_PINNED        = 1.20
MULT_RECENT_ADD    = 1.15
MULT_NEVER_OPENED  = 1.10
PERSONAL_CAP       = 2.00
DECAY_TAU_SESSIONS = 5.0

# The budget — N3
BRIEF_MAX_ITEMS         = 5
BRIEF_CACHE_TTL_SECONDS = 60

# Freshness (seconds)
FEED_HEARTBEAT_MAX_S    = 10
DELAYED_S               = 15
BAND_LOCK_MIN_S         = 60
STALE_THIN_S            = 300
MARKET_HALT_SILENT_FRAC = 0.90
MARKET_HALT_MIN_S       = 60
BAND_PROXIMITY_PCT      = 0.001

# Realtime
CONFLATION_INTERVAL_MS        = 400
WS_QUEUE_MAX                  = 500
WS_MAX_SUBSCRIPTIONS_PER_CONN = 60
POLL_INTERVAL_SECONDS         = 5
SIGNAL_EVAL_INTERVAL_SECONDS  = 30

# Ingest
NSE_MAX_ATTEMPTS       = 5
NSE_BREAKER_FAILURES   = 3
NSE_BREAKER_COOLDOWN_S = 300
ROW_COUNT_DEVIATION    = 0.20
ACTIVE_ROW_FLOOR_FRAC  = 0.98
QUARANTINE_ABORT_FRAC  = 0.02

# State
POSITION_KEY_MAX_LEN    = 32
IDEMPOTENCY_TTL_SECONDS = 86_400
SIGNAL_RETENTION_DAYS   = 90

# Eval
EVAL_SYMBOLS = 200
EVAL_DAYS    = 126
```

---

## 22. The business case

**The industry's problem is activation, not acquisition.** In July 2026 total
demat accounts rose 1.25% to 234.4 million while active NSE clients fell 1.8% —
accounts keep opening, but a shrinking share of holders trade in any given month.
Active accounts peaked at 49.6 million in January 2025 and the industry has since
seen roughly a 10.5% decline. Even the leader is not immune: Groww held 28.72%
share with 1.30 crore active clients in June 2026 and still lost about 6,000
active clients that month.

**This is a dormancy-reactivation surface, and it is the only kind of engagement
feature that gets *more* valuable the longer someone stays away.** A price alert
is worthless to someone who has not opened the app in six weeks. A six-week Brief
is worth more than a one-day Brief. That property maps onto the exact metric the
industry is losing on.

**Revenue mix.** Digital brokers lean on F&O revenue and SEBI is compressing it:
net losses of individual F&O traders widened 41% to ₹105,603 crore in FY25, over
91% of traders lost money, and unique F&O traders fell from 61.4 lakh in Q1 FY25
to 42.7 lakh in Q4 after measures including fewer weekly expiries and larger lot
sizes. A cash-equity attention surface is aligned with where the regulator is
pushing the industry.

**Restraint is becoming a compliance asset.** With the FCA quantifying
notification harm and IOSCO reviewing digital engagement practices, "we cap what
we surface and deliberately suppress non-informative salience" stops being a
growth cost.

**Metrics to propose.** Not sessions or DAU:

| Metric | Definition |
|---|---|
| Brief precision | of items surfaced, the fraction the user opened |
| Suppression ratio | candidates detected ÷ items surfaced |
| Dormant return rate | users inactive 14+ days who returned via a Brief |
| Restatement rate | provisional signals later revised — a data-quality SLO |

---

## 23. Considered and rejected

Put this in the README. Documenting what you did not build reads better than
reaching for the complicated tool.

**23.1 No learned ranker in the scoring path.**

First, a naming correction that matters for how this is presented. **This is a
transparent statistical model.** The scoring path is event-study econometrics: an OLS market
model estimated over 120 sessions with a 5-session leakage gap, abnormal returns
standardised by residual volatility, multi-day CAR aggregated with the correct
`sqrt(n)` scaling, logit-transformed z-scores on a bounded variable,
winsorisation, beta clamping and variance floors. That is a quantitative model.
It is transparent, which is a property, not an absence of one. Describe it as an
explainable quantitative model.

**Why not a learned ranker.** Three reasons, in order of force:

1. **There is no label.** Ranking is a supervised problem and on day one there
   are zero interaction events. Any submission claiming a learned ranker has
   either invented a synthetic target or is doing something else and calling it
   ranking. If the target is forward return, it is no longer a watchlist — it is
   a return-prediction model, which on a retail broker surface is an unregistered
   advice engine. Be ready to make this point: the right question to a competing
   "ML ranker" is *trained on what target, and labelled by whom?*
2. **The output must be defensible line by line.** The jury will ask why an item
   is second. A gradient-boosted score cannot answer that. `/api/brief/explain`
   can, and does, live.
3. **The FCA evidence.** An unexplainable model on a surface that measurably
   shifts retail trading behaviour is a liability, not a credential.

**Why not unsupervised anomaly detection either** — the obvious "but you don't
need labels for isolation forests" objection. An isolation forest or autoencoder
over `(return, turnover, delivery)` would surface broadly the same outliers, and
lose three things we need: a decomposable score (the copy says *"volume 3× normal
but delivery below its own average"* — that sentence requires separated
components), a unit the user can reason about (3.9σ), and any tie between a
threshold and a regulation. It is strictly worse for this product, not simpler
and worse in an acceptable way.

**The v2 that this becomes.** Be able to sketch it on demand, because designing
the system you chose not to build demonstrates more than shipping a bad version
of it: label = Brief-item opens, logged per impression with rank position;
correct for position bias with inverse-propensity weighting, since rank 1 gets
opened regardless of quality; hold the current score as a feature so the model
learns a residual re-rank rather than replacing the statistics; evaluate offline
against the existing replay harness before it ever touches a user; keep the
regulatory floor (§10.1) outside the model permanently, so no learned component
can suppress something the exchange considers material.

**23.2 No CRDTs.** The read cursor is a max over a total order — already a
join-semilattice. The watchlist has one writer and near-zero concurrency. CRDT
metadata overhead and tombstone growth buy nothing here.

**23.3 No Kafka.** Redis Streams with consumer groups covers ordered, replayable,
per-symbol delivery at this scale and is already a dependency. The consumer
interface is abstracted so the swap is a class, not a rewrite.

**23.4 No custom charting.** Groww integrated TradingView's library rather than
building from scratch; `lightweight-charts` is the same reasoning.

**23.5 No SCD Type 2 symbol master.** Correct for institutional point-in-time
reconstruction, but it adds an `as_of` predicate to every reference-data query
including inside the pure loader. Nightly JSONB snapshots give the same audit
trail at zero query cost, and the data exists to retrofit properly later.

**23.6 No Playwright.** `curl_cffi` covers TLS fingerprint impersonation with one
dependency. A headless browser is a heavyweight answer to a problem a small
library solves.

**23.7 No two-factor (market + sector) model.** Statistically better, but it folds
sector co-movement into the residual — which **destroys the "IT fell together"
grouping** the product's UX depends on. A single-factor model plus an explicit
sector classifier is *more explainable*, and explainability is the pitch. v2,
only if the grouping is preserved separately.

**23.8 No robust regression or EWMA/GARCH residual volatility.** Winsorization at
1/99 plus the residual-SD floor already bound outlier influence. OLS with a
constant estimation-window sigma is MacKinlay's market model — the textbook
standard. Defending a non-standard estimator costs more in review than it gains
in fit.

**23.9 No PDF extraction for Para B verification.** Not merely expensive —
**infeasible here.** Para B materiality is tested against 2% of turnover, 2% of
net worth, or 5% of three-year average PAT, and we do not ingest company
financials. Without them, extracting a contract value from a PDF proves nothing.

**23.10 No ATR-scaled extreme factor.** `W_EXTREME` is 10% of `base`, so the
imprecision of a binary flag is bounded at 10% of one of four terms. Adding an
ATR computation and another unbounded ratio to shave that is a bad trade.

**23.11 No Redis write-behind cursors, no WS cursor sync, no cap-tier grouping,
no residential proxies, no object-storage cache, no human-in-the-loop queue.**
All correct at Groww's scale; all invisible in a single-user demo. Documented as
the scale path, which is worth more in an interview than half-built versions.

**23.12 Where models *are* used — two scoped places, both outside scoring.**

The position is not "no ML." It is that models sit outside the path that
produces a number. Drawing that line explicitly, and being able to say where it
is and why, is a stronger answer than either using a model everywhere or
refusing on principle.

**(a) Filing summarisation — `P1`, the highest-visibility use.** An LLM rewrites
an *already-detected, already-linked* filing into one sentence for the `cause`
line of a Brief item. Templates cannot do this well for arbitrary filings; this
is the one place generation genuinely beats string formatting.

Hard boundaries, enforced in code:
- Input is the filing subject, category and body text **only**. No prices, no
  z-scores, no rank.
- Output is prose, validated before it is stored or rendered. Three gates: any
  digit not present in the input fails; any word from the banned-copy list
  (§17.6) fails; anything over `SUMMARY_MAX_CHARS` fails. On any failure the
  sentence is discarded and the template is used.
- **The banned-copy list is enforced here at runtime, not only by the build-time
  lint.** The lint greps template modules and cannot see generated text, so this
  is the only check standing between a model and a recommendation reaching a
  user. It is the single most important line in this subsection.
- It runs **after** scoring and ranking. It cannot influence either.
- Every generated sentence is stored with its source filing, prompt and model
  version, and is rendered with a visible "summarised from the filing" marker.
- If the call fails or times out, fall back to the template. The Brief never
  blocks on it.

**(b) Residual category classification — `P2`.** After the `desc` lookup and the
regex fallback (§9.2), whatever lands in `OTHER` can be classified by a model.
This is a well-posed classification task: hand-label 200 filings, measure
accuracy, report it. It affects a multiplier (1.35 vs 1.15), never a number the
user sees.

**What stays permanently outside any model:** the MPM gate, all abnormality
statistics, all classification that drives suppression, the ranking score, and
the cap. Those are the parts a regulator, a jury or a user might reasonably ask
you to justify — and they are all justifiable by hand.

---

## 24. Failure modes catalogue

| Failure | Detection | Handling |
|---|---|---|
| Bhavcopy late/missing | `last_bhavcopy_date` stale | Banner naming the date; dependent jobs paused; escalate at 20:30 |
| Bhavcopy truncated | active-symbol floor + rolling median | Abort, quarantine, do not commit |
| File corrupted in transit | SHA-256 mismatch | Re-fetch; never parse an unverified file |
| Unparsed / composite / discrepant CA | `verification != VERIFIED` | Suppress the window anyway — fail safe |
| Missing 09:30 index snapshot | gap in `index_snapshots_0930` | Broker candle, else `ESTIMATED_FROM_OPEN` + flag on every derived signal |
| Broker feed dies | heartbeat > 10s | `FEED_DOWN`, dim prices, fall back to polling |
| Stock at price band | no ticks + LTP at band | `BAND_LOCKED` — copy says "locked at the band", never "halted" |
| Market-wide halt | silent fraction **and** benchmark anchor silent | `HALTED_MARKET` banner naming the stage |
| Illiquid symbol | hysteresis state `SUPPRESSED` | No scored signals; "too thinly traded to assess reliably" |
| Degraded beta | `n_obs < 60` | `quality='DEGRADED'`, beta forced to 1.0, shown in explain |
| Missing sector | `sector = 'UNASSIGNED'` | Cannot classify SECTOR_WIDE; tracked as coverage metric |
| Stale Brief after restatement | — | Redis purge on `BHAVCOPY_LANDED` |
| WS sequence gap | `seq != last + 1` | Client drops delta, shows `RE_SYNCING`, sends `resync` |
| Position key growth | length > 32 | Background rebalance of that list |
| Duplicate ingest | `ON CONFLICT` + file hash | Idempotent; both attempts in `ingest_runs` |
| Clock / date confusion | — | IST has no DST; all dates via `ist_trading_date()` |

---

## 25. References

**Investor attention**
1. Barber & Odean, "All That Glitters," *RFS* 21(2), 2008 — https://academic.oup.com/rfs/article-abstract/21/2/785/1607197
2. Gargano & Rossi, "Does It Pay to Pay Attention?" *RFS* 31(12), 2018 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2846149
3. Boudoukh, Feldman, Kogan & Richardson, "Which News Moves Stock Prices?" NBER 18725 — https://www.nber.org/papers/w18725

**Regulatory evidence on notification design**
4. FCA Research Note, trading apps experiment — https://www.fca.org.uk/publications/fca-research/research-note-digital-engagement-practices-trading-apps-experiment
5. FCA press release, June 2024 — https://www.fca.org.uk/news/press-releases/fca-keeps-trading-apps-under-review-over-gaming-concerns
6. FCA Occasional Paper 66 — https://www.fca.org.uk/publication/occasional-papers/op66-digital-engagement-practices-investment-outcomes.pdf
7. IOSCO FR/07/2025 — https://www.iosco.org/library/pubdocs/pdf/IOSCOPD794.pdf

**SEBI and Indian market structure**
8. Material Price Movement framework, threshold table — https://vinodkothari.com/2024/05/amendment-in-market-rumour-2024/ · NSE circular: https://nsearchives.nseindia.com/content/circulars/SURV62122.zip
9. SEBI unaffected-price framework — https://www.sebi.gov.in/legal/circulars/may-2024/framework-for-considering-unaffected-price-for-transactions-upon-confirmation-of-market-rumour_83483.html
10. Reg 30 / Schedule III thresholds and timelines — https://www.assocham.org/uploads/files/ISF%20Reg%2030%20Note.pdf
11. NSE corporate-action adjustments — https://www.nseindia.com/static/products-services/equity-derivatives-corporate-actions-adjustments
12. Price bands and circuit breakers — https://support.geojit.com/support/solutions/articles/89000007110-what-are-price-bands-and-circuit-breakers-
13. SEBI F&O study — https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html
14. SEBI FY25 F&O update — https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html
15. NSE/BSE dual-listing divergence — https://www.multibagg.ai/market-pulse/articles/nse-bse-price-gap-arbitrage-cmrc1ycqt9vm7qc0jsganbmfa

**Delivery data**
16. NSE bhavcopy and deliverable quantity — https://volumelens.com/learn/nse-bhavcopy-explained/
17. Delivery % as churn-vs-conviction — https://strota.in/screens/high-delivery-stocks · https://bottomstreet.com/learn/delivery-percentage-stocks-nse/

**Event-study methodology**
18. Event study step by step — https://www.eventstudytools.com/introduction-event-study-methodology
19. Significance tests (Patell Z, BMP) — https://www.eventstudytools.com/significance-tests
20. Expected-return models — https://www.eventstudytools.com/expected-return-models

**Competitive landscape**
21. Groww Engineering, "Building 915" — https://tech.groww.in/building-915-inside-growws-high-performance-trading-terminal-d2f05c46a9c7
22. Zerodha, new Kite Marketwatch — https://zerodha.com/z-connect/featured/introducing-new-marketwatch-on-kite
23. Kite marketwatch docs — https://kite.trade/docs/kite/marketwatch/
24. Apple Stocks feature set — https://apps.apple.com/tr/app/borsa/id1069512882
25. MarketBeat watchlist improvements — https://www.marketbeat.com/press-room/marketbeat-announces-improved-watchlist-features/

**Business context**
26. India broking market, June 2026 — https://startuptalky.com/india-stock-broking-market-june-2026-analysis/
27. Groww 28.9% share, July 2026 — https://www.whalesbook.com/news/English/brokerage-reports/Groww-Market-Share-Hits-289percent-in-July-2026-Beats-Peers/6a82aa636ffbe1e6461f0735
28. Active-client trend data — https://comparebroker.info/data/

**Systems**
29. Snapshot+delta, conflation, fan-out — https://hosseinnejati.medium.com/market-data-distribution-order-book-snapshots-deltas-and-websocket-feed-design-466ba56a0c23
30. Streaming market data at scale — https://medium.com/@akhilvpsharma/system-design-real-time-stock-market-data-streaming-at-scale-2ee276619ba9
31. Read cursor as a join-semilattice; Matrix MSC2285 — https://github.com/freenet/river/issues/460
32. Local-DB-first sync, cursors, pending mutations — https://seankim.dev/blog/design-slack-for-mobile-engineers/
33. Slack incremental sync — https://systemdesign.one/slack-architecture/
34. Circuit halts are invisible in the feed — https://blog.infoway.io/en/india-stock-market-api-real-time-nse-and-bse-data-for-developers/

---

## 26. Review ledger (revision 1 → 2)

Every external review item, with the verdict and where it landed. Keep this in
the repo — being able to show a reasoned accept/reject ledger is itself evidence
of engineering judgement.

### Accepted — these were genuine defects in revision 1

| Item | Section | Note |
|---|---|---|
| Word-boundary regex for categories | 9.2 | Substring matching mis-tagged `loa` in *Download*, `ncd` in *Unconditional* |
| Turnover instead of share volume | 7.2, 8.2, 10.2 | Split/bonus invariant; deletes a bug class for free |
| PRI vs TRI — no dividend price adjustment | 5.3, 7.1 | Revision 1 was wrong; would have disagreed with every public quote site |
| Benchmark anchor for halt detection | 14.2 | Revision 1 false-positived on illiquid watchlists mid-session |
| Cache purge on bhavcopy landing | 15.2 | Revision 1 never connected the Brief cache to restatement |
| Refractory reset on sign flip | 10.5 | Magnitude-only rule silently blocked reversals |
| Canonical JSON for `inputs_hash` | 4.2 | `json.dumps` cannot serialise numpy/Decimal; float repr unstable — breaks N1 |
| Logit transform on delivery % | 8.3 | z-score on a bounded variable is distorted near its bounds |

### Accepted — genuine improvements

Session-state calendar (5.2) · adjustment-factor table instead of row rewriting
(7.1) · multi-filing arrays (9.4) · calendar-driven linking window (9.3) ·
quarantine DLQ (6.2) · active-symbol row floor (6.2) · file content hash (6.2) ·
403/429 circuit breaker and `curl_cffi` tier (6.3) · NSE client metrics (6.3) ·
liquidity hysteresis (11.6) · idempotency TTL in Redis (12.4) · fractional-index
rebalancing (12.3) · ex-date open pause (11.1) · FactBundle completeness (4.2) ·
cold/hot bundle split (4.2) · ex-date IST alignment (4.3) · sector fallback chain
(5.1) · surrogate `instrument_id` plus aliases (5.1) · vectorised baselines (8.1)
· announcement content hash (9.1) · explicit resync op (14.3) · `contain: content`
and memo boundaries (17.3) · backfill priority matrix and retry escalation (6.1).

### Adapted

**Dual-source CA verification** → no free second source exists, so verify the
parsed factor **empirically against the observed ex-date gap** (5.3). Cheaper,
and uses data already on disk.

### Rejected — with reasons

Composite PK including `series` (**incorrect** — would permit the duplicates it
aims to prevent; §6.2) · two-factor sector model (23.7) · robust regression,
EWMA, GARCH (23.8) · SCD Type 2 (23.5) · UUID keys on fact tables (5.1) ·
`instrument_listings` table (BSE out of scope) · PDF extraction for Para B (23.9)
· ATR extreme factor (23.10) · Playwright (23.6) · residential proxies,
object-storage cache, HITL queue, PagerDuty, Redis write-behind cursors, WS
cursor sync, cap-tier grouping (23.11) · formal CA grammar parser (composite
detection plus suppression is sufficient; 5.3) · `t±30min` announcement window
(redundant with the calendar-driven window; 9.3).

### Already present in revision 1

`MARKET_SAR_CEILING` high-beta guard (11.2) · `PERSONAL_CAP` (13.3) ·
snapshot+delta with gap recovery (14.3) · turnover-based ADV (8.4) · homepage
warmup and cookie refresh (6.3).
