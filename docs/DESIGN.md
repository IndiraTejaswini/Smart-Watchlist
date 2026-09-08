# Design notes

This document is the reasoning behind six decisions the brief leaves open, plus
how the system scales, what actually breaks it, and what we chose not to build.
It is written against the code as it runs today, not against the pre-build
specification — where the two disagree, that disagreement is stated explicitly,
because a design document that describes an aspiration instead of the running
system is worse than no design document.

Formulas and constants below are quoted from [`backend/app/constants.py`](../backend/app/constants.py)
(the registry — every number in the codebase traces back to it) and
[`backend/app/analytics/ranker.py`](../backend/app/analytics/ranker.py) (the ranking
implementation). The fuller build-time record, including sections not repeated
here, is [`docs/BUILD_SPEC.md`](BUILD_SPEC.md).

---

## 1. What counts as a meaningful change

> The brief's question: *what counts as a meaningful change?*

**What we do.** A price move only becomes a candidate if it clears the exchange's
own Material Price Movement gate — a price-tier-based threshold (5% under ₹100,
4% under ₹200, 3% above that; see the table in "Where the numbers come from" in
the README) taken from SEBI's 21 May 2024 circular under LODR Regulation 30(11),
with an index-adjustment carve-out (`MPM_INDEX_ADJUST_MIN_PCT = 1.0`, meaning a
move within 1 percentage point of the index's own move on the day does not
automatically qualify). Clearing that gate only produces a *raw* signal. Whether
it is worth a user's attention is a second, separate question, answered by an
event-study layer: an OLS single-index market model fit over a 120-session
window with a 5-session gap before the event day (`BETA_WINDOW_DAYS = 120`,
`BETA_GAP_DAYS = 5`, so the model never trains on the days it is about to
score), producing an abnormal return standardised by residual volatility (SAR),
alongside a turnover z-score and a logit-transformed delivery z-score computed
against 20-session baselines. A candidate that clears MPM but has an
unremarkable SAR, unremarkable turnover, and unremarkable delivery does not
become a scored item — it is the regulatory gate plus the abnormality layer
together, not either alone, that defines "meaningful."

That candidate then passes through a classification cascade that can still
zero it out before a user ever sees it: a move fully attributable to the market
(`abs(beta * r_market) >= MARKET_ATTRIB_RATIO(0.70) * abs(r_stock)`, with a
`MARKET_SAR_CEILING = 1.5` guard so a high-beta stock's real stock-specific move
isn't laundered as "the market did it"), or to the sector (peers in the same
NSE sector sharing sign and magnitude within `SECTOR_TOLERANCE_SD = 1.0` residual
standard deviation, gated on `SECTOR_MIN_PEERS = 3` — the pre-build spec in
`docs/BUILD_SPEC.md` §11.3 says 4; the shipped code uses 3, a real divergence
recorded here rather than silently carried forward), or to a corporate action
whose ex-date falls inside the window, is not "meaningful" in the sense a user
should be interrupted for — it is either explained by something already known
(the market, the sector, a scheduled corporate action) or it isn't a real
stock-specific event at all.

**Why.** The MPM threshold is not ours to negotiate — it is the same bar SEBI
uses to decide whether a company must respond to a market rumour, so anchoring
"meaningful" to it means the product's definition of "worth noticing" is the
same one the regulator already uses for "worth explaining." The abnormality
layer on top exists because MPM alone is a blunt instrument: it fires on
percentage move only, blind to whether that move is unusual for the *stock*.
Barber and Odean's finding that retail attention chases extreme, salient moves
(`RFS` 21(2), 2008) is the failure mode a naive percentage-threshold system
reproduces; standardising by the stock's own volatility is how we avoid just
building a louder version of the same bias.

**What we gave up.** The four weights that turn SAR/turnover/delivery/extreme
into one score (`W_SCAR = 0.45`, `W_TURNOVER = 0.25`, `W_DELIVERY = 0.20`,
`W_EXTREME = 0.10`) are ours, tuned against the replay harness, not derived from
regulation — conflating them with the MPM threshold in a reviewer's mind would
overstate how much of "meaningful" is externally validated. We also gave up
per-user materiality: the gate is the same for every user regardless of how
much they hold or how volatile their other positions are; personalisation only
re-ranks *after* something has already cleared the gate (§3 in the README's
six-decision table), never lowers the bar itself. And `W_EXTREME` is a binary
flag — a 52-week breakout on 5× turnover gets the same 10%-of-`base` bump as a
band touch that reverses in the next tick. We considered an ATR-scaled
continuous version and rejected it (`docs/BUILD_SPEC.md` §23.10): the flag's
imprecision is bounded at 10% of one of four terms, and an unbounded ratio
computed from a noisy true-range estimate costs more in review than it buys in
precision.

