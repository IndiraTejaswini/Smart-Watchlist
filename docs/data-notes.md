# Data source notes

Observed behaviour of the NSE endpoints, recorded as it is discovered so that
later phases do not have to rediscover it. Each entry states what was measured,
not what was assumed (R3).

---

## The delivery endpoint serves stale data on exchange holidays

**Discovered:** Phase 0.1, 6 September 2026, from the 12-month backfill.
**Affects:** `ingest/delivery.py` (Phase 2.3), the delivery baseline (§8.3).

### What happens

For a non-trading day the two EOD endpoints disagree about how to say "there is
no file":

| Endpoint | On an exchange holiday |
|---|---|
| `content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | HTTP 404 — correct |
| `products/content/sec_bhavdata_full_{DDMMYYYY}.csv` | **HTTP 200 carrying the previous trading day's rows** |

The returned file is a complete, well-formed, ~350 KB delivery file. Nothing
about the response says it is the wrong date. The only tell is the `DATE1`
column inside it.

### The measurement

Across the 12-month backfill, comparing each file's requested date against the
`DATE1` its first data row carries:

```
delivery files checked: 174  |  filename date == DATE1: 163  |  mismatch: 11
```

All 163 matches are trading days. All 11 mismatches are exchange holidays, each
serving exactly one trading session earlier:

```
requested 2025-10-22 -> contains 2025-10-21     requested 2026-03-03 -> contains 2026-03-02
requested 2025-11-05 -> contains 2025-11-04     requested 2026-03-26 -> contains 2026-03-25
requested 2025-12-25 -> contains 2025-12-24     requested 2026-03-31 -> contains 2026-03-30
requested 2026-01-15 -> contains 2026-01-14     requested 2026-04-03 -> contains 2026-04-02
requested 2026-01-26 -> contains 2026-01-23     requested 2026-04-14 -> contains 2026-04-13
requested 2026-05-01 -> contains 2026-04-30
```

`2026-01-26` is the useful case: Republic Day fell on a Monday, and the file
served is the preceding Friday's, not Sunday's. The endpoint returns the last
*trading* session, not the previous calendar day.

### Why it matters

Keyed on the filename date, this row set would be written twice — once under its
real date and once under the holiday — which:

- **double-counts one session in the 20-day delivery baseline** (§8.3), shifting
  the mean and shrinking the SD, so every subsequent `delivery_z` for that
  symbol is computed against a corrupted reference;
- **invents trading activity on a day the market was shut**, which the freshness
  machine and the trading calendar both contradict;
- does so **silently** — the file is valid, complete, and passes every §6.2
  structural check (`high >= low`, `deliverable_qty <= traded_qty`, row counts),
  because the data is real. It is only attached to the wrong date.

This is precisely the failure mode R3 names: a wrong guess about market-data
semantics that produces numbers which look plausible and are wrong.

### What Phase 0 does about it

`backend/scripts/backfill.py` reads `DATE1` from the first data row of each
delivery file and, when it disagrees with the requested date, moves the file to
`data/cache/delivery_stale/{requested_date}/` and records `STALE_CONTENT` in the
backfill ledger with the actual content date. Moved, not deleted — §6.2
quarantines rejected data rather than dropping it.

So the cache contains no delivery file filed under a date it does not belong to.

### What Phase 2 must still do

The backfill guard protects the cache. It is not the ingest contract. When
`ingest/delivery.py` is written it must independently assert that the parsed
`DATE1` equals the target date and quarantine the file with reason
`CONTENT_DATE_MISMATCH` if not — because the daily 18:00 job does not go through
the backfill script, and a holiday that the trading calendar has not yet been
updated for would otherwise reach the database.

Once the trading calendar exists (Phase 1.2), the scheduler should not be asking
for a holiday's file at all (§6.1, "check `trading_calendar` before scheduling").
This check is the belt to that calendar's braces, and should stay even so: the
holiday list is itself ingested data and can be wrong or stale.

---

## Endpoint reference, as verified

| Source | URL | Format |
|---|---|---|
| CM bhavcopy (UDiFF) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | zipped CSV, ~180-200 KB |
| Security-wise delivery | `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv` | plain CSV, ~350 KB |

Note the differing date formats in the two filenames: `YYYYMMDD` for the
bhavcopy, `DDMMYYYY` for the delivery file.

Both require the homepage warmup for cookies before they will answer. Both
answered over plain `httpx` with the constant browser header set during the
Phase 0 backfill; `curl_cffi` TLS impersonation (tier 3) is installed and is
selected automatically if present, but was not needed.

The delivery file's header carries a leading space on every column after the
first (`SYMBOL, SERIES, DATE1, ...`), so column names must be stripped before
use. `DELIV_QTY` and `DELIV_PER` are literal `-` for series where delivery is
not reported; that is a Phase 2 parsing concern, noted here so it is not a
surprise.

---

## NSE publishes no sector classification covering the whole equity universe

**Discovered:** Phase 1.1, 6 September 2026, building the symbol master.
**Affects:** `ingest/symbol_master.py`, the §5.1 fallback chain, `swl_sector_coverage_ratio`,
and §11.3 `SECTOR_WIDE` classification.

### The problem

§5.1 tier 1 is "NSE sector classification file". `EQUITY_L.csv` — the file the
symbol master is built from — has no sector column at all:

```
SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
```

Every NSE-published file that *does* carry the official `Industry` column is an
index constituent list, and NSE Indices only classifies its investable universe.

### What was measured

`EQUITY_L.csv` on this date: **2,570 symbols**, all EQ (2,288) / BE (254) /
BZ (28), so the whole file is in §2.1 scope.

Coverage from the union of every reachable NSE index constituent file — 35 of
them, broad-market, sectoral and thematic:

```
ind_nifty50list          50 rows   +50 new
ind_nifty500list        501 rows  +301 new
ind_niftymicrocap250    254 rows  +254 new
ind_niftytotalmarket    755 rows    +0 new   <- superset of the above
ind_niftymedialist       10 rows    +2 new
ind_niftypsubanklist     12 rows    +1 new
...every other file       0 new
                        -------
