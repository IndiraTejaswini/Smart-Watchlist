/**
 * tradingCalendar.js — GENERATED. Do not edit by hand.
 *
 * Produced by scripts/generate-mock-calendar.mjs from the repository's own
 * cached NSE data. Re-run that script rather than editing this file.
 *
 * Window   2026-06-07 to 2026-09-05 (SIGNAL_RETENTION_DAYS = 90)
 * Sessions 64
 * Sources  data/cache/bhavcopy — a published bhavcopy is the exchange saying a
 *          session happened; data/cache/reference/2026-09-06/nse_holidays_*.json,
 *          segment CM, for the name of each weekday closure.
 *
 * The weekday closures in this window, which are the gaps the spine makes
 * visible over and above the weekends:
 *   2026-06-26  Muharram
 */

/** @typedef {{date: string, session_type: string}} TradingSession */

/** Every trading session in the retention window, ascending. @type {TradingSession[]} */
export const TRADING_SESSIONS = [
  {
    "date": "2026-06-08",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-09",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-10",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-11",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-12",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-15",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-16",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-17",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-18",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-19",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-22",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-23",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-24",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-25",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-29",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-06-30",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-01",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-02",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-03",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-06",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-07",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-08",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-09",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-10",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-13",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-14",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-15",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-16",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-17",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-20",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-21",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-22",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-23",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-24",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-27",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-28",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-29",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-30",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-07-31",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-03",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-04",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-05",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-06",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-07",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-10",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-11",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-12",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-13",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-14",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-17",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-18",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-19",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-20",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-21",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-24",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-25",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-26",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-27",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-28",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-08-31",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-09-01",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-09-02",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-09-03",
    "session_type": "REGULAR"
  },
  {
    "date": "2026-09-04",
    "session_type": "REGULAR"
  }
];

/** The window the sessions above cover. */
export const CALENDAR_WINDOW = {
  from: "2026-06-07",
  to: "2026-09-05",
};

/** Weekday closures, so the interface can name a gap when asked. */
export const WEEKDAY_CLOSURES = [
  {
    "date": "2026-06-26",
    "reason": "Muharram"
  }
];