**What breaks it, and how we detect that.** Three real, current cases, found by
querying the live database rather than reasoning about the formula in the
abstract:

`LIQUIDBEES` and `LIQUIDCASE` — both liquid-fund ETFs whose NAV barely moves —
generated candidates on 2026-07-03 with `turnover_z ≈ 5.1` and `sar` between
0.0 and 0.06. Turnover cleared its own candidate floor (`TURNOVER_Z_CANDIDATE_MIN
= 2.5`) entirely independently of price, so a trading-volume spike on an
instrument that structurally never moves in price still produces a candidate.
The abnormality layer catches most of this (the ranker's `W_SCAR` term is
near-zero for these rows so they rank low), but they are not suppressed
outright — a stricter version would require *both* turnover and SAR to clear
their floors jointly, and we chose not to add that coupling because it would
also suppress genuine "quiet accumulation" cases where price hasn't moved yet
but volume has.

`ESDS` produced a candidate on 2026-09-07 with `n_obs = 0` in its market-model
window and `quality_flag = 'DEGRADED'`, yet `sar = 8.78` — an extreme value from
a model that, by its own bookkeeping, had no observations to estimate beta from
(beta is forced to 1.0 under `BETA_MIN_OBS = 60`; below that floor the model
quality is flagged but the SAR is still computed and still scored). This is a
known, detected failure mode — `quality_flag` is exactly the signal that lets a
reviewer or a future ranking pass discount it — but today nothing downstream
actually discounts it; a `DEGRADED` SAR competes for rank on equal footing with
a fully-observed one. That is a real gap, not a hidden one.

The ranker's use of `max(0.0, delivery_z)` for the delivery term (see
`compute_base_score` in `ranker.py`) means only *unusually high* delivery
raises a score. `ENRIN` on 2026-08-07 had `delivery_z = -10.29` — an extremely
*low* delivery reading alongside `turnover_z = 10.53` and `sar = 5.15`, the
textbook signature of a price spike with no real buying conviction behind it —
and the delivery term contributed exactly zero to its score. The pre-build spec
(`docs/BUILD_SPEC.md` §13.1) describes `abs(delivery_z)`, which would have
caught this; the shipped ranker does not. This is the single clearest
spec-vs-code divergence in the scoring path and it is a real, currently-live
gap: a "high turnover, no delivery" pump signature is scored identically to a
merely well-traded stock unless its SAR happens to be large on its own.

---

## 2. What information to surface

> The brief's question: *what information to surface?*

**What we do.** Every surfaced item carries four things, always, in the same
order: what moved, stated relative to the user's own cursor ("down 7.2% across
the three sessions since you last looked"); how unusual that is in the stock's
own history, not the market's ("its largest three-day stock-specific move in 14
months"); whether there is a disclosed cause ("Q2 results, filed Tuesday 18:40"
or, honestly, "no filing found — turnover 3.4× normal, delivery below its own
average"); and a freshness stamp ("as of 15:29 on 4 Sep · final" or
"provisional — delivery data lands after 18:00"). Alongside the ranked items,
three things are surfaced that are not scored signals at all: a market-wide
rollup line when one applies, one grouped line per sector when peers moved
together, and corporate-action notices explaining an ex-date price step rather
than presenting it as a move. Every response also carries a `budget` block —
how many candidates were detected, how many were suppressed for each reason,
and how many were shown — rendered on screen, not just logged. And the response
always states what was *not* notable: "nine others: nothing notable," set at
the same type size as a real item, not a footnote.

**Why.** The FCA's review of digital engagement practices in trading apps found
that push notifications measurably shift trading behaviour — a 9,000-consumer
experiment showed an 11% increase in trade count and an 8% increase in
risky-asset share among notified users (FCA Occasional Paper 66). A surface that
can move real behaviour has to be able to justify every item it shows, which is
why "cause" and "how unusual" are mandatory fields rather than optional
enrichment: a bare percentage move with no context is exactly the kind of
salience-without-substance the FCA evidence warns about. The budget block exists
for a symmetric reason — a system that only ever shows you things has no
credible way to claim it filtered anything, and a claim of restraint that
cannot be checked is not evidence of restraint.

