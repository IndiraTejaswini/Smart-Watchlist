# FRONTEND_SPEC.md
## Smart Market Watchlist — visual design system and screen specification
### React 18 + Vite + JavaScript + Tailwind v4 · web only · English only

> **This document supersedes `ARCHITECTURE.md` §17 and expands `BUILD_PLAN.md`
> Phase 12.** Where they disagree, this document wins on anything visual. Where
> this document is silent on behaviour, data, or API shape, `ARCHITECTURE.md`
> still governs — especially §16 (API contract) and §21 (Constants Registry).

---

## 0. The one thing to understand before designing anything

This product's argument is **subtraction**. It looked at 41 changes and showed
you 4. Every visual decision either supports that or undermines it.

That does **not** mean the interface should be plain. A plain interface is not the
same as a disciplined one. The goal is an app that looks expensive, precise and
serious — the way a professional instrument looks expensive — while spending its
visual energy on exactly one idea instead of scattering it across twelve cards.

**Spend the boldness in one place: the cursor spine (§3).** Everything else stays
quiet and immaculate.

---

## 1. Design direction

### 1.1 Subject and audience

An Indian retail investor with a watchlist they have stopped being able to read.
Fourteen to two hundred and fifty names, a red-and-green table, no idea which one
deserves the next thirty seconds. The product is the thing that answers that.

The vernacular this design draws from is the **instrument**, not the poster and
not the SaaS dashboard: exchange terminals, the bhavcopy, ticker tape, settlement
data, the numbered clause of a SEBI circular. Precision instruments are dark,
dense, monospaced and unornamented — and they are beautiful because every mark on
them means something.

### 1.2 The direction: **Terminal and Dispatch**

The app runs in one continuous dark environment, but shifts **register** between
two kinds of surface. The shift is carried by typography and density, never by
changing the background:

| | **Terminal** | **Dispatch** |
|---|---|---|
| Where | Overview, watchlist table, symbol page, charts | The Brief |
| Type | Mono figures, grotesque labels, tight leading | Serif prose, 20px, generous leading |
| Density | High. Tabular, hairline-divided, scannable | Low. One column, long measure, room to breathe |
| Colour | Green and red carry price direction | No green, no red. Confidence colours only |
| Job | Show the market as it is | Show what a careful reader concluded |

**Why this is the right idea and not just a nice one:** the product's whole claim
is that a market table and a considered judgement are different objects that
every existing app renders identically. Making them *look* like different objects
is the thesis expressed in the interface. Say exactly that when the jury asks
about the UI.

### 1.3 What this deliberately is not

Not a cream-paper broadsheet with hairline rules. Not a grid of identical rounded
cards with soft grey shadows. Not gradient washes, not glassmorphism, not a
tracked-out all-caps eyebrow above every heading, not a monospace face used
decoratively on labels that are not data, not `→` glued onto button text. Every
one of those is a default rather than a decision, and a jury that reviews forty
submissions will have seen all of them by lunchtime.

---

## 2. Tokens

### 2.1 Colour

Six structural values, five semantic. That is the entire palette. If a colour is
needed that is not on this list, the answer is a different value from this list.

```css
:root {
  /* Structure */
  --abyss:    #080D14;  /* page ground — blue-black, never neutral black */
  --panel:    #101927;  /* raised surfaces, table row bands, chart plot area */
  --panel-hi: #162233;  /* hover, selected row, active tab */
  --hairline: #1E2A3D;  /* every divider and border in the app */
  --chalk:    #E6EAF0;  /* primary text */
  --slate:    #7D8DA3;  /* secondary text, metadata, axis labels */

  /* Semantic — data confidence. Used on the Brief and on every provenance line. */
  --final:    #3DD8A0;  /* exchange-final data */
  --provis:   #E8B04B;  /* provisional, will be restated */
  --stale:    #566274;  /* stale, absent, below liquidity floor */

  /* Semantic — price direction. TERMINAL SURFACES ONLY. Never on the Brief. */
  --up:       #2FCE8A;
  --down:     #FF5A52;

  /* The accent */
  --flare:    #F0A500;
}
```

