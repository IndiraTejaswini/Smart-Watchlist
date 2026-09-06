/**
 * constants.js — the frontend mirror of ARCHITECTURE.md §21, the Constants
 * Registry.
 *
 * BUILD_PLAN.md A1/R1 makes `backend/app/constants.py` the single source of
 * truth. JavaScript cannot import it, so this file mirrors the subset the
 * interface actually needs and cites the registry line for each value. Nothing
 * here is derived, rounded, or adjusted. If a number the UI needs is not in §21,
 * it does not get invented here — the task stops and the human is asked.
 *
 * Values marked [REGULATORY] trace to a SEBI/NSE instrument and must never be
 * altered, refactored or "simplified".
 */

// ─── [REGULATORY] §21 ───────────────────────────────────────────────────────
// Framework on Material Price Movement (Equity Cash Markets), NSE/BSE,
// 21 May 2024, under SEBI LODR Reg 30(11). Rendered verbatim in the landing
// page threshold table (FRONTEND_SPEC §5.1 section 4).
export const MPM_TIER_THRESHOLDS = [
  { priceUpTo: 100.0, thresholdPct: 5.0 },
  { priceUpTo: 200.0, thresholdPct: 4.0 },
  { priceUpTo: Infinity, thresholdPct: 3.0 },
];
export const MPM_INDEX_ADJUST_MIN_PCT = 1.0;
export const MPM_INDEX_SNAPSHOT_TIME = "09:30";

// Session defaults, IST. The trading_calendar overrides these per date.
export const SESSION_PRE_OPEN_START = "09:00";
export const SESSION_OPEN = "09:15";
export const SESSION_CLOSE = "15:30";

// ─── [TUNED] §21 ────────────────────────────────────────────────────────────
export const BRIEF_MAX_ITEMS = 5;
export const BRIEF_CACHE_TTL_SECONDS = 60;

// Cursor spine range: the cursor cannot be dragged past retention, because
// beyond it there are no signals to show.
export const SIGNAL_RETENTION_DAYS = 90;

// Freshness state machine, §14.2. Seconds.
export const FEED_HEARTBEAT_MAX_S = 10;
export const DELAYED_S = 15;
export const BAND_LOCK_MIN_S = 60;
export const STALE_THIN_S = 300;

// Ranking, §13. The explain panel renders every one of these, because §16.2's
// whole purpose is that a reader can check the arithmetic rather than trust it.
export const W_SCAR = 0.45;
export const W_TURNOVER = 0.25;
export const W_DELIVERY = 0.2;
export const W_EXTREME = 0.1;

// The clamp ceilings in the §13.1 base score.
export const CLAMP_SCAR = 6;
export const CLAMP_TURNOVER = 5;
export const CLAMP_DELIVERY = 4;

/** §13.2 — classification multipliers, and why each one is what it is. */
export const CLASSIFICATION_MULTIPLIERS = {
  EXPLAINED_A: { value: 1.35, label: "Explained (Para A)", why: "Identified news, which predicts continuation" },
  EXPLAINED_B: { value: 1.15, label: "Explained (Para B or other)", why: "Weaker evidence of materiality" },
  UNEXPLAINED: { value: 1.0, label: "Unexplained", why: "Baseline" },
  SECTOR_WIDE: { value: 0.55, label: "Sector-wide", why: "Partly explained by something other than the company" },
  MARKET_WIDE: { value: 0.25, label: "Market-wide", why: "Rolled up separately" },
  CORPORATE_ACTION: { value: 0.0, label: "Corporate action", why: "Suppressed" },
};

/** §13.3 — personal multipliers. Multiplicative, product capped. */
export const PERSONAL_MULTIPLIERS = {
  MULT_HOLDING: { value: 1.35, label: "Holds the stock" },
  MULT_LEVEL_SET: { value: 1.3, label: "Price level set, not crossed" },
  MULT_LEVEL_CROSSED: { value: 1.8, label: "Price level crossed in the window" },
  MULT_PINNED: { value: 1.2, label: "Pinned" },
  MULT_RECENT_ADD: { value: 1.15, label: "Added less than thirty days ago" },
  MULT_NEVER_OPENED: { value: 1.1, label: "Never opened by this user" },
};
export const PERSONAL_CAP = 2.0;
export const DECAY_TAU_SESSIONS = 5.0;