**What we gave up.** The Brief itself carries no charts, no sparkline, no
color-coded direction (colour is reserved for data-confidence state — final,
provisional, stale — not for up/down, which is carried typographically instead;
the live watchlist table is the one surface where red/green direction is used,
because fighting that convention there helps nobody). A user who wants a chart
goes to `/symbol/:symbol`; the Brief's job is the sentence, not the picture.
We also gave up filing-text summarisation as a default: the "cause" line is
templated from structured category and metrics data, with an LLM-generated
one-sentence summary only for the highest-visibility slot, gated by three
runtime checks (no digit in the output that wasn't in the input, no banned-copy
term, a length cap) that fall back to the template on any failure —
`docs/BUILD_SPEC.md` §23.12 has the full boundary. Push notifications are not
built at all; the product argues from the FCA evidence that they are a cost, not
a feature, so we did not build a demo we would then have to defend not shipping.

**What breaks it, and how we detect that.** The "cause" field is only as honest
as the suppression it depends on. `WIPRO`'s buy-back, ex-date 2026-06-05, has
`verification = 'UNPARSED'` — its purpose string ("Buy Back") names an action
type our parser has no ex-date price-adjustment rule for, so it is one of 31
identical `UNPARSED` "Buy Back" rows out of 2,023 corporate actions (95.4%
parser coverage overall — see the README's parser-coverage table). Rows in
`UNPARSED` are excluded from the suppression registry entirely, which means an
abnormal move around a buy-back ex-date is not explained by "corporate action"
and not suppressed — it would surface as a normal `UNEXPLAINED` or `EXPLAINED`
item, with no cause line pointing at the buy-back, because the system has no
adjustment rule to point at. This is a known, bounded gap: buy-backs carry no
mechanical ex-date price step the way a split or bonus does, so there may be
nothing to explain in the first place, but the current code cannot distinguish
"nothing to explain" from "we don't know how to explain this" and presents both
identically.

The sector-rollup line is a genuine information loss when the peer group is too
coarse. NSE's own sector taxonomy groups 1,876 candidates under "Financial
Services" over the eval window — a bucket spanning banks, NBFCs, insurers, and
asset managers, businesses with materially different exposures. `SECTOR_WIDE`
classification requires only that peers *in that bucket* share sign and
magnitude; a genuine bank-specific event that happens to coincide with an
NBFC-driven sector move can be grouped and downweighted (multiplier `0.55`,
`docs/BUILD_SPEC.md` §13.2) even though the two companies have nothing in
common but a shared regulatory label. We detect this only by inspection, not by
a runtime check — there is no automatic signal that a sector bucket is too
coarse for a given candidate.

---

## 3. How state persists across sessions and devices

> The brief's question: *how does state persist across sessions and devices?*

**What we do.** A user's "last looked" position is a read cursor —
`(user_id, scope_type, scope_id) → (seen_through_ts, acknowledged_through_ts)` —
merged across devices with a single rule: `GREATEST()`, nothing else. Two
devices writing concurrently converge on whichever wrote the later timestamp,
regardless of arrival order, with no conflict-resolution logic and no vector
clock. `seen_through_ts` advances the moment a Brief is served;
`acknowledged_through_ts` only advances on an explicit action — expanding an
item, opening the symbol page, or "mark all as read" — and the Brief is
rendered against the *acknowledged* cursor, so glancing at the Brief on a phone
does not silently consume the same Brief still waiting, unread, on a desktop.
The watchlist itself is server-authoritative: every mutation bumps a `version`
column, and a write carries an `If-Match` precondition that returns 409 with
the current state on a stale write, rather than silently overwriting a
concurrent edit. List ordering uses fractional indexing — a lexicographically
sortable `position_key` string, so inserting between two items generates a key
between theirs with no reindexing of the rest of the list; if repeated
insertion at the same point grows a key past `POSITION_KEY_MAX_LEN = 32`
characters, a background job re-spaces the whole list.

**Why.** The cursor is a max over a total order, and a max over a total order
is a join-semilattice by construction — commutative, associative, idempotent —
which is the algebraic property that makes "just take `GREATEST()`" a *provably*
sufficient merge rule rather than a lucky simplification. This is not a novel
insight for this domain: Matrix's MSC2285 solved cross-device read-receipt
privacy the same way (a private per-user read pointer merged by position, never
reaching other users), and Slack, Discord, and IRC all converged on the same
shape for the same reason. Reaching for a CRDT here would be reaching for
machinery built for a problem — concurrent, multi-writer, arbitrary-structure
state — that a single-user, single-writer, totally-ordered timestamp does not
have.

**What we gave up.** We explicitly did not build CRDTs (`docs/BUILD_SPEC.md`
§23.2) — correct, since the read cursor has one writer per user and near-zero
real concurrency, and CRDT tombstone growth and merge metadata would be
overhead spent on a problem this system doesn't have. We also did not build a
Type-2 slowly-changing symbol master for point-in-time reconstruction (§23.5):
nightly JSONB snapshots of reference data give the same audit trail at zero
query-time cost, at the price of losing arbitrary-instant reconstruction
between snapshots — acceptable, because nothing in this product needs to
answer "what did the symbol master say at 14:32 on a Tuesday."

**What breaks it, and how we detect that.** The idempotency-key and
pending-mutation-queue design in `docs/BUILD_SPEC.md` §12.4–12.5 — every
mutating request carrying an `Idempotency-Key` header, replayed safely from a
local queue on reconnect — is specified but not implemented in the shipped
frontend: no request in the real client sends that header today. This matters
concretely in exactly one case, the one the design exists to prevent: a
reorder or add/remove sent right as a connection drops and retried by the
client (or by a flaky mobile network's own retry) can double-apply, because the
server has no key to recognise the retry by. The `version`/`If-Match` check
protects against two *different* devices racing each other, which is the more
common case and is real and tested; it does not protect against one device
retrying its own write. This is a known, scoped gap, not a hidden one, and
closing it is a frontend queue plus one header, not a backend redesign — the
backend's idempotency-cache path (`idempotency:{user_id}:{key}` in Redis, TTL
`IDEMPOTENCY_TTL_SECONDS = 86400`) already exists and is unused.

---

## 4. How to handle stale, delayed, or conflicting data

> The brief's question: *how do you handle stale, delayed, or conflicting
> data?*

**What we do.** Every intraday number is provisional by construction, because
the bhavcopy that makes a day's numbers final only lands after close (typically
from 16:00) and delivery data later still (around 18:00) — so any statistic
dated today is shown with an explicit "provisional" state and revised in place
once the final files land, publishing a cache purge (`BHAVCOPY_LANDED:
<trading_date>`) so no worker serves stale provisional data past the point the
database already holds the final one. A parallel nine-state freshness machine
(`LIVE`, `DELAYED`, `STALE_THIN`, `FEED_DOWN`, `BAND_LOCKED`, `HALTED_MARKET`,
and others) exists because a broken feed and a genuine circuit halt look
identical from the client — a halt is invisible in the data feed itself, the
stream simply stops with no error and no flag — and the only way to tell them
apart is to triangulate feed heartbeat age, the benchmark index's own liveness,
and the price's position relative to its band. For corporate actions
specifically, a parsed adjustment factor is verified empirically against the
observed ex-date price gap (there is no independent second source to
cross-check against, so the check is against reality itself, within
`CA_VERIFY_TOLERANCE = 0.08`); a factor that fails that check is marked
`DISCREPANCY`, and — the point that matters most — every non-`VERIFIED` row,
including `DISCREPANCY` and `UNPARSED`, causes that symbol's window to be
suppressed rather than scored. When we cannot determine whether a move is a
corporate-action artefact, the fail-safe rule is silence, not a best guess.

