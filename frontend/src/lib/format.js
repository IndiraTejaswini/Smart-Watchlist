/**
 * format.js — every number and timestamp the interface renders passes through
 * here.
 *
 * Two decisions worth stating, because both are easy to get silently wrong:
 *
 * 1. Digit grouping is Indian (`en-IN`): 1,02,481.50, not 102,481.50. The
 *    audience is an Indian retail investor and a price written with Western
 *    grouping reads as foreign software. This is number formatting for a single
 *    locale, not internationalisation — there is no locale file, no message
 *    catalogue and no t() wrapper anywhere in this app (R7).
 *
 * 2. Timestamps are forced to Asia/Kolkata. The product is entirely about
 *    Indian market sessions: 09:15, 09:30, 15:30. Rendering those in the
 *    viewer's local zone would silently relabel every session boundary for a
 *    jury member running the demo from another timezone. The API sends ISO 8601
 *    with offset; we pin the display zone rather than trusting the browser.
 */

const IST = "Asia/Kolkata";

/** U+2212 MINUS SIGN. Wider and vertically centred against digits, unlike the
 *  ASCII hyphen, and it holds the tabular advance width in JetBrains Mono. */
const MINUS = "−";

const groupedFormatters = new Map();

function grouped(dp) {
  let f = groupedFormatters.get(dp);
  if (!f) {
    f = new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: dp,
      maximumFractionDigits: dp,
      useGrouping: true,
    });
    groupedFormatters.set(dp, f);
  }
  return f;
}

/** ICU emits an ASCII hyphen for negatives; swap in the true minus sign. */
function withTrueMinus(text) {
  return text.replace(/^-/, MINUS);
}

/**
 * A price or any plain magnitude. Never signed — a price has no direction.
 * @param {number|null|undefined} value
 * @param {number} [dp=2]
 * @returns {string} e.g. "2,481.50", "1,02,481.50", or an em dash when absent
 */
export function formatPrice(value, dp = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  return withTrueMinus(grouped(dp).format(value));
}

/**
 * A signed quantity. The sign is always shown, including the plus, so that a
 * column of changes aligns on sign as well as on decimal point.
 * @param {number|null|undefined} value
 * @param {number} [dp=2]
 */
export function formatSigned(value, dp = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  const body = grouped(dp).format(Math.abs(value));
  if (value > 0) return `+${body}`;
  if (value < 0) return `${MINUS}${body}`;
  return body;
}

/**
 * A signed percentage. §16 returns 1dp on Brief moves and 2dp on index cards,
 * so the caller chooses.
 * @param {number|null|undefined} value
 * @param {number} [dp=2]
 */
export function formatPercent(value, dp = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${formatSigned(value, dp)}%`;
}

/**
 * Rupee turnover in the notation the market actually uses. §21 itself writes
 * 8_000_000 as "₹80 lakh" and 12_000_000 as "₹1.2 crore".
 * @param {number|null|undefined} value rupees
 */
export function formatTurnover(value) {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const sign = value < 0 ? MINUS : "";
  if (abs >= 1e7) return `${sign}₹${grouped(2).format(abs / 1e7)} cr`;
  if (abs >= 1e5) return `${sign}₹${grouped(2).format(abs / 1e5)} L`;
  return `${sign}₹${grouped(0).format(abs)}`;
}

/** A z-score or any statistic that reads best signed to two places. */
export function formatZ(value) {
  return formatSigned(value, 2);
}

/** A ratio held as 0–1 rendered as a percentage, e.g. delivery 0.61 → "61%". */
export function formatRatioPct(value, dp = 0) {
  if (value == null || Number.isNaN(value)) return "—";
  const percentage = Math.min(100, Math.max(0, Math.abs(value) <= 1 ? value * 100 : value));
  return `${grouped(dp).format(percentage)}%`;
}

// ─── Time ───────────────────────────────────────────────────────────────────

const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DAYS_LONG = [
  "Sunday", "Monday", "Tuesday", "Wednesday",
  "Thursday", "Friday", "Saturday",
];

/**
 * Decompose an instant into its IST calendar parts, independent of the host
 * timezone. Intl is the only reliable way to do this without a date library.
 * @param {string|Date} input ISO 8601 string or Date
 */
function istParts(input) {
  const date = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    weekday: "short",
  }).formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type)?.value ?? "";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    hour: get("hour"),
    minute: get("minute"),
    weekdayIndex: date.getUTCDay(), // corrected below
    date,
  };
}

/** Weekday in IST. Derived from the IST calendar date, not the UTC one. */
function istWeekday(p) {
  return DAYS_LONG[new Date(Date.UTC(p.year, p.month - 1, p.day)).getUTCDay()];
}

/** "4 Sep" */
export function formatDayMonth(input) {
  const p = istParts(input);
  if (!p) return "—";
  return `${p.day} ${MONTHS_SHORT[p.month - 1]}`;
}

/** "12 Aug 21:04" — the cursor spine handle label. */
export function formatDayMonthTime(input) {
  const p = istParts(input);
  if (!p) return "—";
  return `${p.day} ${MONTHS_SHORT[p.month - 1]} ${p.hour}:${p.minute}`;
}

/** "15:29" */
export function formatTime(input) {
  const p = istParts(input);
  if (!p) return "—";
  return `${p.hour}:${p.minute}`;
}

/** "Tuesday 12 August at 21:04" — the Brief headline register. */
export function formatLongMoment(input) {
  const p = istParts(input);
  if (!p) return "—";
  return `${istWeekday(p)} ${p.day} ${MONTHS_LONG[p.month - 1]} at ${p.hour}:${p.minute}`;
}

/**
 * The IST calendar date of an instant, as "YYYY-MM-DD".
 *
 * The cursor spine needs this: an instant at 21:04 IST on 12 August is on the
 * 12 August session, and asking the host Date object would answer with whatever
 * date it is wherever the browser happens to be.
 */
export function istDateIso(input) {
  const p = istParts(input);
  if (!p) return null;
  const mm = String(p.month).padStart(2, "0");
  const dd = String(p.day).padStart(2, "0");
  return `${p.year}-${mm}-${dd}`;
}

/** "2026-09-04" as it appears in a provenance line: "4 Sep 2026". */
export function formatIsoDate(isoDate) {
  if (!isoDate) return "—";
  const [y, m, d] = String(isoDate).split("-").map(Number);
  if (!y || !m || !d) return "—";
  return `${d} ${MONTHS_SHORT[m - 1]} ${y}`;
}

export { IST, MINUS };
