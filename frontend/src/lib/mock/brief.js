import { DEMO_LAST_SESSION_DATE, DEMO_NOW } from "./clock.js";
import { score } from "./scoring.js";
import { TRADING_SESSIONS } from "./tradingCalendar.js";
import { BY_SYMBOL, DEMO_WATCHLIST } from "./watchlist.js";
import { formatLongMoment, istDateIso } from "../format.js";

/**
 * brief.js — GET /api/brief?watchlist_id=&as_of=
 *
 * The payload shape is ARCHITECTURE §16.1 exactly. The *numbers* are computed
 * rather than quoted, for the reason set out in scoring.js: the explain panel
 * exists so a reader can check the arithmetic, and fixtures that do not
 * reconcile would undermine the one screen built to demonstrate rigour.
 *
 * ─── How the fourteen names account for themselves ──────────────────────────
 *
 * The brief's own arithmetic, which is asserted at the bottom of this file:
 *
 *   4  surfaced as items of their own
 *   1  IDEA — a corporate-action notice, never scored (§11.1)
 *   9  others with nothing notable
 *  ──
 *  14  the watchlist
 *
 * The market rollup and the sector group cut across that, and deliberately so.
 * A name that fell with the market did nothing *of its own* — that is §11.2's
 * entire argument — so it is counted among the nine and mentioned collectively
 * at the top. Rendering it as its own item would spend fourteen units of
 * attention on one piece of information.
 *
 * ─── Where these numbers differ from §16's example, and why ─────────────────
 *
 *   below_cap    20, not 19, so the budget sums to candidates_detected. §18.2
 *                requires each funnel step to be a strict subset of the last.
 *                Confirmed with the human.
 *   score        Derived from §13.1–13.4. §16's 1.42 is not reachable from the
 *                metrics printed beside it.
 *   weekday      §16 writes "Tue 12 Aug"; 12 August 2026 is a Wednesday. The
 *                date is load-bearing (it yields the 17 sessions the spine
 *                independently reproduces), so the date is kept.
 */

const SESSION_DATES = TRADING_SESSIONS.map((s) => s.date);

/** Age in trading sessions from a signal's date to the newest session (§13.4). */
function ageInSessions(sessionDate) {
  const from = SESSION_DATES.indexOf(sessionDate);
  if (from === -1) throw new Error(`${sessionDate} is not a trading session`);
  return SESSION_DATES.length - 1 - from;
}

/**
 * The four surfaced items, as inputs. Each one's score is derived below, and
 * the copy follows the §13.6 four-part structure: what moved, how unusual in
 * this stock's own terms, whether there is a cause, and how fresh it is.
 */
