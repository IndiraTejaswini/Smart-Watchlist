/**
 * clock.js — the demo clock.
 *
 * Every mock payload is anchored to one fixed instant, taken from the
 * `generated_at` in the docs/BUILD_SPEC.md §16 example so that the mock and the
 * contract example describe the same moment.
 *
 * That instant is Saturday 5 September 2026 at 10:14 IST — the market shut, the
 * Friday bhavcopy final. This is deliberate. FRONTEND_SPEC §3 asks that the app
 * demo correctly at 2am on a Sunday with the market closed, and a demo anchored
 * to a fixed weekend instant proves that path every time it is opened rather
 * than only when someone runs it during trading hours.
 *
 * A fixed clock also makes the mock reproducible: the same cursor position
 * yields the same Brief on every run, which is what makes a screenshot or a
 * rehearsed demo trustworthy.
 */

/** The demo "now", ISO 8601 with IST offset. */
export const DEMO_NOW = "2026-09-05T10:14:22+05:30";

/** The demo user's acknowledged cursor — §16 `cursor.acknowledged_through`. */
export const DEMO_CURSOR = "2026-08-12T21:04:00+05:30";

/** Latest settled trading session. Friday 4 September 2026. */
export const DEMO_LAST_SESSION_DATE = "2026-09-04";

export const DEMO_NOW_MS = Date.parse(DEMO_NOW);
