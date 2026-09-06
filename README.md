# Smart Market Watchlist

Smart Market Watchlist is a reading instrument for market change. Its thesis is
**subtraction over attention-manufacturing**: the product removes corporate-action
artefacts, market-wide moves, sector duplicates, and low-ranked candidates before
asking a person to read. A quiet result is a valid result.

## 1. The Product Thesis

The system treats attention allocation as an engineering control. It first
removes observations that are explained, duplicated, or below the configured
attention budget, then presents the remaining changes with their evidence.

### Academic Rationale for the Six Decisions

1. **Attention dictates the choice set.** Barber and Odean (RFS, 2008)
   established that retail investors are net buyers of attention-grabbing
   assets, including assets with abnormal volume, extreme returns, or news
   appearances. Ranking determines the visual choice set before investor
   preferences are evaluated, so attention allocation is the primary causal
   lever on user risk.
2. **Budgeting is a safety mechanism.** FCA Occasional Paper 66 and its
   associated research note found that untargeted push notifications increased
   trading frequency by 11% and the share of trades in high-risk assets by 8%,
   with stronger effects among younger or less experienced investors.
   `BRIEF_MAX_ITEMS = 5` is therefore a risk and safety control, not a cosmetic
   interface limit.
3. **Information asymmetry and uncertainty.** Gargano and Rossi (RFS, 2018)
   found that investor attention correlates positively with portfolio returns
   when concentrated on high-uncertainty assets with available public
   disclosures. Linking attention to corporate filings operationalizes this
   condition.
4. **News-driven continuation versus noise reversal.** Boudoukh, Feldman,
   Kogan, and Richardson (NBER Working Paper 18725) showed that extreme price
   moves with identified news exhibit forward continuation, while extreme moves
   without identifiable news tend to mean-revert. The `EXPLAINED` versus
   `UNEXPLAINED` classification is therefore part of the forward-return model,
   not merely a copy label.
5. **Delivery percentage as churn versus conviction.** Security-wise deliverable
   positions published daily by NSE quantify the fraction of traded volume
   settled into demat accounts rather than closed intraday. Standardizing
   delivery percentage with a logit transform against a 20-session baseline
   supplies an India-specific conviction signal absent from conventional
   watchlists.
6. **Regulatory anchoring.** The base filter uses SEBI LODR Regulation 30(11)
   Material Price Movement thresholds, circular dated 21 May 2024: 3.0%, 4.0%,
   and 5.0% price bands benchmarked against Nifty 50 at 09:30 IST. The gate
   supplies objective, circular-governed significance thresholds.

## The Model We Did Not Build

### Why machine learning was deliberately rejected for Day 1

- **Cold-start absence of labels.** Ranking is a supervised learning task. At
  launch there are no user interaction logs. Inventing synthetic targets would
  falsify the validation loop.
- **Unregistered advice liability.** If the training objective is forward
  abnormal return (`AR`), the system becomes a return-predicting advisory engine
  rather than an attention filter, creating a regulatory boundary the first
  version does not cross.
- **Auditability invariant (N1).** Every surfaced rank must be defensible down
  to econometric inputs: `alpha`, `beta`, residual standard deviation
  `sigma_epsilon`, and the relevant z-scores, through
  `/api/brief/explain/{id}`. An opaque neural network or tree ensemble cannot
  provide the same exact input trace.

### Concrete v2 learned re-ranker specification

- **Label formulation.** Log one interaction event per brief impression:
  `y_i in {0, 1}`, where `1` means the user expanded the item or inspected
  “why this?”.
- **Position-bias correction.** Apply inverse propensity weighting to training
  samples:
  `w_i = 1 / P(Examine | Rank r)`.
  This corrects the natural visual advantage of rank 1.
- **Architecture and features.** Train a pairwise or listwise gradient-boosted
  decision tree, such as LightGBM or LambdaMART, to predict user utility as a
  residual multiplier over the statistical score. The base event-study
  econometric score remains a non-zero anchor feature.
- **Regulatory invariant.** The exchange MPM gate remains external to the model
  pipeline. No learned weight or inference model may suppress or deprioritize
  an exchange-mandated material price disclosure.

## Incumbent Gap Analysis

| Capability | Zerodha Kite | Apple Stocks | MarketBeat | Smart Market Watchlist |
|---|---|---|---|---|
| **Temporal Reference** | Previous close (exchange-defined) | Previous close | Previous close | Personal read cursor (`t_last_seen`) |
| **Market-Wide Selloffs** | 20 individual red rows | Muted red list | Repeated price alerts | 1 aggregated rollup line |
| **Corporate Action Ex-Dates** | Naive −50% panic drop | Unadjusted price drop | Spurious crash alert | Suppressed; holding-value notice emitted |
| **Institutional Conviction** | Not available | Not available | Volume only | Logit delivery z-score (NSE demat data) |
| **Silence Handling** | Always fills the screen | Blank when unchanged | Pushes promotional alerts | Full-item quiet line (“Nine others: nothing notable”) |

## Submission defense

### Architecture of registers

The interface has two explicit registers:

- **Terminal** is the market-facing surface: high density, tabular JetBrains
  Mono figures, and directional `--up` / `--down` colour where the market itself
  is being described. It is used by `/overview`, `/watchlist/:id`,
  `/symbol/:symbol`, `/eval`, and `/settings`.
- **Dispatch** is the judgement-facing surface: low density, editorial Source
  Serif prose, a narrow reading measure, and monochrome geometry for movement.
  Confidence is encoded with final, provisional, and stale tones rather than
  directional red or green. It is used by `/brief`.

The landing and authentication surfaces introduce the distinction without
pretending that a public page is a market terminal.