const ITEM_INPUTS = [
  {
    symbol: "TATAMOTORS",
    model: { window_sessions: 3, r_i_cum: -0.072, r_m_cum: -0.009, alpha: 0.0002, beta: 1.32, resid_sd: 0.0089, n_obs: 118, r2: 0.41, ar_signal_day: -0.0351 },
    session_date: "2026-09-04",
    family: "PRICE_MOVE",
    classification: "EXPLAINED",
    classificationKey: "EXPLAINED_A",
    personalKeys: ["MULT_HOLDING"],
    metrics: {
      pct_move: -7.2,
      turnover_z: 2.1,
      delivery_z: 0.4,
      delivery_pct: 0.61,
      extreme: false,
      mpm_triggered: true,
      mpm_threshold_used: 3.0,
    },
    what: "Down 7.2% across the three sessions since you last looked.",
    how_unusual: "Its largest three-day stock-specific move in fourteen months.",
    cause: "Q2 results, filed Tuesday at 18:40.",
    freshness: "As of 15:29 on 4 Sep. Final.",
    provisional: false,
    revision: 2,
    was_restated: true,
    completeness: ["bars", "baseline", "delivery", "announcements"],
    linked_announcement_ids: [88213, 88209],
    announcement_url: "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
  },
  {
    symbol: "BHARTIARTL",
    model: { window_sessions: 1, r_i_cum: 0.041, r_m_cum: -0.002, alpha: 0.0001, beta: 0.88, resid_sd: 0.0152, n_obs: 116, r2: 0.33, ar_signal_day: 0.0427 },
    session_date: "2026-09-04",
    family: "PRICE_MOVE",
    classification: "UNEXPLAINED",
    classificationKey: "UNEXPLAINED",
    personalKeys: ["MULT_NEVER_OPENED"],
    metrics: {
      pct_move: 4.1,
      turnover_z: 3.4,
      delivery_z: -1.9,
      delivery_pct: 0.38,
      extreme: false,
      mpm_triggered: true,
      mpm_threshold_used: 3.0,
    },
    what: "Up 4.1% on Friday, on turnover 3.4 standard deviations above its twenty-day average.",
    how_unusual: "Delivery fell to 38% while the price rose — activity without accumulation behind it.",
    cause: "No filing found. The exchange has no disclosure from this company in the window around the move.",
    freshness: "As of 15:30 on 4 Sep. Final.",
    provisional: false,
    revision: 1,
    was_restated: false,
    completeness: ["bars", "baseline", "delivery", "announcements"],
    linked_announcement_ids: [],
    announcement_url: null,
  },
  {
    symbol: "SBIN",
    model: { window_sessions: 1, r_i_cum: 0.034, r_m_cum: 0.001, alpha: 0.0001, beta: 1.05, resid_sd: 0.0134, n_obs: 119, r2: 0.52, ar_signal_day: 0.0329 },
    session_date: "2026-08-28",
    family: "DELIVERY_SHIFT",
    classification: "EXPLAINED",
    classificationKey: "EXPLAINED_B",
    personalKeys: ["MULT_LEVEL_SET"],
    metrics: {
      pct_move: 3.4,
      turnover_z: 2.9,
      delivery_z: 2.2,
      delivery_pct: 0.71,
      extreme: false,
      mpm_triggered: true,
      mpm_threshold_used: 3.0,
    },
    what: "Up 3.4% on 28 August, with delivery at 71% of traded quantity.",
    how_unusual: "Delivery 2.2 standard deviations above its own twenty-day average.",
    cause: "Board meeting outcome, filed 28 August at 16:12. Categorised under Para B.",
    freshness: "As of 15:30 on 28 Aug. Final.",
    provisional: false,
    revision: 1,
    was_restated: false,
    completeness: ["bars", "baseline", "delivery", "announcements"],
    linked_announcement_ids: [87740],
    announcement_url: "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
  },
  {
    symbol: "MARUTI",
    model: { window_sessions: 1, r_i_cum: -0.058, r_m_cum: -0.004, alpha: 0.0, beta: 1.12, resid_sd: 0.0172, n_obs: 117, r2: 0.38, ar_signal_day: -0.0535 },
    session_date: "2026-08-20",
    family: "PRICE_MOVE",
    classification: "EXPLAINED",
    classificationKey: "EXPLAINED_A",
    personalKeys: ["MULT_LEVEL_CROSSED"],
    metrics: {
      pct_move: -5.8,
      turnover_z: 2.6,
      delivery_z: 1.1,
      delivery_pct: 0.55,
      extreme: true,
      mpm_triggered: true,
      mpm_threshold_used: 3.0,
    },
    what: "Down 5.8% on 20 August, through the level you set at ₹11,000.",
    how_unusual: "A fifty-two week low, on turnover 2.6 standard deviations above normal.",
    cause: "Monthly production and sales figures, filed 20 August at 09:04.",
    freshness: "As of 15:30 on 20 Aug. Final.",
    provisional: false,
    revision: 1,
    was_restated: false,
    completeness: ["bars", "baseline", "delivery", "announcements"],
    linked_announcement_ids: [86201],
    announcement_url: "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
  },
];