**Why.** Regulation 30(11)'s materiality framework and R6 of the build rules
both point the same direction: when genuinely uncertain whether something is
noise, an artefact, or real, the safe failure is to say nothing rather than to
say something confidently wrong. A −50% number on screen that is actually a
1:1 bonus adjustment is the single worst thing this product could show a user,
because it is indistinguishable from a real crash and it is completely
fabricated by our own pipeline's confusion, not by the market. Suppressing a
real signal costs attention; showing a phantom one costs trust, and the two are
not symmetric.

**What we gave up.** No PDF extraction for deeper materiality verification
(`docs/BUILD_SPEC.md` §23.9) — SEBI's Para B thresholds test a disclosed
transaction against 2% of turnover, 2% of net worth, or 5% of three-year
average PAT, none of which this system ingests, so extracting a contract value
from a filing PDF would prove nothing without the financials to test it
against; we did not build a feature whose output we could not validate. No
dual-source corporate-action verification either — there is no free second
feed to cross-check against, so verification is empirical (against the price
series itself) rather than a second independent opinion, which is weaker in
principle but is the only option that uses data actually on disk.

**What breaks it, and how we detect that — a real bug found and fixed while
building this.** `NARMADA`'s 1:5 stock split, ex-date 2026-07-31, parsed to a
price factor of exactly `0.5` from its purpose string. The observed ex-date
price gap was `0.552` — an 8.9% miss against `CA_VERIFY_TOLERANCE = 0.08` —
so the row was correctly flagged `DISCREPANCY` by the verification step. The
bug: the batch pipeline that builds the corporate-action suppression registry
for scoring (`load_corporate_action_registry` in
`backend/scripts/run_full_pipeline.py`) filtered on
`verification IN ('VERIFIED', 'INFERRED')` only — a `DISCREPANCY` row, despite
being exactly the case R6 defines as "uncertain, so suppress," was silently
excluded from the suppression set and would have scored normally, defeating the
fail-safe rule for the one row where it mattered most. Found by re-deriving the
five self-audit false positives directly from the live database rather than
trusting a prior summary of them, and fixed by adding `'DISCREPANCY'` to the
registry's verification filter; after the fix, `NARMADA` has zero candidates in
the window around its ex-date, confirmed by re-running the full pipeline and
querying the candidates table directly. The detection mechanism this bug
exposes as necessary, and which now exists: the parser coverage report
(`python -m app.ingest.coverage`) partitions every corporate action into four
buckets that sum to the row count by construction, so a verification value that
silently falls outside every downstream filter has nowhere to hide — it would
show up as a bucket whose count doesn't add up to what a consuming query
expects, which is exactly the class of bug this one was.

