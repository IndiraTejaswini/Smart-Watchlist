import { DEMO_WATCHLIST_ID } from "./watchlist.js";
import { LIVE_WATCHLIST } from "./liveWatchlist.js";

/**
 * watchlistState.js — the mock transport's mutable order for one watchlist.
 *
 * Every other mock fixture is a pure function of static data; this one is not,
 * because drag-to-reorder (12.6) is a write, and the mock transport has to
 * actually remember it for the rest of the session the same way the real
 * PATCH /api/watchlist/items/:symbol/position endpoint does — a reorder that
 * snaps back on the next render would not exercise anything.
 */

const POSITION_STEP = 100;

const order = new Map(
  LIVE_WATCHLIST.map(({ symbol }, index) => [symbol, (index + 1) * POSITION_STEP]),
);

export function listWatchlistItems(watchlistId) {
  if (watchlistId !== DEMO_WATCHLIST_ID) return { items: [] };
  const items = [...order.entries()]
    .sort((a, b) => a[1] - b[1])
    .map(([symbol, position]) => ({ symbol, position: String(position) }));
  return { items };
}

export function reorderWatchlistItem(symbol, { after_symbol: after, before_symbol: before }) {
  if (!order.has(symbol)) {
    const error = new Error("Symbol not on this watchlist");
    error.status = 404;
    error.title = "Not found";
    error.detail = `${symbol} is not on this watchlist`;
    throw error;
  }
  const afterPos = after ? order.get(after) : undefined;
  const beforePos = before ? order.get(before) : undefined;
  let next;
  if (afterPos === undefined && beforePos === undefined) next = POSITION_STEP;
  else if (afterPos === undefined) next = beforePos - POSITION_STEP;
  else if (beforePos === undefined) next = afterPos + POSITION_STEP;
  else next = (afterPos + beforePos) / 2;
  order.set(symbol, next);
  return { symbol, position: String(next) };
}