unique symbols            758     -> 753 of EQUITY_L's 2,570 = 29.3%
```

Nifty Total Market (755) *is* NSE Indices' full investable universe. The other
34 files are subsets of it, bar three symbols. There is no larger NSE file.

Endpoints checked and rejected as sources, each fetched rather than assumed:

| Endpoint | Result |
|---|---|
| `/api/quote-equity?symbol=X` — carries `industryInfo` per symbol | **HTTP 403**, with Chrome TLS impersonation, homepage warmup and a quote-page referer |
| `/api/equity-stockIndices?index=...` | HTTP 404 |
| `/api/equity-meta-info`, `/api/search/autocomplete` | HTTP 404 |
| `/api/corporate-announcements` — carries `smIndustry` | HTTP 200, but a **different, older taxonomy** (71+ values: "Computers - Software", "Auto Ancillaries") that does not map to the 22 published sectors without inventing the mapping. Rejected under R3 |
| `/api/equity-master`, `/api/market-data-pre-open` | HTTP 200, no sector |

So NSE's own per-symbol classification exists and is not reachable. Nothing in
the loader silently substitutes for it.

### The vendor tier, and why BSE

Tier 3 is "vendor/broker instrument metadata". No broker instrument dump
(Kite, Dhan, Upstox) carries a sector. BSE does, through
`api.bseindia.com/.../ComHeadernew`, and its `IndustryNew` field uses the same
SEBI/AMFI sector taxonomy NSE's index files use — the same 22 labels, differing
only in punctuation.

That claim was tested, not assumed. 150 symbols carried by both NSE's index
files and BSE were compared:

```
sample=150  agree=150  disagree=0  no_data=0     agreement = 1.0000
```

The only differences are commas: BSE writes `Oil, Gas & Consumable Fuels` and
`Media, Entertainment & Publication` where NSE writes them without. Left raw,
that would split one §11.3 peer group in two and could push both halves under
`SECTOR_MIN_PEERS` with nothing looking wrong. `normalise_sector` collapses
both to the NSE spelling before anything is stored.

BSE's bulk `ListofScripData` returns `INDUSTRY: null` for every row and ignores
its own `industry=` filter (all 22 filter values return the identical 4,997
rows), so the sector has to be fetched per scrip. 1,696 lookups ~0.4s apart, of
which 1,685 returned a sector, cached as one JSON document per snapshot with a
SHA-256 sidecar and checkpointed every 100 — a one-time ~11 minutes, free after
that. The offline rerun reproduces the identical result in under a second.

### The result: the coverage ceiling is ~0.95, not 0.99

As loaded on 6 September 2026:

```
EQUITY_L symbols                              2,570
  PRIMARY_FILE  ind_niftytotalmarket_list.csv    750   29.2%
  INDEX_MAP     the other index files              3    0.1%
  VENDOR        BSE, joined on ISIN            1,685   65.6%
  UNASSIGNED                                     132    5.1%
                                               -----
  swl_sector_coverage_ratio                           0.9486