---

## 5. How the system scales

> The brief's question: *how does the system scale?*

**What we do.** Nothing is computed per user. Signals are computed once per
symbol against the full universe of subscribed instruments, stored keyed by
`(symbol, date)`, and joined to a user's watchlist only at read time, when a
Brief is actually requested. A Nifty-wide move produces on the order of fifty
signal rows total, not one row per affected user per symbol. The digest read
path is cached per `(user, cursor)` for `BRIEF_CACHE_TTL_SECONDS = 60`, and the
much heavier per-symbol computation is cached in Redis and shared across every
user watching that symbol — since a large fraction of all watchlists overlap
heavily on the same few hundred liquid names, this shared cache absorbs most of
the read load before it ever reaches the database.

**Why.** The number that makes this the only viable architecture: Groww
reported 13.12 million active NSE clients at 28.9% market share in July 2026,
against 2,584 instruments in this build's symbol master — of which NSE's own
investable-universe index list classifies 755. Users outnumber symbols by three
to four orders of magnitude. Any design that fans work out per-user on write — computing a
signal and pushing it into every affected user's feed at ingest time — pays
that four-to-five-order-of-magnitude cost on every single ingest cycle, every
day, forever. Computing per symbol and joining at read time pays the
user-count cost only for the users who are actually looking, at the moment
they look, which is the only point in the pipeline where "how many users" is
allowed to matter at all.

**What we gave up, and what stays documented rather than built.** A partitioned
log (Kafka or equivalent) in place of Redis Streams with consumer groups
(`docs/BUILD_SPEC.md` §23.3) — Streams already give ordered, replayable,
per-symbol delivery at the scale this build needs, and the consumer interface
is abstracted behind a class specifically so that swap is a class change, not a
rewrite, if real multi-instance fan-out ever requires it. Subject-based
pub/sub fan-out with binary payloads, Redis write-behind for cursor writes, and
cap-tier grouping are all in the same bucket — correct at Groww's real
production scale, invisible in a single-user demo, and Groww's own engineering
blog describes needing exactly the first two of these for their real-time
terminal, which is closer to independent confirmation than anything we could
measure ourselves at this scale. We also gave up multi-region: everything here
assumes a single region and a single write path; there is no cross-region
replication story and none was built, because nothing about a first submission
justifies designing for a failure mode (regional outage) this system has never
had to survive.