/**
 * The market model, §9. Every abnormality number the explain panel shows is
 * computed here from the regression inputs rather than stated, so CAR, SCAR and
 * SAR reconcile with alpha, beta and resid_sd on screen.
 *
 *   market_component = alpha * n + beta * r_m       expected return
 *   CAR              = r_i - market_component        cumulative abnormal return
 *   SCAR             = CAR / (resid_sd * sqrt(n))    standardised
 *   SAR              = AR_T / resid_sd               the signal day alone
 */
export function abnormality(model) {
  const n = model.window_sessions;
  const market_component = model.alpha * n + model.beta * model.r_m_cum;
  const car = model.r_i_cum - market_component;
  const scar = car / (model.resid_sd * Math.sqrt(n));
  const sar = model.ar_signal_day / model.resid_sd;
  return { n, market_component, car, scar, sar, ar: model.ar_signal_day };
}

/** Every item, with its derivation attached. Ranked by the derived score. */
export const SCORED_ITEMS = ITEM_INPUTS.map((input) => {
  const abnormal = abnormality(input.model);
  const metrics = { ...input.metrics, scar: abnormal.scar };
  const derivation = score({
    metrics,
    classificationKey: input.classificationKey,
    personalKeys: input.personalKeys,
    ageSessions: ageInSessions(input.session_date),
  });
  return { ...input, metrics, abnormal, derivation };
})
  .sort((a, b) => b.derivation.final - a.derivation.final)
  .map((item, i) => ({ ...item, rank: i + 1 }));

function toWireItem(item) {
  const company = BY_SYMBOL[item.symbol];
  return {
    signal_event_id: `se_${item.symbol.toLowerCase()}_${item.session_date.replace(/-/g, "")}`,
    symbol: item.symbol,
    company_name: company.company_name,
    family: item.family,
    classification: item.classification,
    rank: item.rank,
    score: Number(item.derivation.final.toFixed(4)),
    what: item.what,
    how_unusual: item.how_unusual,
    cause: item.cause,
    freshness: item.freshness,
    metrics: {
      pct_move: item.metrics.pct_move,
      scar: Number(item.metrics.scar.toFixed(2)),
      turnover_z: item.metrics.turnover_z,
      delivery_z: item.metrics.delivery_z,
      delivery_pct: item.metrics.delivery_pct,
      mpm_triggered: item.metrics.mpm_triggered,
      mpm_threshold_used: item.metrics.mpm_threshold_used,
    },
    provisional: item.provisional,
    revision: item.revision,
    was_restated: item.was_restated,
    completeness: item.completeness,
    linked_announcement_ids: item.linked_announcement_ids,
    links: {
      announcement: item.announcement_url,
      explain: `/api/brief/explain/se_${item.symbol.toLowerCase()}_${item.session_date.replace(/-/g, "")}`,
    },
  };
}

const SURFACED_SYMBOLS = new Set(ITEM_INPUTS.map((i) => i.symbol));
const CORP_ACTION_SYMBOLS = new Set(["IDEA"]);

const QUIET_COUNT =
  DEMO_WATCHLIST.length - SURFACED_SYMBOLS.size - CORP_ACTION_SYMBOLS.size;

const NUMBER_WORDS = [
  "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
  "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen",
];

/**
 * Prose spells small counts; only market figures are numerals. §16's own copy
 * does this — "four things changed", "Nine others" — and it is what keeps the
 * serif register reading as a sentence rather than as a table.
 */
function word(n) {
  return NUMBER_WORDS[n] ?? String(n);
}

const BUDGET = {
  candidates_detected: 41,
  suppressed_corporate_action: 2,
  rolled_up_market_wide: 11,
  grouped_sector_wide: 4,
  below_cap: 20,
  surfaced: 4,
  cap: 5,
};

/**
 * @param {string} [asOf] the cursor instant the brief is requested for
 */