```

All 22 published sectors are represented and no peer group falls under
`SECTOR_MIN_PEERS` (=4), so §11.3 is fully usable on the resolved 94.9%.

The 132 are companies listed on NSE and **not on BSE** — mostly former SME-platform
migrations (Aakash Exploration, Ajooni Biotech, Art Nirman, Banka BioLoo …). BSE
has no record of them under any status, so the ISIN join cannot reach them. A
match on normalised company name recovers exactly 2 of the 132, which is not
worth the risk of a cross-venue name collision assigning one company's sector to
another (R3).

**BUILD_PLAN task 1.1 asks for `swl_sector_coverage_ratio` ≥ 0.99 for active
symbols. From the sources that exist, 0.9486 is what there is.** The gap is 132
symbols, and it is visible rather than papered over:

- they are `UNASSIGNED`, never NULL, and `sector_source = 'UNASSIGNED'` says so;
- §5.1 already states the consequence — an `UNASSIGNED` symbol can never be
  classified `SECTOR_WIDE`, which biases it toward being surfaced, so the
  failure mode is over-surfacing 132 micro-caps, not wrong numbers;
- §11.6's liquidity hysteresis suppresses most of them on their own merits;
- the ratio is logged on every run and asserted against a regression floor, so a
  tier that stops answering fails a test rather than quietly lowering coverage.

### What would close the gap

One thing only: a per-symbol NSE `industryInfo` source. If `/api/quote-equity`
becomes reachable, or a broker feed with sector metadata arrives with the
credentials in `docs/broker-access.md`, it slots in as tier 1 and the residual
goes to zero. The chain is ordered, so adding a tier changes no other code.

---

## The trading calendar needs two sources, because each misses a real session

**Discovered:** Phase 1.2, 6 September 2026, building `trading_calendar`.
**Affects:** `ingest/calendar.py`, `timeutil.py`, §6.1 calendar gating, and the
`sqrt(n)` in SCAR (§10.2).

### The naive rule is wrong twice in fifteen months

"A trading day is a weekday that is not on the holiday list" misses both
exceptional days in the backfilled window, in opposite directions:

| Date | Day | What the naive rule says | What happened |
|---|---|---|---|
| 2025-10-21 | Tuesday | closed — it is on the holiday list | **traded** — Muhurat session |
| 2026-02-01 | Sunday | closed — it is a weekend | **traded** — Budget special live session |

Neither is exotic. A Muhurat session happens every year, and a Budget session
lands on a weekend whenever the Budget does.

### The two sources, and what each is good for

**Holiday master** — `/api/holiday-master?type=trading&year=YYYY`, segment `CM`.
The `year` parameter works, so history is reachable and not only the current
year; `year=2027` returns an empty list because it is not published yet. `CM`
and `CBM` carry identical dates, so one is read and the other ignored.

**The cached bhavcopy record.** Whether NSE published a bhavcopy for a date is
the strongest available evidence a session happened, and it costs no network:
the Phase 0 backfill already holds 12 months. Over the window the holiday master
explains **all 14** weekday gaps in the cache with **none unexplained**, so the
two agree everywhere except on the special sessions above — which is exactly
where each one is needed to correct the other.

Mock-trading Saturdays (2026-08-29, 2026-09-05, both announced by circular)
return **404**, so a published bhavcopy means a real session and not a rehearsal.
Of the 131 weekend dates in the window, exactly one returns 200.

The turnover corroborates the Muhurat classification without being used to make
it — the classification rests on the two NSE sources disagreeing:

```
2025-10-17  Fri   ₹110,895 Cr   34.0M trades
2025-10-20  Mon   ₹ 99,634 Cr   33.6M trades
2025-10-21  Tue   ₹ 19,552 Cr    9.0M trades   <- ~18% of a normal session
2025-10-23  Thu   ₹116,175 Cr   35.7M trades
```

### Muhurat timings are not published when the date is

NSE's own holidays page says so, and this sentence is copied verbatim into the
calendar row's `notes`:

> November 08, 2026, shall be a trading holiday on account of Diwali Laxmi
> Pujan. Muhurat Trading will be conducted on that day. **Timings of Muhurat
> Trading shall be notified subsequently through a circular.**

The circular is not reachable either: `/api/circulars` **ignores its date range**
and returns only the latest ~200 rows, so neither the October 2025 circular nor
a November 2026 one that does not exist yet can be fetched.

So "a session happened and its window is not yet known" is a real, recurring
state. §21 has no Muhurat constant and R1 forbids inventing one, so the row is
written with `is_trading_day = TRUE`, `session_type = 'MUHURAT'` and a **NULL
window**, and every run reports it under `pending_windows`.

### Why `timeutil` changed

`_session_from_row` previously **raised** on a non-regular trading day with no
hours. That made one unnotified hour on one day take down the whole calendar:
a Diwali falls inside every `BETA_WINDOW_DAYS` (=120) window once a year, so
essentially every baseline load spanning one would have failed to construct.

The refusal moved from construction to the query. `SessionWindowUnknownError`
is raised by `session_phase()` and `session_close()` — the two functions that
actually need a window — while `previous_trading_day()` and `sessions_between()`
work correctly, since they need only `is_trading_day`. Those two are the §5.2
reason the table exists, because a miscounted session changes the `sqrt(n)` in
SCAR.

**No default is ever borrowed**, which is the rule the original narrowing was
written to enforce: inheriting 09:00–09:15 would report `PRE_OPEN` on a Diwali
morning hours before the session opens. `Session.has_known_window` lets a
scheduler check before timing a job off a session instead of catching an
exception, which is what §6.1's "MUHURAT → adjust the poll time" needs.

**Open item for the human (R1).** The Muhurat session windows are the one thing
here that cannot be sourced. Once NSE publishes the circular, the weekly
calendar refresh (§19.1) picks the date up; the timings still have to be entered
by a person, or a circular parser has to be built to read them. Until then
`session_phase()` and `session_close()` raise for those two dates and nothing
else is affected.

### What Phase 2 gets from this

`trading_calendar` now holds 451 rows, 2025-09-11 to 2026-12-05: 305 trading
days, 303 `REGULAR`, 2 `MUHURAT`, 146 `CLOSED`. Two consistency checks hold in
both directions and are asserted by the test suite — every cached bhavcopy date
is a trading day, and every trading day inside the cached history has a
bhavcopy. So §6.1 will never schedule an ingest for a date that returns 404, and
never skip one it already has data for.

---

## Three traps in the corporate-action purpose strings

**Discovered:** Phase 1.3, 6 September 2026, building the CA parser.
**Affects:** `ingest/ca_parser.py`, `ingest/corporate_actions.py`, §7.1 factors,
and every return, volatility and beta downstream of them.

§5.3.0 rates `purpose_raw → adjustment factor` the **only High-risk text parse**
in the system: a wrong factor renders a phantom crash that never happened. The
measurement below is over `/api/corporates-corporateActions?index=equities`,
2025-09-11 to 2026-12-05 — **2,121 rows, 594 distinct subject strings.**

### Trap 1 — a bonus that is not an equity bonus

```
Scheme Of Arrangement - Bonus Ncrps 46:1
Scheme Of Arrangement - Bonus Ncrps  4:1
Scheme Of Arrangement - Bonus Ncrps  3:1
```

NCRPS is a **non-convertible redeemable preference share**. This is a bonus
issue of preference shares; the equity share count does not change and the
equity price does not move. Read as an equity bonus, `46:1` gives
`1/47 = 0.0213` — a **98% phantom crash** applied to a stock that did nothing.

This is the single most dangerous string in the data, and it is the exact
failure R3 and R6 exist to prevent: a wrong guess about market-data semantics
producing a number that looks plausible and is wrong. A fourth string,
`Rights - 7 Ccps And 7 Warrants:40`, is the same problem in the rights family.

Any purpose string naming a non-equity instrument (NCRPS, NCPS, CCPS, OCPS,
CCD, NCD, warrant, preference share, debenture) is refused outright — typed
`UNPARSED`, factor NULL, window suppressed.

### Trap 2 — every split looks like a composite

All 53 face-value splits in the window are titled:

```
Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share
```

§5.3's composite rule is "more than one action keyword". `SPLIT` and
`SUB-DIVISION` are both action keywords, so **counting keywords marks all 53
splits composite** and suppresses every one of them. They are one action named
twice.

So composite detection counts **families**, never keywords: SPLIT and
SUB-DIVISION map to one family, as do DIVIDEND and DISTRIBUTION.

### Trap 3 — " AND " does not separate action clauses

§5.3's other composite trigger is "` AND ` between two ratio-bearing clauses".
` AND ` appears in six real strings, and in **every one** it sits inside a
single trust distribution:

```
Distribution - Rs 1.160 Per Unit Consists Of Re 1.157 Per Unit As Interest
And Re 0.003 Per Unit As Other Income
```

Splitting on it would misread all six. The composite path therefore fires only
when two *different families* are present. Measured: **zero of the 594 distinct
strings name two families.** The composite branch is still implemented, because
exchanges do publish combined events and the failure mode is severe — but it is
rare, not routine, and a rule that fired on 53 splits and 6 distributions would
have been quietly suppressing 10% of the price-moving actions.

A related non-trap: 23 strings pay two dividends on one ex-date
(`Dividend - Rs 10 Per Share/Special Dividend - Rs 30 Per Share`). Both clauses
are the same family, so they are **summed into one ₹40 payment** rather than
treated as a composite.

### The distribution sum check, and which direction falsifies it

InvIT and REIT payouts state a headline total and then break it down. Summing
the components tests the parser's claim that the headline *is* the total.

The check is one-directional, and the direction is the point. Components summing
to **more** than the headline falsifies the claim — a total cannot be smaller
than its parts — so the amount is refused. Components summing to **less**
falsifies nothing: it means a component label went unrecognised, and the label
vocabulary is open-ended. A two-sided check rejected six strings it had in fact
read correctly, the misses being `Repayment Of Shareholder Loan` and
`Interest On Fixed Deposit`.

### Result

```
rows                     2,121          action_type
                                          DIVIDEND      1,929   90.9%