**What breaks it, and how we detect that.** The one place per-user cost still
leaks in is the live WebSocket fan-out for the watchlist table, which is
necessarily per-connection. It is bounded three ways: subscriptions are
scoped to the visible viewport of a virtualized list, not the full watchlist
(so a 250-row watchlist streams only the ~20–30 rendered rows), updated on
scroll with a 200ms debounce; a hard per-connection cap
(`WS_MAX_SUBSCRIPTIONS_PER_CONN = 60`); and conflation at a fixed 400ms
interval so a volatile symbol cannot flood a connection with one message per
tick. A connection saturated for more than 30 seconds is disconnected rather
than allowed to degrade the worker it's attached to — the failure mode this
guards against is not correctness but one noisy client starving every other
connection on the same process.

---

## 6. Where to keep things simple, and where to add complexity

> The brief's question: *where do you keep things simple, and where do you
> deliberately add complexity?*

**What we do.** Complexity is spent on the parts a regulator, a juror, or a
user might reasonably ask us to justify by hand: the MPM gate, the abnormality
statistics (OLS market model, winsorization, the logit transform on a bounded
delivery percentage), the classification cascade that decides what gets
suppressed, the ranking score, and the per-Brief cap. Every one of those is
deterministic, inspectable end to end through `/api/brief/explain/{id}`, and
none of them touches a model whose reasoning cannot be handed to a person.
Simplicity is spent everywhere the deterministic, inspectable version is
already sufficient: no learned ranker, no CRDTs, no partitioned log, no
in-house charting library.

**Why.** The ranker is a transparent statistical model — event-study
econometrics, not machine learning dressed as ranking — and that is a property
worth defending, not a gap to apologize for. A learned ranker fails on the
first question a jury would ask: trained on what target, labelled by whom? On
day one there is no interaction data, so any "learned ranker" in a submission
either invented a synthetic label or is quietly predicting forward returns
instead of ranking attention — which, on a retail brokerage surface, is an
unregistered advice engine wearing a ranking model's name. The FCA evidence
that unexplainable engagement mechanisms measurably harm retail outcomes
applies with particular force to a model that cannot answer "why is this
ranked second," which a gradient-boosted score cannot do and
`/api/brief/explain` does, today, against real data. We considered and
rejected unsupervised anomaly detection too, on the same grounds by a
different route: an isolation forest over `(return, turnover, delivery)` would
surface broadly the same outliers, but loses a decomposable score (the
"turnover 3× normal but delivery below its own average" sentence needs
separated components, not one opaque anomaly number), a unit a user can reason
about (a z-score in sigmas versus an isolation-forest path length), and any
tie between a threshold and a named regulation.

**What we gave up.** No custom charting (`docs/BUILD_SPEC.md` §23.4) —
integrating an existing charting library is the same call Groww itself made
building its own terminal, and building candlestick rendering from scratch buys
nothing a reviewer would credit. No Playwright for data collection (§23.6) — a
TLS-impersonating HTTP client covers what NSE's endpoints actually require, and
a headless browser is a heavyweight answer to a problem a small library
solves (Playwright *is* used, deliberately, for verifying the frontend in a
real browser during development — a different job from scraping, and not the
one §23.6 is about). No robust regression, EWMA, or GARCH for residual
volatility (§23.8) — winsorization at the 1st/99th percentile plus a residual
standard-deviation floor already bound outlier influence, and OLS with a
constant estimation-window sigma is the textbook single-index market model;
defending a non-standard estimator in review costs more than the fit it would
buy. The place we spend real, deliberate complexity on a problem that looks
avoidable is the corporate-action suppression path: a parser, an empirical
verifier, a gap-based inferer for the unparsed tail, and a fail-safe suppression
rule feeding a scoring engine — four separate pieces of machinery for what
looks, from a distance, like "detect stock splits." It stays that complex
because the failure mode on the other side of a shortcut here — a real −50%
crash silently reinterpreted as a harmless 1:1 bonus adjustment — is, in this
system's own words, the worst failure it can produce, and that is not a place
where simple is worth the risk.

