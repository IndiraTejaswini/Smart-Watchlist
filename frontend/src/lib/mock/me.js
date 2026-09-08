import { DEMO_CURSOR, DEMO_NOW } from "./clock.js";
import { DEMO_WATCHLIST_ID } from "./watchlist.js";

/**
 * GET /api/me
 *
 * §16 names this endpoint without printing its body. It carries the two things
 * the shell needs before any screen can render: who is signed in, and where
 * their reading cursor currently sits. The cursor block is quoted from §16.1's
 * BriefResponse rather than shaped freshly, so there is one cursor schema in
 * the app and not two.
 *
 * Flagged to the human as an open question, along with /api/market/status and
 * the calendar and signal-mark endpoints: this envelope is assembled from
 * fields §16 defines elsewhere, not quoted from it.
 */
export function mockMe() {
  return {
    user: {
      id: "usr_demo",
      display_name: "Demo account",
      initials: "AR",
      is_demo: true,
    },
    default_watchlist_id: DEMO_WATCHLIST_ID,
    as_of: DEMO_NOW,
    cursor: {
      acknowledged_through: DEMO_CURSOR,
    },
  };
}