typed                     98.3%           SPLIT            53    2.5%
UNPARSED                   1.7%           BONUS            47    2.2%
                                          RIGHTS           42    2.0%
                                          UNPARSED         36    1.7%
                                          DEMERGER         14    0.7%
```

Every one of the 36 unparsed rows is a **deliberate refusal**, not a parser
failure: 32 `Buy Back` (no row in the §5.3 enum and no ex-date price
adjustment), 3 NCRPS bonuses, 1 CCPS rights issue. Zero dividends carry a
`price_factor` other than 1.0.

`RIGHTS` and `DEMERGER` are typed but carry no factor. A rights adjustment needs
the **cum price**, which no purpose string contains, and a demerger needs the
value split between the entities, which real strings state as the single word
`Demerger`. Both are written with `verification = 'UNPARSED'` so §5.3's
fail-safe rule suppresses the window, and task 1.5 can still infer the factor
from the observed gap.

### What tasks 1.4 and 1.5 still need

`tr_factor` is NULL for 1,808 cash payouts. §5.3 defines it as
`price_factor × (prev − div) / prev`, and `prev` is the previous close — a
`daily_bars` value, and `daily_bars` is Phase 2. Nothing is lost: `purpose_raw`
is stored NOT NULL and the parser is pure, so task 1.4 recovers the amount by
re-reading the same string and gets the same answer by construction. The loader
already accepts a previous-close map and fills the column the moment one exists.

---

## Composite corporate actions arrive as separate rows, not composite strings

**Discovered:** Phase 1.4, 6 September 2026, verifying parsed factors against
the ex-date price gap.
**Affects:** `ingest/ca_verify.py`, and by extension §7.1 factors and every
return downstream.

### What §5.3 expects, and what the feed actually does

§5.3 handles multi-action events **inside one purpose string**:

> `SUB-DIVISION FROM RS 10 TO RS 2 AND BONUS IN 1:1 RATIO`

Measured over the backfilled history, that shape does not occur — zero of the
594 distinct strings name two action families. What does occur is the same event
published as **two separate feed rows sharing a symbol and an ex-date**, each
carrying a clean single-action string.

Verified one row at a time, every one of them fails catastrophically, because
each factor predicts only half the gap the market took:

| symbol | ex-date | prev close | open | own factor | dev alone | combined | dev combined |
|---|---|---|---|---|---|---|---|
| DELPHIFX | 2026-02-13 | 228.13 | 15.90 | 0.3333 | **−79.1%** | 0.06667 | +4.5% |
| SILVERTUC | 2026-03-06 | 1345.90 | 137.90 | 0.5000 | **−79.5%** | 0.10000 | +2.5% |
| FCL | 2025-10-31 | 248.60 | 25.55 | 0.5000 | **−79.4%** | 0.10000 | +2.8% |
| BHARATRAS | 2025-12-12 | 9900.00 | 2549.00 | 0.5000 | **−48.5%** | 0.25000 | +3.0% |
| NAZARA | 2025-09-26 | 1116.00 | 291.00 | 0.5000 | **−47.8%** | 0.25000 | +4.3% |
| RNBDENIMS | 2026-04-02 | 61.30 | 19.41 | 0.6667 | **−52.5%** | 0.33333 | −5.0% |

Nothing was wrong with either parse. The error was **verifying half an event**.

So verification groups by `(symbol, ex_date)` and tests the product. This is
§5.3's own composition rule applied across rows rather than within a string;
multiplication is commutative, so the stated execution order does not change
the result, and a single action composes to itself so there is one code path.

If any action on the date states no factor — a rights issue, a demerger, an
unreadable string — the combined gap is unknowable and **none** of its siblings
can be verified either. R6: suppress rather than guess.

### Result over the backfilled history

```
                        before grouping     after grouping