**What breaks it, and how we detect that.** The deliberate simplicity has a
cost that is visible in the running system rather than hypothetical, and the
Brief's own top-ranked item demonstrates it. Because the ranking score is a
fixed linear combination with hand-set weights and no learned component, it
cannot learn that a flat-NAV liquid ETF is never interesting no matter how its
turnover behaves — a learned ranker with a month of interaction data would
demote `LIQUIDBEES` after a handful of ignored impressions, and this one never
will on its own. In the current live data it ranks first. The mechanism that
substitutes for learning here is measurement, not intuition: the replay harness
scores the whole universe over 126 sessions so the surfaced set can be read
directly, and the self-audit in the README lists what that reading turned up.
That is a slower and more manual correction loop than a model would give, and
it depends on someone actually looking. The honest statement of the trade-off
is that we chose an approach whose errors are legible and hand-correctable over
one whose errors would be smaller on average and much harder to interrogate —
and the price of that choice is on screen, at rank 1.

---

## How it scales

The asymmetry underlying every scaling decision in this system is stated once,
concretely, so it does not have to be re-derived per component: **users are
counted in the millions, distinct symbols in the low thousands.** Groww's own
reported figures — 13.12 million active NSE clients, 28.9% market share, July
2026 — set the user-side number; the symbol side is 2,584 instruments in this
build's symbol master, of which NSE's own Nifty Total Market list — the outer
bound of NSE's investable-universe classification — covers 755, with the
remainder resolved through a vendor cross-reference (`docs/BUILD_SPEC.md` §5.1,
and `docs/data-notes.md` for the measurement). That three-to-four
order-of-magnitude gap is why every write path in this system is organized
around the symbol, never the user: `signal_events` is keyed by `(symbol,
date)` with no user column at all; the corporate-action suppression registry,
the market-model baselines, and the turnover/delivery baselines are all
computed once per symbol per session and read by however many users happen to
be watching. The single per-user artifact in the whole pipeline is the read
cursor and the cached digest built from it, and both of those are small,
cheap, and — per the cursor's join-semilattice merge rule in decision 3 above —
require no coordination between a user's own devices, let alone between users.

Concretely, the batch pipeline that populated this submission's data computed
market-model parameters and baselines for 3,042 symbols with adjustment
factors over 180 real trading sessions (547,560 market-model-parameter rows,
544,518 delivery-baseline rows), and the 200-symbol × 126-session evaluation
replay used for the numbers in the README evaluated 22,418 symbol-days through
the MPM gate and abnormality layer to produce 9,141 raw candidates and 139
corporate-action notices — all of it computed once, independent of how many
users are watching any of those 200 symbols. Scaling to Groww's real user
count changes none of that arithmetic; it only changes how many times the
already-computed per-symbol result gets read, which is exactly the operation
the shared Redis cache exists to absorb cheaply.

What is deliberately left undone, and stated as such rather than half-built: a
partitioned log in place of Redis Streams, subject-based binary pub/sub
fan-out, Redis write-behind cursor writes, and cap-tier grouping of similar
symbols for shared computation. Groww's own engineering blog on their "915"
real-time trading terminal describes needing the first two of these at their
actual scale, which is a stronger argument for eventually building them than
anything this submission could demonstrate on a single-user demo — and a
weaker argument for building them *now*, where they would be invisible.

---

## Failure-modes catalogue

Every failure mode below is detected by name — a specific signal, not "the
system seemed off" — and handled by a specific, stated behaviour. This is the
full list from `docs/BUILD_SPEC.md` §24, reproduced here because a design
document that argues for fail-safe behaviour throughout should also be
checkable against a concrete list of the failures that behaviour actually
covers.