**`--flare` is not a decorative accent. It is the cursor.** It appears in exactly
three places in the entire application: the cursor spine (§3), the keyboard focus
ring, and the "you are here" marker on a chart. Nowhere else — not on buttons,
not on links, not on badges, not on the logo. It marks a position in time and
nothing else.

That constraint is what makes it powerful. The moment amber appears anywhere
decorative, the app loses the one signal a user learns to look for.

**Green and red are forbidden on the Brief.** The Brief carries direction with a
signed number and a magnitude bar that extends left or right of a centre rule.
Colour there means confidence, not direction. The live table three clicks away is
green and red as expected, and the contrast between them is the point.

### 2.2 Type

```
Prose      Source Serif 4 Variable   Brief items, landing headline, long copy
UI         Archivo Variable          nav, labels, buttons, table headers, forms
Figures    JetBrains Mono Variable   every number, ticker, timestamp, clause ref
```

Self-host all three:

```bash
npm i @fontsource-variable/source-serif-4 \
      @fontsource-variable/archivo \
      @fontsource-variable/jetbrains-mono
```

**Rules.**

- **Every numeral in the application is JetBrains Mono.** Prices, percentages,
  z-scores, dates, times, symbol tickers. Non-negotiable — without a fixed
  advance width, a table of live prices jitters on every tick.
- Enable `font-variant-numeric: tabular-nums lining-nums` globally on `.num`.
- Source Serif 4 is used at **body sizes for actual sentences**, and once at
  display size on the landing hero. It is never a decorative headline face on
  interior screens.
- Archivo carries all interface chrome. Set display sizes at `letter-spacing:
  -0.02em`; leave body tracking at zero.
- No all-caps labels anywhere. Sentence case throughout.

**Scale** (rem, 16px root):

```
0.75   12px   axis labels, dense table metadata
0.8125 13px   table body, form labels
0.875  14px   UI default, nav, buttons
1.0    16px   secondary prose
1.25   20px   Brief item prose            ← the reading size
1.75   28px   section headings, cursor sentence
3.0    48px   landing hero (Source Serif 4, weight 400, tracking -0.03em)
```

Line length: cap prose at **62ch**. Serif on dark needs air — `line-height: 1.65`
on Brief prose, `1.45` on UI text, `1.3` on tabular rows.

### 2.3 Space, shape, elevation

- 4px base grid. Section rhythm in multiples of 8.
- **Border radius 3px** on inputs, buttons and chart panels. Not 8, not 12, not
  full. An instrument has machined edges, not pillows.
- **No box shadows anywhere.** Separation comes from `--hairline` borders and
  from the `--panel` / `--abyss` value step. Shadows on a near-black ground are
  invisible anyway, and reaching for them is the SaaS-card reflex.
- Table rows: 1px `--hairline` bottom border. No zebra striping — the mono
  figures already align the eye.

### 2.4 Motion

One orchestrated moment on the landing page (§5.1). Everything else is a direct
response to a user action:

- Cursor drag → items restack, 220ms, `cubic-bezier(0.2, 0, 0, 1)`.
- Row expand → height auto, 180ms.
- Tick update → **no animation at all.** Flashing a row on price change is the
  attention-manufacturing pattern this entire product argues against. The number
  changes. That is the notification.
- `@media (prefers-reduced-motion: reduce)` collapses every duration to 0ms.

---

## 3. The cursor spine — the signature element

**This is the one memorable thing in the app. Build it first and build it well.**

A persistent horizontal band, 56px tall, sitting directly under the nav on every
authenticated page.

```
┌──────────────────────────────────────────────────────────────────────┐
│  12 Aug 21:04                                              now       │
│  ●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━▶ │
│    │      ││        │           │  ││    │            │      │       │
│    ·      ··        ▲           ·  ▲·    ·            ▲      ·       │
│  17 sessions since you last looked                                   │
└──────────────────────────────────────────────────────────────────────┘
```

