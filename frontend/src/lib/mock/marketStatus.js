import { DEMO_LAST_SESSION_DATE, DEMO_NOW } from "./clock.js";

/**
 * GET /api/market/status
 *
 * §16 names this endpoint but does not print its body. Every field below is
 * lifted from a shape §16 or §14 already defines rather than composed freely:
 *
 *   session      — the `market_status` websocket frame, §14.3
 *   banner       — the same frame; null when there is nothing to say
 *   feed_state   — the freshness state machine, §14.2
 *   data_quality — the block returned on every BriefResponse, §16.1
 *
 * Flagged to the human as an open question: this envelope is assembled, not
 * quoted, and the backend should agree to it before it is relied on.
 *
 * The demo instant is a Saturday, so the honest answer here is a closed market
 * on final Friday data — which is also the state that exercises R5 hardest.
 */
export function mockMarketStatus() {
  return {
    as_of: DEMO_NOW,
    session: "CLOSED",
    feed_state: "CLOSED",
    banner: null,
    data_quality: {
      last_bhavcopy_date: DEMO_LAST_SESSION_DATE,
      delivery_final_through: DEMO_LAST_SESSION_DATE,
      index_0930_source: "CAPTURED_LIVE",
      symbols_below_liquidity_floor: [],
      degraded_baselines: [],
    },
  };
}
