import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAxis,
  dateMs,
  fractionOfDate,
  indexForInstant,
  nearestIndex,
  sessionsElapsed,
} from "./spineAxis.js";
import { CALENDAR_WINDOW, TRADING_SESSIONS } from "./mock/tradingCalendar.js";
import { DEMO_CURSOR } from "./mock/clock.js";

/**
 * The cursor spine is the signature element, and everything memorable about it
 * is geometry: where a session sits, which session a drag lands on, and how
 * many sessions have closed since the cursor. Those are pure functions, so they
 * are tested directly rather than through the DOM.
 *
 * Run: npm run test:unit   (node:test, no test framework dependency)
 */

const axis = buildAxis(TRADING_SESSIONS, CALENDAR_WINDOW);
const DAY_MS = 86_400_000;

test("the axis covers every session in the generated calendar", () => {
  assert.equal(axis.points.length, TRADING_SESSIONS.length);
  assert.equal(axis.points[0].date, "2026-06-08");
  assert.equal(axis.points.at(-1).date, "2026-09-04");
});

test("fractions are monotonic and stay inside the window", () => {
  for (let i = 1; i < axis.points.length; i += 1) {
    assert.ok(
      axis.points[i].fraction > axis.points[i - 1].fraction,
      `session ${axis.points[i].date} is not after ${axis.points[i - 1].date}`,
    );
  }
  assert.ok(axis.points[0].fraction >= 0);
  assert.ok(axis.points.at(-1).fraction <= 1);
});

test("a weekend leaves three times the gap of a mid-week night", () => {
  // Thursday 11 June -> Friday 12 June is one night.
  // Friday 12 June -> Monday 15 June is three.
  const gap = (a, b) => dateMs(b) - dateMs(a);
  assert.equal(gap("2026-06-11", "2026-06-12"), DAY_MS);
  assert.equal(gap("2026-06-12", "2026-06-15"), 3 * DAY_MS);
});

test("the Muharram holiday widens its weekend gap beyond a normal one", () => {
  // Thursday 25 June is a session; Friday 26 June is Muharram; the next
  // session is Monday 29 June. Four nights rather than the usual three.
  const dates = TRADING_SESSIONS.map((s) => s.date);
  assert.ok(dates.includes("2026-06-25"));
  assert.ok(!dates.includes("2026-06-26"), "26 June should not be a session");
  assert.ok(dates.includes("2026-06-29"));
  const holidayGap = dateMs("2026-06-29") - dateMs("2026-06-25");
  const weekendGap = dateMs("2026-06-15") - dateMs("2026-06-12");
  assert.equal(holidayGap, 4 * DAY_MS);
  assert.ok(holidayGap > weekendGap, "the holiday gap must read wider than a weekend");
});

test("the demo cursor resolves to the 12 August session", () => {
  const index = indexForInstant(DEMO_CURSOR, axis);
  assert.equal(axis.points[index].date, "2026-08-12");
});

test("sessions elapsed reproduces the 17 in the ARCHITECTURE §16 example", () => {
  // The contract's example Brief states sessions_elapsed: 17 for this cursor.
  // The calendar here was generated from the repository's cached NSE bhavcopy
  // and holiday data, so this asserts that the real record agrees with the doc.
  const index = indexForInstant(DEMO_CURSOR, axis);
  assert.equal(sessionsElapsed(index, axis), 17);
});

test("an instant after the close belongs to that day's session, not the next", () => {
  // 21:04 is after the 15:30 close: the reader has seen 12 August in full.
  const late = indexForInstant("2026-08-12T21:04:00+05:30", axis);
  const early = indexForInstant("2026-08-12T09:20:00+05:30", axis);
  assert.equal(axis.points[late].date, "2026-08-12");
  assert.equal(axis.points[early].date, "2026-08-12");
});

test("a cursor on a non-session day falls back to the previous session", () => {
  // Sunday 16 August 2026. The last session before it is Friday 14 August.
  const index = indexForInstant("2026-08-16T10:00:00+05:30", axis);
  assert.equal(axis.points[index].date, "2026-08-14");
});

test("a cursor is resolved in IST, not in the host timezone", () => {
  // 20:00 UTC on 12 August is 01:30 IST on 13 August — a different session.
  // Getting this wrong would silently shift every cursor for a reviewer
  // running the demo outside India.
  const index = indexForInstant("2026-08-12T20:00:00Z", axis);
  assert.equal(axis.points[index].date, "2026-08-13");
});

test("a cursor older than retention pins to the start of the window", () => {
  const index = indexForInstant("2020-01-01T00:00:00+05:30", axis);
  assert.equal(index, 0);
});

test("at the newest session nothing has elapsed", () => {
  assert.equal(sessionsElapsed(axis.points.length - 1, axis), 0);
});

test("a drag onto a session's own position selects that session", () => {
  for (const point of axis.points) {
    const landed = nearestIndex(fractionOfDate(point.date, axis), axis);
    assert.equal(landed, point.index, `round trip failed at ${point.date}`);
  }
});

test("a drag into a weekend snaps to the nearer side, never off the axis", () => {
  // Saturday 13 June sits between Friday 12 and Monday 15; it is closer to
  // Friday, and must resolve to a real session either way.
  const saturday = nearestIndex(fractionOfDate("2026-06-13", axis), axis);
  assert.equal(axis.points[saturday].date, "2026-06-12");

  const sunday = nearestIndex(fractionOfDate("2026-06-14", axis), axis);
  assert.equal(axis.points[sunday].date, "2026-06-15");
});

test("dragging past either end clamps to a real session", () => {
  assert.equal(nearestIndex(-5, axis), 0);
  assert.equal(nearestIndex(5, axis), axis.points.length - 1);
});

test("an empty calendar yields no axis rather than a divide by zero", () => {
  assert.equal(buildAxis([], CALENDAR_WINDOW), null);
  assert.equal(buildAxis(TRADING_SESSIONS, null), null);
  assert.equal(
    buildAxis(TRADING_SESSIONS, { from: "2026-09-05", to: "2026-09-05" }),
    null,
  );
});