- The rail is a 2px `--flare` line. It is the only amber in the interface.
- The left handle is the cursor. **It is draggable.** Dragging it re-queries
  `/api/brief` and the whole page updates.
- Tick marks below the rail are trading sessions, from `trading_calendar` —
  weekends and exchange holidays leave real gaps in the spacing, which makes the
  market's actual rhythm visible.
- Signal marks sit on the sessions: a small dot for a scored signal, a filled
  triangle for one that was surfaced. Hovering a mark shows the symbol.
- On `/symbol/:symbol` the spine filters to that symbol's signals only.

**Why this earns its place:** the product's central concept is a reading cursor
for markets — something no financial product has. Making it a physical,
draggable object that persists across every screen turns the concept from a
sentence in the README into something the jury can grab with a mouse. It is also
what makes the app demo correctly at 2am on a Sunday with the market shut.

**Accessibility:** the handle is a real `<input type="range">` styled to
disappear, so keyboard and screen-reader support come free. Arrow keys move one
session, Home jumps to the start of retention, End to now.

---

## 4. Application shell

```
┌────────────────────────────────────────────────────────────────────┐
│ ◆ ticker    Brief   Overview   Lists   Evaluation      ⌘K    [AR] │  nav 52px
├────────────────────────────────────────────────────────────────────┤
│ [ CURSOR SPINE — §3 ]                                              │  56px
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  route content                                                     │
│                                                                    │
├────────────────────────────────────────────────────────────────────┤
│ ● NSE live · bhavcopy 4 Sep final · delivery final                 │  status 28px
└────────────────────────────────────────────────────────────────────┘
```

**Nav.** `--abyss` ground, 1px `--hairline` bottom. Wordmark left as a small
filled diamond plus the product name in Archivo 600. Four links. Active link is
`--chalk` with a 2px `--chalk` underline; inactive `--slate`. A `⌘K` command
palette for symbol search. User initials in a 28px `--panel` circle, right.

**Status strip.** Fixed to the bottom. Always visible, always honest. A dot in
`--final` / `--provis` / `--stale`, then the live feed state, the last bhavcopy
date, and whether delivery data is final. When the feed dies, this strip is what
tells the user — and every price on screen simultaneously drops to `--stale`.

This strip is a differentiator. Almost no consumer product tells you the age and
confidence of what it is showing you. Keep it visible at all times.

---

## 5. Screens

### 5.1 `/` — Landing (public)

The hero is not a headline over a gradient. **The hero is the product's argument,
running.**

```
┌───────────────────────────────────────────────────────────────────────┐
│  ◆ Smart Watchlist                    How it works   Evidence  [Open] │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   You have 14 stocks on              ┌───────────────────────────┐   │
│   your watchlist. Three of           │ RELIANCE    2,481.50 ▁▂▁  │   │
│   them did something.                │ TCS         3,902.10 ▁▁▂  │   │
│                                      │ HDFCBANK    1,644.75 ▂▁▁  │   │
│   Every watchlist shows you          │ INFY        1,502.30 ▁▂▃  │   │
│   what changed since the             │ ... 37 more rows ...      │   │
│   market closed. This one            │                           │   │
│   shows you what changed             │        ↓ 2.5s ↓           │   │
│   since *you* last looked,           │                           │   │
│   and stays quiet the rest           │ TATAMOTORS  −7.2%         │   │
│   of the time.                       │ Q2 results, filed Tue     │   │
│                                      │                           │   │
│   [ Open the demo ]  [ Sign in ]     │ BHARTIARTL  +4.1%         │   │
│                                      │ No filing found           │   │
│   No signup needed for the demo.     │                           │   │
│                                      │ 11 others: nothing        │   │
│                                      └───────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────┘
```

**The one orchestrated motion in the product.** On load, the right panel shows
~40 ticker rows at `--slate`. Over 2.5 seconds they dim to `--stale` and collapse
out, leaving three items plus the quiet line. It runs **once**, never loops, and
is skipped entirely under `prefers-reduced-motion` (which renders the end state).

Nothing else on this page animates on scroll. No fade-and-slide-up sections.