export function mockBrief(asOf) {
  const cursor = asOf ?? "2026-08-12T21:04:00+05:30";
  const cursorDate = istDateIso(cursor);
  const elapsed = SESSION_DATES.filter((d) => d > cursorDate).length;

  // Only signals after the cursor belong in this brief (§13.5 step 2). Dragging
  // the spine back genuinely widens the period rather than replaying a fixture.
  const inWindow = SCORED_ITEMS.filter((item) => item.session_date > cursorDate)
    .sort((a, b) => b.derivation.final - a.derivation.final)
    .slice(0, BUDGET.cap)
    .map((item, i) => toWireItem({ ...item, rank: i + 1 }));

  const corpActions = CORP_ACTION_NOTICES.filter((n) => n.ex_date > cursorDate);
  const quiet = DEMO_WATCHLIST.length - inWindow.length - corpActions.length;

  return {
    generated_at: DEMO_NOW,
    cursor: {
      acknowledged_through: cursor,
      sessions_elapsed: elapsed,
      calendar_days_elapsed: Math.round(
        (Date.parse(DEMO_NOW) - Date.parse(cursor)) / 86_400_000,
      ),
    },
    headline: `Since you last looked on ${formatLongMoment(cursor)}, ${
      inWindow.length === 0 ? "nothing changed" : `${word(inWindow.length).toLowerCase()} things changed`
    }.`,
    market_rollup: {
      present: inWindow.length > 0,
      text: "The market fell over this period. Nifty 50 −4.1%. Eleven of your fourteen names moved with it.",
      index_change_pct: -4.1,
      symbols_attributed: [
        "RELIANCE", "HDFCBANK", "ICICIBANK", "AXISBANK", "SUNPHARMA",
        "TCS", "INFY", "WIPRO", "HCLTECH", "MARUTI", "SBIN",
      ],
    },
    items: inWindow,
    sector_groups:
      inWindow.length > 0
        ? [
            {
              sector: "IT",
              text: "IT fell together — INFY, TCS, WIPRO and HCLTECH all down 3 to 4%.",
              symbols: ["INFY", "TCS", "WIPRO", "HCLTECH"],
            },
          ]
        : [],
    corporate_action_notices: corpActions,
    quiet: {
      count: quiet,
      text: `${word(quiet)} others: nothing notable.`,
    },
    budget: BUDGET,
    data_quality: {
      last_bhavcopy_date: DEMO_LAST_SESSION_DATE,
      delivery_final_through: DEMO_LAST_SESSION_DATE,
      symbols_below_liquidity_floor: [],
      degraded_baselines: [],
      index_0930_source: "CAPTURED_LIVE",
    },
  };
}

const CORP_ACTION_NOTICES = [
  {
    symbol: "IDEA",
    action_type: "BONUS",
    ex_date: "2026-08-14",
    text: "1:1 bonus, ex-date 14 August. Price adjusted from ₹2,480 to ₹1,240. Your holding value is unchanged.",
  },
];

// ─── Fixture self-checks ────────────────────────────────────────────────────
// §18.2: each funnel step is a strict subset of the previous — assert it. A
// fixture that quietly stops adding up is worse than no fixture, because the
// budget line is the product's own argument rendered as a number.
{
  const b = BUDGET;
  const parts =
    b.suppressed_corporate_action +
    b.rolled_up_market_wide +
    b.grouped_sector_wide +
    b.below_cap +
    b.surfaced;
  if (parts !== b.candidates_detected) {
    throw new Error(
      `Mock budget does not reconcile: the parts sum to ${parts} but ` +
        `candidates_detected is ${b.candidates_detected}.`,
    );
  }
  if (b.surfaced > b.cap) {
    throw new Error(`Mock budget surfaces ${b.surfaced} items above the cap of ${b.cap}.`);
  }
  if (QUIET_COUNT < 0) {
    throw new Error("Mock brief accounts for more symbols than the watchlist holds.");
  }
  const ranks = SCORED_ITEMS.map((i) => i.derivation.final);
  for (let i = 1; i < ranks.length; i += 1) {
    if (ranks[i] > ranks[i - 1]) {
      throw new Error("Mock brief items are not in descending score order.");
    }
  }
}
