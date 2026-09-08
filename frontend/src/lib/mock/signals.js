import { TRADING_SESSIONS } from "./tradingCalendar.js";
import { BY_SYMBOL } from "./watchlist.js";

/**
 * signals.js — the signal marks plotted on the cursor spine.
 *
 * §3: "a small dot for a scored signal, a filled triangle for one that was
 * surfaced." A mark is therefore the minimum a spine needs — when, which name,
 * and whether the ranker let it through the budget — and nothing else. The full
 * signal is fetched only when a Brief item is rendered.
 *
 * These are fixtures, and they are the one part of the mock that is authored
 * rather than derived. Two constraints hold them honest:
 *
 *   Every date must be a real trading session. Enforced below, not assumed —
 *   a mark on a Sunday would quietly undermine the exact claim the spine is
 *   making about the calendar being real.
 *
 *   The four surfaced marks after the demo cursor (2026-08-12) are the four
 *   items §16's example Brief returns, so the spine and the Brief tell the same
 *   story. Drag the cursor back and earlier surfaced marks come into range;
 *   that is the whole interaction the product is built around.
 */

/** @typedef {{signal_event_id: string, session_date: string, symbol: string, surfaced: boolean}} SignalMark */

/** [date, symbol, surfaced] */
const AUTHORED = [
  // ── Before the demo cursor ────────────────────────────────────────────────
  ["2026-06-11", "WIPRO", false],
  ["2026-06-18", "HDFCBANK", false],
  ["2026-06-19", "TCS", false],
  ["2026-06-30", "RELIANCE", true],
  ["2026-07-07", "SUNPHARMA", false],
  ["2026-07-08", "AXISBANK", false],
  ["2026-07-15", "ICICIBANK", false],
  ["2026-07-16", "INFY", false],
  ["2026-07-23", "MARUTI", true],
  ["2026-07-24", "IDEA", false],
  ["2026-07-30", "TCS", false],
  ["2026-08-04", "HCLTECH", false],
  ["2026-08-05", "SBIN", false],
  ["2026-08-11", "BHARTIARTL", false],
  ["2026-08-12", "RELIANCE", false],

  // ── After the demo cursor: the period the Brief covers ────────────────────
  // The two candidates suppressed as corporate-action artefacts, on and either
  // side of IDEA's 14 August ex-date. They are scored — the engine saw them —
  // and they never reach the brief as moves; one notice is emitted instead.
  // These are the `suppressed_corporate_action: 2` in the budget block.
  ["2026-08-13", "IDEA", false],
  ["2026-08-14", "IDEA", false],
  ["2026-08-14", "HDFCBANK", false],
  ["2026-08-18", "WIPRO", false],
  ["2026-08-20", "MARUTI", true],
  ["2026-08-21", "ICICIBANK", false],
  ["2026-08-25", "SUNPHARMA", false],
  ["2026-08-26", "TCS", false],
  ["2026-08-27", "INFY", false],
  ["2026-08-28", "SBIN", true],
  ["2026-09-01", "AXISBANK", false],
  ["2026-09-02", "HCLTECH", false],
  ["2026-09-03", "RELIANCE", false],
  ["2026-09-04", "TATAMOTORS", true],
  ["2026-09-04", "BHARTIARTL", true],
];

const SESSION_DATES = new Set(TRADING_SESSIONS.map((s) => s.date));

/** @type {SignalMark[]} */
export const SIGNAL_MARKS = AUTHORED.map(([session_date, symbol, surfaced]) => {
  if (!SESSION_DATES.has(session_date)) {
    throw new Error(
      `Mock signal for ${symbol} is dated ${session_date}, which is not a ` +
        "trading session in the generated calendar. Fixtures are required to sit on " +
        "real sessions — re-run scripts/generate-mock-calendar.mjs or fix the date.",
    );
  }
  if (!BY_SYMBOL[symbol]) {
    throw new Error(`Mock signal references ${symbol}, which is not on the demo list.`);
  }
  return {
    signal_event_id: `se_${symbol.toLowerCase()}_${session_date.replace(/-/g, "")}`,
    session_date,
    symbol,
    surfaced,
  };
});

/**
 * @param {{from?: string, to?: string, symbol?: string}} filter
 * @returns {SignalMark[]}
 */
export function selectMarks({ from, to, symbol } = {}) {
  return SIGNAL_MARKS.filter(
    (mark) =>
      (!from || mark.session_date >= from) &&
      (!to || mark.session_date <= to) &&
      (!symbol || mark.symbol === symbol),
  );
}