**Sections below the hero,** each separated by a full-width `--hairline` rule and
generous space — not cards:

1. **The gap.** Three short paragraphs in Source Serif at 20px, left-aligned,
   62ch: every watchlist measures change against yesterday's close, a date the
   exchange picked; nobody has a read cursor for markets; nobody ever says
   nothing happened.
2. **How it decides.** A four-step horizontal diagram — regulatory gate,
   statistical abnormality, explanation, personal ranking — with the real
   numbers under each. Numbered markers are appropriate here because it genuinely
   is a sequence.
3. **The subtraction.** The funnel from §18.2 of the architecture, rendered as a
   stepped bar. Real numbers from the eval run, with a line stating the source.
4. **Where the numbers come from.** The MPM threshold table, verbatim, with the
   SEBI circular linked. This is the credibility section — a jury member who
   clicks that link is the one you want.
5. **Footer.** Data provenance, scope limitations stated plainly (NSE cash
   equity only, no BSE, no derivatives), links to the repo and both docs.

**Copy rules.** No marketing superlatives. No "revolutionary", "powerful",
"seamless", "AI-powered". No fake testimonials, no invented logo strip, no
metrics you have not measured. The tone is a competent person explaining
something, which is also the tone that survives a technical jury.

### 5.2 `/login` and `/register`

Split screen. Left: the form on `--abyss`, max 360px, centred vertically. Right:
a full-bleed `--panel` region showing a live-looking ticker column at 40% opacity,
static.

Fields in Archivo, inputs `--panel` with `--hairline` border and a 3px radius,
focus ring in `--flare`.

**The demo path must be the most prominent control on the page.** A full-width
button reading "Open the demo account" above a hairline divider, with the
email/password form below it.

**Never make a jury member create an account to see your work.** A single click
signs into a seeded user with a populated watchlist, a cursor set three weeks
back, and real signals waiting. This is worth more than any feature on this page.

### 5.3 `/overview` — the dashboard

Terminal register. This is where the charts live, and it must be immaculate:
aligned baselines, consistent axis treatment, no chart junk.

```
┌────────────────────────────────────────────────────────────────────┐
│ [ CURSOR SPINE ]                                                   │
├──────────────────┬──────────────────┬──────────────────────────────┤
│ NIFTY 50         │ NIFTY BANK       │ NIFTY MIDCAP 150             │
│ 24,812.30        │ 52,104.85        │ 21,338.90                    │
│ −1.84% ▁▂▁▃▂▁▁   │ −2.10% ▂▁▁▂▃▁▂   │ −0.92% ▁▁▂▁▂▂▃               │
├──────────────────┴──────────────────┴──────────────────────────────┤
│  Your list against the market            since 12 Aug              │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                                              lightweight-     │ │
│  │      two series: your equal-weight list      charts area      │ │
│  │      vs Nifty 50, rebased to 100             + amber cursor   │ │
│  │                                              marker at the    │ │
│  │                                              cursor date      │ │
│  └──────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────┬──────────────────────────────────┤
│ Attention budget                │ Where the movement was           │
│                                 │                                  │
│ Detected            41  ████████│ IT          ████████  −3.9%      │
│ Corporate action     2  ▌       │ Banking     ██████    −2.4%      │
│ Market-wide         11  ██      │ Auto        ███       −1.1%      │
│ Sector-grouped       4  ▌       │ FMCG        ██        +0.3%      │
│ Below the cap       19  ███     │ Pharma      █         +0.8%      │
│ Shown                4  ▌       │                                  │
│                    [ see how ]  │                                  │
├─────────────────────────────────┴──────────────────────────────────┤
│  Recent signals                                                    │
│  4 Sep 15:29  TATAMOTORS  −7.2%  explained   Q2 results     final  │
│  4 Sep 14:02  BHARTIARTL  +4.1%  unexplained no filing      final  │
│  3 Sep 15:30  IDEA        —      corp action 1:1 bonus      final  │
└────────────────────────────────────────────────────────────────────┘
```

