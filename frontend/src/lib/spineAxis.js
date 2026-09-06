import { istDateIso } from "./format.js";

/**
 * spineAxis.js — the geometry behind the cursor spine, as pure functions.
 *
 * The spine's one structural idea: **position is calendar time, value is
 * session count.**
 *
 * A tick sits at its real calendar date, so the two days the market is shut
 * every weekend, and the day it is shut for Muharram, take up real width. That
 * is what makes the market's rhythm visible instead of flattening 64 sessions
 * into 64 equal steps. But the *cursor* moves in sessions — one arrow key press
 * is one session, and "17 sessions since you last looked" is a session count —
 * because a session is the unit the product actually reasons in.
 *
 * Two consequences worth stating, because both are deliberate:
 *
 * 1. Dragging cannot use the native range input's own pointer handling. That
 *    maps the pointer linearly onto value, which on a non-linear axis would
 *    land the handle somewhere other than where the user let go. The input is
 *    kept for keyboard and assistive technology, where its behaviour is exactly
 *    right, and pointer drags are mapped through `nearestIndex` instead.
 *
 * 2. Positions are calendar *dates*, not session instants. A MUHURAT session's
 *    hours are notified separately by circular and the backend stores them as
 *    NULL rather than inventing them (R1). Placing ticks by date means the
 *    spine never has to assert a session window it does not have.
 */

const IST_OFFSET = "+05:30";

/** Midnight IST on a "YYYY-MM-DD", in epoch milliseconds. */
export function dateMs(isoDate) {
  return Date.parse(`${isoDate}T00:00:00${IST_OFFSET}`);
}

/**
 * @typedef {object} SpineAxis
 * @property {number} t0 window start, epoch ms
 * @property {number} t1 window end, epoch ms
 * @property {number} span
 * @property {{date:string, session_type:string, index:number, fraction:number}[]} points
 */

/**
 * @param {{date:string, session_type:string}[]} sessions ascending
 * @param {{from:string, to:string}} window
 * @returns {SpineAxis|null} null when there is nothing to draw
 */
export function buildAxis(sessions, window) {
  if (!sessions?.length || !window) return null;
  const t0 = dateMs(window.from);
  const t1 = dateMs(window.to);
  const span = t1 - t0;
  if (!Number.isFinite(span) || span <= 0) return null;

  const points = sessions.map((session, index) => ({
    ...session,
    index,
    fraction: clamp01((dateMs(session.date) - t0) / span),
  }));
  return { t0, t1, span, points };
}

/** Where a calendar date sits on the axis, 0–1. */
export function fractionOfDate(isoDate, axis) {
  if (!axis) return 0;
  return clamp01((dateMs(isoDate) - axis.t0) / axis.span);
}

/**
 * The session nearest a horizontal position. Linear scan: 64 points over a 90
 * day retention window, called during a drag — a binary search here would be
 * ceremony over an array that fits in a cache line.
 */
export function nearestIndex(fraction, axis) {
  if (!axis?.points.length) return 0;
  let best = 0;
  let bestDistance = Infinity;
  for (const point of axis.points) {
    const distance = Math.abs(point.fraction - fraction);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = point.index;
    }
  }
  return best;
}

/**
 * The session a server-supplied cursor instant belongs to: the last session on
 * or before the cursor's IST date.
 *
 * An instant of 21:04 on 12 August is after that session's close, so 12 August
 * is the last session the reader has seen — which is why the comparison is on
 * the IST calendar date and not on the raw instant.
 */
export function indexForInstant(instantIso, axis) {
  if (!axis?.points.length) return 0;
  const day = istDateIso(instantIso);
  if (!day) return axis.points.length - 1;
  let found = -1;
  for (const point of axis.points) {
    if (point.date <= day) found = point.index;
    else break;
  }
  // A cursor older than the retention window pins to its start; §21 keeps
  // ninety days of signals and there is nothing to show before that.
  return found === -1 ? 0 : found;
}

/**
 * Sessions strictly after the selected one — the number in "17 sessions since
 * you last looked". At the newest session this is zero, which is a real state
 * and not an error: it means nothing has closed since you last read.
 */
export function sessionsElapsed(index, axis) {
  if (!axis?.points.length) return 0;
  return Math.max(0, axis.points.length - 1 - index);
}

function clamp01(value) {
  if (Number.isNaN(value)) return 0;
  return Math.min(1, Math.max(0, value));
}