| Failure | Detected by | Handling |
|---|---|---|
| Bhavcopy late or missing | `last_bhavcopy_date` stale | Banner naming the date; dependent jobs paused; escalate at 20:30 IST |
| Bhavcopy truncated | Active-symbol floor + rolling median check | Abort, quarantine, never commit |
| File corrupted in transit | SHA-256 mismatch against the expected hash | Re-fetch; an unverified file is never parsed |
| Unparsed, composite, or discrepant corporate action | `verification != VERIFIED` | Suppress the window regardless — fail safe (§4 above) |
| Missing 09:30 index snapshot | Gap in `index_snapshots_0930` | Fall back to the broker candle, else mark `ESTIMATED_FROM_OPEN` and flag every derived signal that depended on it |
| Broker feed dies | Heartbeat age exceeds 10 seconds | State → `FEED_DOWN`, prices dim in the UI, fall back to polling |
| Stock at its price band | No ticks, last-traded price sits at the band | State → `BAND_LOCKED` — copy says "locked at the band," never "halted" |
| Market-wide halt | Silent fraction of the feed *and* the benchmark index anchor both silent | State → `HALTED_MARKET`, banner names the circuit stage |
| Illiquid symbol | Liquidity hysteresis state → `SUPPRESSED` | No scored signals; copy says "too thinly traded to assess reliably" |
| Degraded market-model beta | `n_obs < BETA_MIN_OBS (60)` | `quality_flag = 'DEGRADED'`, beta forced to 1.0, visible in the explain endpoint (see the ESDS case in decision 1) |
| Missing sector classification | `sector = 'UNASSIGNED'` | Cannot be classified `SECTOR_WIDE`; tracked as its own coverage metric rather than defaulted silently |
| Stale Brief cache after restatement | — | Redis purge published on `BHAVCOPY_LANDED` |
| WebSocket sequence gap | `incoming.seq != last_seen_seq + 1` | Client drops the delta, shows `RE_SYNCING`, requests a resync |
| Duplicate ingest of the same file | `ON CONFLICT` plus a file-content hash | Idempotent; both attempts recorded in `ingest_runs` |
| Clock or date confusion | — | IST observes no DST; every date is resolved through the trading calendar, never wall-clock arithmetic |

---

## Considered and rejected

This section exists because documenting what we chose not to build is, on its
own, evidence of engineering judgement — reaching for the complicated tool by
default is not a neutral choice, and stating why the simpler one was enough is
part of the design, not an omission from it.

**No learned ranker.** Covered in full in decision 6 above. The short version:
there is no label on day one, the output has to be defensible line by line
(which `/api/brief/explain` does and a gradient-boosted score cannot), and an
unexplainable model on a surface that measurably shifts retail trading
behaviour (the FCA's own finding) is a liability, not a credential. The v2 this
becomes, sketched rather than built: log Brief-item opens per impression with
rank position, correct for position bias with inverse-propensity weighting
(rank 1 gets opened regardless of quality), hold the current statistical score
as a feature so the model learns a residual re-rank rather than replacing the
event-study math outright, evaluate offline against this same replay harness
before it ever reaches a user, and keep the MPM regulatory floor outside the
model permanently so no learned component can ever suppress something the
exchange considers material.

**No CRDTs.** Covered in decision 3. The read cursor is a max over a total
order — already a join-semilattice — and the watchlist has one writer and
near-zero real concurrency. CRDT metadata overhead and tombstone growth solve
a multi-writer problem this system does not have.

**No Kafka.** Covered under "how it scales" above. Redis Streams with
consumer groups already gives ordered, replayable, per-symbol delivery at this
scale, and the consumer interface is abstracted so a future swap is a class
change, not a rewrite.

**No custom charting.** Groww integrated an existing charting library rather
than building candlestick rendering from scratch for their own real terminal;
building one from scratch here would spend effort a reviewer has no way to
credit over the alternative of picking a maintained library and moving that
effort into the parts of the system that are actually novel.

**No two-factor (market-and-sector) statistical model.** A two-factor model is
statistically better-fitting, but it folds sector co-movement directly into
the residual, which destroys the "these moved together" grouping the sector
rollup line depends on to render "IT fell together" as one sentence. A
single-factor model plus an explicit, separate sector classifier is *more*
explainable even though it is less statistically efficient, and explainability
is the actual pitch — a v2 revisiting this would need to preserve the grouping
some other way, not simply swap in the better-fitting model.

**No PDF extraction, no dual-source corporate-action verification, no ATR-scaled
extreme factor, no SCD Type 2 symbol master.** Each covered above in the
decision its threshold or format belongs to (decisions 1, 4, and 3
respectively); each rejected for a stated, specific reason rather than for
being generically "too much work."

---

*Numbers cited above were re-verified against the live database and the
replay harness (`app/eval/replay_runner.py`) on 2026-09-08, after fixing the
`DISCREPANCY`-suppression gap described in decision 4 — funnel and
false-positive figures reflect that fix, not the numbers a run before it would
have produced.*