VERIFIED                     1,689              1,701
DISCREPANCY                     22                 10
verified / testable         98.71%             99.42%
```

Against a §1.4 bar of 85%. Sixteen of the twenty-two original discrepancies were
this one defect.

### The ten that remain are real

None is a factor error. Each is a stock that moved on its own news that morning
by more than `CA_VERIFY_TOLERANCE` (=0.08) on top of the corporate action:

```
VAIBHAVGBL  +19.2%   SIL        +15.7%   ORIENTTECH +14.0%
AHCL        +11.3%   NARMADA    +10.5%   BESTAGRO    +9.5%
ALLDIGI      −9.1%   GEEKAYWIRE  +8.6%
```

These are exactly what the band exists to catch, and the fail-safe rule
suppresses their windows. They are listed at `/api/eval/unparsed-actions`
alongside the strings that never parsed, because both are answers to the same
question — how far can this be trusted — and publishing them is a stronger
position than claiming the parser is always right (§5.3.0).

### Two supporting measurements

**`PrvsClsgPric` is as-traded, not pre-adjusted.** Checked on eight ex-dates
with a known bonus or split, against the previous trading session's `ClsPric`:
the ratio was exactly 1.0000 on all eight. This matters because a verification
built on a pre-adjusted previous close would compare an adjusted price against
an adjusted expectation and confirm itself no matter what the parser did. The
spec's source — the previous trading day's close — is what is used, and the
exchange's own figure is read alongside it and reported when the two disagree.

**173 actions are unverifiable, and correctly so.** Twelve sit on the first
cached session and have no previous trading day inside the window. The rest are
InvIT and REIT units — EMBASSY, MINDSPACE, BIRET, NHIT, CUBEINVIT, SHREMINVIT,
SEITINVIT — which trade outside the §2.1 EQ/BE/BZ scope and so have no bar to
compare against. They are `UNVERIFIED`, never `DISCREPANCY`: absence of evidence
is not evidence of a parser error, and branding it one would suppress a symbol
for the crime of having no bar on file.

### A note on where prices come from

`daily_bars` is a Phase 2 table and is still empty, so this job reads the
Phase 0 backfill straight off disk through a `PriceSource` — which is what
"using data already on disk" in §5.3 means. `DailyBarsPrices` is the same
interface over the table and takes over automatically once task 2.1 fills it.
The job logs which source it used on every run; it never falls back silently,
because a job that quietly changed its evidence base between runs would make two
different verdicts look like one.

---

---

## Inferring factors for the unparsed tail, and a bug it exposed

**Discovered:** Phase 1.5, 6 September 2026.
**Affects:** `ingest/ca_infer.py`, `ingest/corporate_actions.py`, §11.1
suppression.

### What inference recovers

```
candidates (no price_factor, not settled)          89
  INFERRED                                          8
  still UNPARSED                                   81
    NO_CLEAN_FACTOR_WITHIN_TOLERANCE               78
    MULTIPLE_UNATTRIBUTED_ACTIONS                   2
    NO_OBSERVED_GAP                                 1