**Chart rules, applied to every chart in the app:**

- `lightweight-charts`. Install it, then read
  `node_modules/lightweight-charts/package.json` for the installed major version
  and use the matching API — v4 and v5 differ on series creation. **Do not guess
  from memory.**
- Chart background `--panel`, grid lines `--hairline` at 40% opacity, horizontal
  only. No vertical grid.
- Axis labels JetBrains Mono 12px in `--slate`.
- One `--flare` vertical price line at the cursor date on every time series.
- Series colour: `--up` / `--down` on price, `--chalk` on the market benchmark
  so the user's own line reads as the subject and the index as the reference.
- Watermarks off. Trading-hours gaps preserved — do **not** fill weekends.
- Every chart panel carries a caption line in `--slate`: what the series is, what
  it is adjusted for, and its as-of time.

### 5.4 `/brief` — Dispatch register

The product. Everything above exists to bring the user here.

```
┌────────────────────────────────────────────────────────────────────┐
│ [ CURSOR SPINE ]                                                   │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│   Since you last looked on Tuesday 12 August at 21:04,             │
│   four things changed.                                             │
│                                                                    │
│   The market fell over this period. Nifty 50 −4.1%.                │
│   Eleven of your fourteen names moved with it.                     │
│   ──────────────────────────────────────────────────────────       │
│                                                                    │
│   TATA MOTORS                                −7.2%   ◀━━━━━▌       │
│                                                                    │
│   Down 7.2% across the three sessions since you last looked.       │
│   Its largest three-day stock-specific move in fourteen months.    │
│   Q2 results, filed Tuesday at 18:40.                              │
│                                                                    │
│   ● As of 15:29 on 4 Sep · final                    why this?      │
│   ──────────────────────────────────────────────────────────       │
│                                                                    │
│   ... three more ...                                               │
│   ──────────────────────────────────────────────────────────       │
│                                                                    │
│   Nine others: nothing notable.                                    │
│   ──────────────────────────────────────────────────────────       │
│                                                                    │
│   IDEA — 1:1 bonus, ex-date 14 August. Price adjusted from         │
│   ₹2,480 to ₹1,240. Your holding value is unchanged.               │
│   ──────────────────────────────────────────────────────────       │
│                                                                    │
│   We looked at 41 changes and showed you 4.        see how →       │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**Non-negotiables on this screen:**

- **No cards.** Items are separated by hairline rules. Cards give equal visual
  weight to unequal items, which contradicts the whole idea of a ranked brief.
- Item prose is Source Serif 4 at 20px / 1.65, measure capped at 62ch.
- The ticker and the percentage are JetBrains Mono. The magnitude bar extends
  left or right of a centre rule — **direction by geometry, not by hue.**
- The confidence dot before the provenance line is the only colour in an item:
  `--final`, `--provis`, or `--stale`.
- **"Nine others: nothing notable" is set at full item size**, not shrunk to a
  footnote. It is a finding, not an apology.
- "why this?" opens a side panel rendering `/api/brief/explain/{id}` — every
  intermediate value, every branch of the classification, every multiplier, the
  inputs hash. Present it as a plain definition list in mono. This panel is what
  you open live when the jury asks why an item ranks second.
- The budget line at the bottom is permanent, not a tooltip.

**Empty state.** When the cursor is recent and nothing has happened:

> Nothing notable since 09:15 this morning.
> Your fourteen names moved less than their own normal range.
> Move the cursor back to see a longer period.

Set in the same serif at the same size as a real item. The empty state is a
first-class output of this system, not a failure.

### 5.5 `/watchlist/:id` — Terminal register

Conventional and deliberately so. Muscle memory is not the enemy here.

Virtualised via `@tanstack/react-virtual` with pre-allocated row heights.
Columns: freshness dot, symbol, last price, change, change %, turnover, delivery
%, 20-day range sparkline. All figures mono, right-aligned, `tabular-nums`.
`--up` / `--down` on the change columns only.

Row hover `--panel-hi`. Drag to reorder via the fractional index keys. Only rows
in the viewport hold a WebSocket subscription, resubscribed on scroll with a
200ms debounce. `contain: content` on every row; `React.memo` comparator that
fires only on `ltp`, `chp`, `state`.

When the feed state is `FEED_DOWN` or `HALTED_MARKET`, every price drops to
`--stale` and the bottom strip explains why in plain English.

### 5.6 `/symbol/:symbol`

Two columns. Left 60%: `lightweight-charts` candlestick on the adjusted series,
with signal markers plotted on the dates the engine fired and a `--flare` line at
the cursor. A toggle switches to the as-traded series — and on a stock with a
corporate action, flipping that toggle is a genuinely convincing demo moment.

Right 40%: a "what we know" panel — every baseline with its window and quality
flag, the 09:30 index snapshot source, the liquidity position, then the signal
history for this symbol, then linked filings with their timestamps.

### 5.7 `/eval` — the jury page

Make this the best-looking page in the application.

The funnel as a stepped horizontal bar chart, each step labelled with its count
and its rule. The three corporate-action suppression cases side by side: naive
view on the left showing a −50% red number, our view on the right showing the
notice. The continuation table — explained versus unexplained forward five-day
abnormal return, with n, mean, median and same-direction percentage. The parser
coverage numbers. The self-audit of five false positives, written out.

### 5.8 `/settings`

Cursor controls, the item cap shown and explained as a safety control rather than
a preference, and a data-provenance table listing every source with its last
successful ingest time and row count.

---

## 6. Component inventory

Build these before any screen. No component library — hand-build against the
tokens, because a default component kit is exactly what makes an interface look
generated.

```
CursorSpine        the signature element, §3
StatusStrip        bottom bar, feed and data state
Num                mono numeric with tabular figures, sign, unit, colour policy
FreshnessDot       final / provisional / stale
MagnitudeBar       centre-rule bar, direction by side
BriefItem          serif prose block, hairline separated
QuietLine          "N others: nothing notable"
BudgetLine         "we looked at N and showed you M"
CorpActionNotice   the suppression explainer
ExplainPanel       slide-over rendering /api/brief/explain
PriceChart         lightweight-charts wrapper — resize observer, cleanup on unmount
Sparkline          inline 60x18 SVG, no library
DataTable          virtualised, hairline rows, mono figures
Funnel             stepped bar for the budget and /eval
SessionBadge       PRE_OPEN / REGULAR / CLOSED / HALTED
EmptyState         icon-free, one sentence, one action
```

`PriceChart` must handle unmount cleanup (`chart.remove()`) and container resize
via `ResizeObserver`. A leaked chart instance on route change is the most common
bug with this library.

---

## 7. Quality floor

- Responsive to 768px. Below that, the watchlist table becomes a stacked list.
  **No mobile app, no React Native, no PWA manifest.**
- Visible `--flare` focus ring on every interactive element. Full keyboard path
  through the cursor spine, the Brief, and the explain panel.
- 4.5:1 contrast on all body text. `--slate` on `--abyss` passes; verify before
  using it anywhere smaller than 13px.
- Colour is never the only signal: the freshness dot always sits beside a text
  label; the magnitude bar always sits beside a signed number.
- `prefers-reduced-motion` respected everywhere.
- Every screen has a designed empty state and a skeleton that matches the loaded
  layout's geometry, so nothing shifts when data arrives.
- No `.ts` or `.tsx` files. No Next.js. Zod validates API responses at the
  boundary; JSDoc typedefs everywhere else.

---

## 8. Self-critique before you call it done

Take a screenshot of every screen and check:

1. Is `--flare` anywhere other than the cursor, a focus ring, or a chart marker?
   Remove it.
2. Are there cards on the Brief? Remove them.
3. Is any numeral not in JetBrains Mono? Fix it.
4. Does anything animate that the user did not trigger, other than the landing
   hero? Remove it.
5. Is there an all-caps label, a decorative monospace label, or a `→` inside
   button text? Remove it.
6. Does the Brief look like the watchlist table? It must not.
7. Remove one more thing.
