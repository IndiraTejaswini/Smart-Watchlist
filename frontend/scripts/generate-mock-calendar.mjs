#!/usr/bin/env node
/**
 * generate-mock-calendar.mjs — derive the mock trading calendar from real data.
 *
 * The cursor spine's whole claim is that the gaps in it are real: weekends and
 * exchange holidays leave genuine space, which is what makes the market's
 * rhythm visible. That claim is only worth making if the dates are not invented
 * (R1, R3), so this script reads the same two sources `backend/app/ingest/
 * calendar.py` reads and applies the same precedence rule:
 *
 *   data/cache/bhavcopy/<date>/*.zip        NSE published a bhavcopy for that
 *                                           date, which is the exchange saying
 *                                           a session happened. Direct evidence.
 *   data/cache/reference/<snap>/nse_holidays_<year>.json, segment CM
 *                                           The published holiday list, used to
 *                                           name why a weekday had no session.
 *
 * Observation wins over the list, exactly as classify_day() does: a published
 * bhavcopy is what actually occurred.
 *
 * Run: node scripts/generate-mock-calendar.mjs
 * Writes: src/lib/mock/tradingCalendar.js
 */

import { readdirSync, readFileSync, writeFileSync, existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = fileURLToPath(new URL("..", import.meta.url));
const REPO = join(FRONTEND, "..");
const CACHE = join(REPO, "data", "cache");

// Mirrors src/lib/mock/clock.js and §21 SIGNAL_RETENTION_DAYS.
const DEMO_NOW_DATE = "2026-09-05";
const RETENTION_DAYS = 90;

const MONTHS = {
  Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6,
  Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12,
};

function isoOf(d) {
  return d.toISOString().slice(0, 10);
}
function addDays(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return isoOf(d);
}
function weekday(iso) {
  return new Date(`${iso}T00:00:00Z`).getUTCDay(); // 0 Sun … 6 Sat
}

// ─── Source 1: observed sessions ────────────────────────────────────────────

const bhavcopyRoot = join(CACHE, "bhavcopy");
if (!existsSync(bhavcopyRoot)) {
  console.error(`No bhavcopy cache at ${bhavcopyRoot}. Run \`make backfill\` first.`);
  process.exit(1);
}

const observed = new Set();
for (const name of readdirSync(bhavcopyRoot)) {
  const dir = join(bhavcopyRoot, name);
  if (!statSync(dir).isDirectory()) continue;
  if (!readdirSync(dir).some((f) => f.endsWith(".zip"))) continue;
  if (/^\d{4}-\d{2}-\d{2}$/.test(name)) observed.add(name);
}

// ─── Source 2: the published holiday master ─────────────────────────────────

const referenceRoot = join(CACHE, "reference");
const snapshots = existsSync(referenceRoot)
  ? readdirSync(referenceRoot).filter((n) => /^\d{4}-\d{2}-\d{2}$/.test(n)).sort()
  : [];
const snapshot = snapshots.at(-1);
if (!snapshot) {
  console.error(`No reference snapshot under ${referenceRoot}.`);
  process.exit(1);
}

const holidays = new Map();
for (const file of readdirSync(join(referenceRoot, snapshot))) {
  const match = /^nse_holidays_(\d{4})\.json$/.exec(file);
  if (!match) continue;
  const payload = JSON.parse(readFileSync(join(referenceRoot, snapshot, file), "utf8"));
  for (const row of payload.CM ?? []) {
    const [dd, mon, yyyy] = String(row.tradingDate).split("-");
    const month = MONTHS[mon];
    if (!month) continue;
    const iso = `${yyyy}-${String(month).padStart(2, "0")}-${dd.padStart(2, "0")}`;
    holidays.set(iso, String(row.description ?? "").replace(/\*$/, "").trim());
  }
}

// ─── Resolve the retention window ───────────────────────────────────────────

const windowStart = addDays(DEMO_NOW_DATE, -RETENTION_DAYS);
const sessions = [];
const closures = [];

for (let iso = windowStart; iso <= DEMO_NOW_DATE; iso = addDays(iso, 1)) {
  if (observed.has(iso)) {
    sessions.push({ date: iso, session_type: "REGULAR" });
    continue;
  }
  const listed = holidays.get(iso);
  const isWeekend = weekday(iso) === 0 || weekday(iso) === 6;
  closures.push({
    date: iso,
    reason: listed ?? (isWeekend ? "Weekend" : "No bhavcopy published and no listed holiday"),
    weekend: isWeekend,
  });
}

// Weekday closures are the interesting ones: they are the gaps a reader can see
// in the spine that a weekend does not explain.
const holidayClosures = closures.filter((c) => !c.weekend);

const out = `/**
 * tradingCalendar.js — GENERATED. Do not edit by hand.
 *
 * Produced by scripts/generate-mock-calendar.mjs from the repository's own
 * cached NSE data. Re-run that script rather than editing this file.
 *
 * Window   ${windowStart} to ${DEMO_NOW_DATE} (SIGNAL_RETENTION_DAYS = ${RETENTION_DAYS})
 * Sessions ${sessions.length}
 * Sources  data/cache/bhavcopy — a published bhavcopy is the exchange saying a
 *          session happened; data/cache/reference/${snapshot}/nse_holidays_*.json,
 *          segment CM, for the name of each weekday closure.
 *
 * The weekday closures in this window, which are the gaps the spine makes
 * visible over and above the weekends:
${holidayClosures.map((c) => ` *   ${c.date}  ${c.reason}`).join("\n") || " *   (none)"}
 */

/** @typedef {{date: string, session_type: string}} TradingSession */

/** Every trading session in the retention window, ascending. @type {TradingSession[]} */
export const TRADING_SESSIONS = ${JSON.stringify(sessions, null, 2)};

/** The window the sessions above cover. */
export const CALENDAR_WINDOW = {
  from: ${JSON.stringify(windowStart)},
  to: ${JSON.stringify(DEMO_NOW_DATE)},
};

/** Weekday closures, so the interface can name a gap when asked. */
export const WEEKDAY_CLOSURES = ${JSON.stringify(
  holidayClosures.map(({ date, reason }) => ({ date, reason })),
  null,
  2,
)};
`;

const target = join(FRONTEND, "src", "lib", "mock", "tradingCalendar.js");
writeFileSync(target, out, "utf8");

console.log(
  `generate-mock-calendar: ${sessions.length} sessions, ` +
    `${holidayClosures.length} weekday closure(s), ${windowStart} to ${DEMO_NOW_DATE}`,
);
for (const c of holidayClosures) console.log(`  ${c.date}  ${c.reason}`);