```

The eight are exactly the population §5.3 aims at — actions whose *type* is
known but whose *factor* the purpose string never states:

```
NDTV       2025-09-12  RIGHTS    gap 0.754017 -> 0.75    (0.54% away)
CAPTRUST   2025-10-10  RIGHTS    gap 0.688879 -> 0.70    (1.59%)
UTKARSHBNK 2025-10-14  RIGHTS    gap 0.836207 -> 5/6     (0.34%)
STALLION   2026-02-11  RIGHTS    gap 0.836704 -> 5/6     (0.40%)
SICALLOG   2026-02-18  RIGHTS    gap 0.793651 -> 0.80    (0.79%)
TRIVENI    2026-07-22  DEMERGER  gap 0.614952 -> 0.625   (1.61%)
GENESYS    2026-08-06  RIGHTS    gap 0.654244 -> 2/3     (1.86%)
INDIAGLYCO 2026-09-02  DEMERGER  gap 0.202393 -> 0.20    (1.20%)
```

A rights adjustment needs the cum price and a demerger the value split between
entities; neither appears in any purpose string, so the text can never yield
these and the price gap is the only estimator there is.

### Why the other 81 stay unparsed, and why the band was not widened

`CA_CLEAN_FACTORS` is the set of factors produced by standard bonus ratios and
face-value splits. Most of the remaining tail is 32 `Buy Back` rows — which have
no ex-date price adjustment at all — plus rights issues whose subscription price
lands them nowhere near a clean ratio. 66 of the 80 candidates with a price pair
had a gap of ~1.0, and there is deliberately no 1.0 in the table: "no
adjustment" is not a ratio to be recovered from a price that did not move.

The five closest declines sit 2.1%–3.0% from a clean factor against a 2% band:

```
DUCON      2026-08-25  RIGHTS    gap 0.733766  2.16% from 0.75
SUMEETINDS 2026-06-12  RIGHTS    gap 0.851798  2.22% from 5/6
GUJENERGY  2026-07-02  DEMERGER  gap 0.852941  2.35% from 5/6
HCC        2025-12-05  RIGHTS    gap 0.770625  2.75% from 0.75
SHANKARA   2025-09-24  DEMERGER  gap 0.257446  2.98% from 0.25
```

Tempting, and left alone. `CA_INFER_SNAP_TOLERANCE` is a §21 constant and R1
puts it out of reach of a result that would look better if it moved. The run
prints its nearest misses on purpose — they are how a human tells a tolerance
that is too tight from a tail with no clean answer — and at 2-3% on rights
factors that land near a clean ratio only by arithmetic coincidence, they say
the latter. Every one is suppressed under the §5.3 fail-safe, which costs a
signal and risks nothing.

### The bug this exposed: a verdict outliving its evidence

Running the full suite left eight rows reading `verification = 'INFERRED'` with
`price_factor = NULL` — asserting a factor they no longer held.

Task 1.3's upsert protects the *verdict* against a re-parse, so that task 1.4's
empirical work is not undone by the next daily refresh:

```sql
verification = CASE WHEN corporate_actions.verification IN
    ('VERIFIED','DISCREPANCY','INFERRED') THEN corporate_actions.verification
    ELSE EXCLUDED.verification END