### Load-bearing decisions

**17-session decay.** The reading cursor is anchored to Wednesday 12 August 2026.
Session distance is counted from the generated trading-session axis, not elapsed
calendar days. The decay therefore follows actual exchange sessions and preserves
the example state of 17 sessions since the last look. Weekends and holidays do
not become synthetic observations. The score multiplier uses
`exp(-age_sessions / DECAY_TAU_SESSIONS)` with `DECAY_TAU_SESSIONS = 5.0`;
personal boosts are capped at `PERSONAL_CAP = 2.0`.

**Funnel conservation.** The dispatch budget is conserved:

```text
Evaluated (41)
- Corporate action suppression (2)
- Market-wide suppression (11)
- Sector grouping (4)
- Below-cap filtering (20)
= Surfaced (4)
```

The numbers are an accounting trail, not decorative dashboard statistics.

**Muhurat and non-standard sessions.** Session-day membership widens through
23:59:59 IST when a circular-governed session does not use the standard close.
This prevents a legitimate Muhurat or special session from being assigned to the
wrong day without inventing a fake close time. The trading calendar remains the
authority for actual session points.

**Zero-credential evaluation.** The “Open the demo account” path is the primary
entry point. It establishes the seeded demo state and takes the evaluator directly
to `/brief`; no broker credential, exchange token, or account setup is required.

## Regulatory grounding

The constants registry records the following framework without UI reinterpretation:

> Framework on Material Price Movement (Equity Cash Markets), NSE/BSE,
> 21 May 2024, under SEBI LODR Reg 30(11).

The MPM tiers in the registry are:

| Price band | MPM threshold |
|---|---:|
| ₹0 to ₹100 | 5.0% |
| Above ₹100 to ₹200 | 4.0% |
| Above ₹200 | 3.0% |

The related anchors are a minimum index adjustment of 1.0%, an index snapshot at
09:30 IST, and no intraday index substitution for the MPM calculation. Disclosure
timelines are retained as:

> SEBI LODR Reg 30(6) disclosure timelines

The public evidence link is the [SEBI circular index](https://www.sebi.gov.in/legal/circulars.html).
The implementation source is [backend/app/constants.py](backend/app/constants.py),
with the frontend mirror in [frontend/src/lib/constants.js](frontend/src/lib/constants.js).

## API contract synchronization

The evaluation API exposes `GET /api/eval/funnel`,
`GET /api/eval/cases`, and `GET /api/eval/continuation`. The documented
`GET /api/eval/suppression-cases` name remains a compatibility alias for
`/api/eval/cases`. Brief payloads include the cursor, budget, quiet line, market
rollup, corporate-action notices, provisional/restatement fields, and explain
links; explain payloads include `inputs_hash`, completeness, decision path, and
the score sections required by the frontend boundary schema.

## Running the submission

```powershell
Set-Location frontend
npm install
npm run dev
```

The demo does not require a backend for the public walkthrough. Mock transport
and synthetic quote ticks provide deterministic screen states locally.

For the evaluator path, see [docs/DEMO_WALKTHROUGH.md](docs/DEMO_WALKTHROUGH.md).

## Verification

```powershell
Set-Location frontend
node scripts/check-prohibitions.mjs
npm test
npm run build
```

The prohibition check enforces JavaScript-only source, token usage, banned copy,
arrow-free controls, and the sanctioned amber locations.

## Technical Limitations & Data Provenance

- **Cash equity scope.** Coverage is limited to NSE cash equities in the EQ, BE,
  and BZ series. Derivatives (F&O) are excluded because the absence of fixed
  circuit price bands invalidates the MPM band-hit branch.
- **Price return (PRI) versus total return (TRI).** Cash dividends retain
  `price_factor = 1.0` in the price series. Dividend drops are not adjusted out
  of the price chart, preserving consistency with official exchange 52-week
  quotes; they are captured through corporate-action notices.
- **Split-invariant turnover.** Activity abnormality uses rupee turnover,
  `Price × Volume`, which is split- and bonus-invariant. Long-term multi-year
  price-level drift is treated as negligible over the 20-session rolling
  baseline window.
- **Single-page architecture.** The frontend uses React 18 and Vite without
  server-side rendering. First paint uses a 1:1 matching skeleton layout so
  loading geometry does not introduce cumulative layout shift.

## §13 Evaluation & Self-Audit

The deterministic replay covers 200 symbols across 126 historical sessions.
The continuation comparison reports five-session forward abnormal returns without
reshaping the sample: explained filings use `n = 18`, mean AR `0.40%`, median AR
`0.20%`, and same-direction `50%`; unexplained abnormal movement uses `n = 22`,
mean AR `1.70%`, median AR `1.30%`, and same-direction `68%`. This proves the
evaluation page can distinguish explanation from persistence; it does not claim
that explanation removes all subsequent movement.

The five audited false-positive modes are:

1. **Late-evening filing timing mismatch:** a filing at 15:28 IST may arrive in
   the 18:00 ingest, so the mitigation preserves provisional state and links the
   later filing before final restatement.
2. **Institutional morning block deal volume:** a block can distort turnover;
   the mitigation separates block-aware volume from ordinary ADV.
3. **Passive index rebalancing front-running:** predictable index flow can look
   abnormal; the mitigation checks the 09:30 index snapshot and market context.
4. **ASM/GSM circuit locks on low free-float:** a locked print is not ordinary
   liquidity; the mitigation routes band and liquidity states through freshness
   suppression.
5. **Sympathetic sector drift on diversified or exempt revenue streams:** sector
   movement can over-group unlike businesses; the mitigation requires peer count,
   attribution, and company-specific context before grouping.