// Candidate gates, §10. Shown in the explain panel beside the value that
// cleared (or failed) each one.
export const SAR_CANDIDATE_MIN = 2.0;
export const TURNOVER_Z_CANDIDATE_MIN = 2.5;
export const DELIVERY_Z_CANDIDATE_MIN = 2.0;
export const SCAR_MIN = 2.0;

// Classification, §11. The explain panel prints the branch taken at each step
// against the value it was tested on, so these appear on screen verbatim.
export const MARKET_ATTRIB_RATIO = 0.7;
export const MARKET_SAR_CEILING = 1.5;
export const SECTOR_MIN_PEERS = 4;
export const SECTOR_TOLERANCE_SD = 1.0;

// Realtime, §14.3.
export const CONFLATION_INTERVAL_MS = 400;
export const WS_MAX_SUBSCRIPTIONS_PER_CONN = 60;
export const POLL_INTERVAL_SECONDS = 5;

// ─── FRONTEND_SPEC.md, not §21 ──────────────────────────────────────────────
// Presentation timings. Cited to their spec section rather than the registry,
// because the registry governs business logic and these are not that.
export const RESTACK_MS = 220; // §2.4 cursor drag → items restack
export const ROW_EXPAND_MS = 180; // §2.4 row expand
export const VIEWPORT_RESUBSCRIBE_DEBOUNCE_MS = 200; // §5.5 / ARCHITECTURE §14.3
export const PROSE_MEASURE_CH = 62; // §2.2 line length cap

/**
 * R12 banned copy. One list, mirrored from `constants.py`, consumed by both the
 * build-time lint (scripts/check-prohibitions.mjs) and any runtime check on
 * model-generated text. Matched on word boundaries so that legitimate market
 * vocabulary — a BUYBACK corporate action, a Sensex reference — does not trip
 * a substring hit.
 */
export const BANNED_COPY = [
  "buy",
  "sell",
  "should",
  "consider",
  "opportunity",
  "target price",
  "undervalued",
  "overvalued",
  "bullish",
  "bearish",
  "act now",
  "don't miss",
  "hurry",
];

// ─── Freshness states · ARCHITECTURE §14.2 ──────────────────────────────────

/** The nine states returned by `freshness(symbol, ctx)`. */
export const FRESHNESS_STATES = [
  "LIVE",
  "DELAYED",
  "STALE_THIN",
  "BAND_LOCKED",
  "HALTED_MARKET",
  "FEED_DOWN",
  "PRE_OPEN",
  "CLOSED",
  "NO_DATA",
];

/**
 * How each freshness state renders, and what the status strip says about it.
 *
 * `tone` drives the confidence colour on the price and on the freshness dot:
 *   final  — settled, will not be restated
 *   provis — real but indicative; it will move or be restated
 *   stale  — do not read this as a live price
 *
 * FRONTEND_SPEC is explicit that FEED_DOWN and HALTED_MARKET drop prices to
 * --stale. The remaining assignments follow the same principle (R5: never
 * render a stale price as though it were live) and are listed here rather than
 * scattered through components so the policy can be reviewed in one place.
 *
 * `label` is the plain-English status-strip copy. Per §14.2 the BAND_LOCKED
 * copy must never use the word "halted" — a stock at its band is not halted.
 */
export const FRESHNESS_DISPLAY = {
  LIVE: { tone: "final", label: "NSE live", live: true },
  DELAYED: { tone: "provis", label: "NSE delayed", live: true },
  STALE_THIN: { tone: "stale", label: "No recent trades", live: false },
  BAND_LOCKED: { tone: "provis", label: "Locked at the price band", live: true },
  HALTED_MARKET: {
    tone: "stale",
    label: "Trading halted market-wide",
    live: false,
  },
  FEED_DOWN: {
    tone: "stale",
    label: "Live feed down — prices are not updating",
    live: false,
  },
  PRE_OPEN: { tone: "provis", label: "Pre-open", live: false },
  CLOSED: { tone: "final", label: "Market closed", live: false },
  NO_DATA: { tone: "stale", label: "No data", live: false },
};

/** Session phases, ARCHITECTURE §7 `session_phase(ts)`. */
export const SESSION_PHASES = ["CLOSED", "PRE_OPEN", "REGULAR", "POST_CLOSE"];

/** Session-badge copy. Sentence case — §2.2 forbids all-caps labels. */
export const SESSION_LABELS = {
  PRE_OPEN: "Pre-open",
  REGULAR: "Open",
  POST_CLOSE: "Post-close",
  CLOSED: "Closed",
  HALTED: "Halted",
};