```

but it took `price_factor` from the freshly parsed row unconditionally. For a
rights issue or a demerger that value is NULL, so every daily CA refresh
silently stripped the inferred factor and kept the label. Nothing downstream
could have detected it: the row looked settled and carried no number.

An inferred factor did not come from the text and cannot be reproduced by
re-reading it, so the upsert now preserves `price_factor` and `tr_factor` on an
`INFERRED` row exactly as it preserves the verdict. Two further guards were
added with it:

- inference's own `WHERE` clause is `price_factor IS NULL`, so it can only ever
  *fill* a factor and never replace one — a factor already present came from the
  text or from two sources agreeing, and both outrank a snapped guess;
- an `INFERRED` row holding no factor is treated as a candidate again, so a row
  already in the broken state is repaired rather than being invisible to both
  jobs.

The invariant that caught it is now asserted directly: **no row may claim
`VERIFIED` or `INFERRED` while its `price_factor` is NULL.**

### And a second one: verification was confirming its own inferences

Once inference gave those rights and demerger rows a factor, they became
*testable* to task 1.4 — which promptly tested each against the very ex-date gap
it had just been snapped from, found it agreed, and relabelled it `VERIFIED`.

That confirmation is circular by construction. It cannot fail, it says nothing
about whether the factor is right, and it destroys the `INFERRED` flag that §5.3
requires be "flagged everywhere it appears" — laundering a snapped guess into
what reads as two independent sources agreeing. Only a factor derived from the
*text* makes a claim the market can independently settle, so verification now
skips `INFERRED` rows outright.

Both bugs share a shape worth naming: three jobs write the same few columns, and
each was correct alone. What was missing was a statement of which job owns which
column under which verdict. That is now explicit in each of the three write
paths, and asserted by invariants over the table rather than over any one job's
output.

### The guard against inventing an action is structural

§5.3's warning is that "without that guard a genuine -50% crash would be
silently reinterpreted as a 1:1 bonus, which is the worst failure this system
can produce."

`ca_infer` iterates over **scheduled actions** and asks what factor each had. It
never iterates over price gaps asking whether an action occurred, and contains
no code path that creates a `corporate_actions` row. `actions_on()` is exposed
so a caller — or the acceptance test — can assert that absence directly.

The two defences are independent, which matters because the stated acceptance
example only exercises one: a −48% fall is a gap of 0.52, which is 4% from the
nearest clean factor and would not snap even without the guard. The guard is
what protects the −49.5% fall, which snaps to 0.5 perfectly well. Both are
asserted.

---

## The parser coverage report, and why announcements report zero honestly

**Discovered:** Phase 1.6, 6 September 2026.
**Affects:** `ingest/coverage.py`, `ingest/announcements.py`, README.md.

### The four CA buckets are a partition, not four separate counts

`corporate_actions.verification` carries five values across three tasks — 1.3
parses (`UNVERIFIED`/`UNPARSED`), 1.4 verifies against the market
(`VERIFIED`/`DISCREPANCY`), 1.5 infers the unparsed tail (`INFERRED`). BUILD_PLAN
1.6 asks for four: parsed / inferred / unparsed / discrepant. `parsed` is
`VERIFIED + UNVERIFIED` — the text produced a usable factor, whether or not the
market has checked it yet — and the other three map one-to-one onto their
verification value. Because this is a partition of one enum column, the four
buckets sum to the row count **by construction**, not by anything that could
drift out of sync with the acceptance criterion as the pipeline evolves.

Over the backfilled history (2,001 rows): **95.0% parsed, 0.4% inferred, 4.1%
unparsed, 0.5% discrepant** — 95.4% ended up with a usable factor. The report
also lists every distinct unparsed string grouped with its count, rather than
printing the same "Buy Back" 31 times: 15 distinct strings account for all 83
unparsed rows, dominated by 31 `Buy Back` (no ex-date price adjustment exists to
parse) and 12 `Demerger` (factor is the value split between entities, stated in
no purpose string).

### Why the announcement half reports zero, honestly

BUILD_PLAN task 2.8 — the announcement poller, its content-hash dedup, and the
historical backfill — has not run, and building it now would be front-running a
`P0` task with its own acceptance criteria (a non-empty table, zero duplicate
hashes, an idempotent re-poll) that this task was never asked to satisfy.

What *is* built is `app.ingest.announcements.resolve_category` — §9.2's
three-step resolution order (`desc` lookup → regex fallback → `OTHER`), with
`CATEGORY_PATTERNS` copied verbatim from the architecture doc. `CATEGORY_FROM_DESC`
is deliberately left empty: §9.2 says to build it by hand-mapping the top ~30
real `desc` values after the backfill, and typing in guessed entries now would
be exactly the invented market-data semantics R3 forbids. Every announcement
today would fall through to the regex fallback or `OTHER` — untested against
reality, since there are 0 rows to test it against.

So the report distinguishes "0 rows, and here is why" from "0 rows, categorised,
0% by desc" — the second would read as a working pipeline that measured zero
coverage, which is false. `AnnouncementCoverage.ingested` carries that
distinction through to both the CLI and the README section.

### The README did not exist

Task 14.1 writes the full README (thesis, evidence, business case, data
provenance). Task 1.6 needed the coverage numbers to have a destination now, so
`coverage.py` creates a minimal `README.md` on first run and thereafter updates
only the block between `<!-- COVERAGE:START -->` and `<!-- COVERAGE:END -->` —
idempotent, and safe to run before or after 14.1 writes the rest of the file.
