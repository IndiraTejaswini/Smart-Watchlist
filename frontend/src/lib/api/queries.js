import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BRIEF_CACHE_TTL_SECONDS, POLL_INTERVAL_SECONDS } from "../constants.js";
import {
  briefSchema,
  explainSchema,
  marketStatusSchema,
  meSchema,
  signalMarksSchema,
  tradingCalendarSchema,
  evalFunnelSchema,
  evalCasesSchema,
  evalContinuationSchema,
  watchlistItemsSchema,
  watchlistQuotesSchema,
} from "../schemas.js";
import { apiFetch } from "./client.js";

/**
 * queries.js — server state lives in TanStack Query. Zustand is reserved for
 * the tick stream, which arrives over a websocket rather than a request and
 * would otherwise force a re-render storm through the query cache.
 */

export const queryKeys = {
  me: ["me"],
  marketStatus: ["market", "status"],
  calendar: (from, to) => ["market", "calendar", from ?? null, to ?? null],
  signalMarks: (watchlistId, symbol) => ["signals", "marks", watchlistId, symbol ?? null],
  brief: (watchlistId, asOf) => ["brief", watchlistId, asOf],
  explain: (signalEventId) => ["brief", "explain", signalEventId],
  watchlistItems: (watchlistId) => ["watchlist", watchlistId, "items"],
  watchlistQuotes: (watchlistId) => ["watchlist", watchlistId, "quotes"],
};

/** Who is signed in, and where their reading cursor sits. */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: ({ signal }) => apiFetch("/me", { schema: meSchema, signal }),
    staleTime: Infinity,
  });
}

/**
 * The session axis for the cursor spine.
 *
 * The trading calendar is reference data: a session that happened does not stop
 * having happened, and the exchange publishes holidays a year ahead. It is
 * fetched once and never refetched, which also means dragging the cursor never
 * waits on it.
 */
export function useTradingCalendar({ from, to } = {}) {
  const search = new URLSearchParams();
  if (from) search.set("from", from);
  if (to) search.set("to", to);
  const suffix = search.toString() ? `?${search}` : "";
  return useQuery({
    queryKey: queryKeys.calendar(from, to),
    queryFn: ({ signal }) =>
      apiFetch(`/market/calendar${suffix}`, { schema: tradingCalendarSchema, signal }),
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

/**
 * Signal marks for the spine. Passing a symbol narrows it to that name, which
 * is what /symbol/:symbol needs (§3).
 */
export function useSignalMarks(watchlistId, { symbol } = {}) {
  const search = new URLSearchParams();
  if (symbol) search.set("symbol", symbol);
  const suffix = search.toString() ? `?${search}` : "";
  return useQuery({
    enabled: Boolean(watchlistId),
    queryKey: queryKeys.signalMarks(watchlistId, symbol),
    queryFn: ({ signal }) =>
      apiFetch(`/watchlist/${watchlistId}/signals${suffix}`, {
        schema: signalMarksSchema,
        signal,
      }),
    staleTime: 60_000,
  });
}

/** The live table's register (12.6): symbol and position, in list order. */
export function useWatchlistItems(watchlistId) {
  return useQuery({
    enabled: Boolean(watchlistId),
    queryKey: queryKeys.watchlistItems(watchlistId),
    queryFn: ({ signal }) =>
      apiFetch(`/watchlist/${watchlistId}`, { schema: watchlistItemsSchema, signal }),
    staleTime: 30_000,
  });
}

/**
 * Each watchlist symbol's own latest daily_bars row — not a live tick (see
 * the endpoint's own docstring). Polled on the same cadence as everything
 * else that calls itself a quote, purely so a re-seed with fresher data
 * during a session would still show up without a page reload.
 */
export function useWatchlistQuotes(watchlistId) {
  return useQuery({
    enabled: Boolean(watchlistId),
    queryKey: queryKeys.watchlistQuotes(watchlistId),
    queryFn: ({ signal }) =>
      apiFetch(`/watchlist/${watchlistId}/quotes`, { schema: watchlistQuotesSchema, signal }),
    staleTime: POLL_INTERVAL_SECONDS * 1000,
    refetchInterval: POLL_INTERVAL_SECONDS * 1000,
  });
}

/**
 * Drag-to-reorder (12.6). Optimistic: the row moves under the pointer
 * immediately, and rolls back only if the write itself fails — waiting on
 * the round trip would make the drag feel like it missed.
 */
export function useReorderWatchlistItem(watchlistId) {
  const queryClient = useQueryClient();
  const queryKey = queryKeys.watchlistItems(watchlistId);
  return useMutation({
    mutationFn: ({ symbol, afterSymbol, beforeSymbol }) =>
      apiFetch(`/watchlist/items/${symbol}/position`, {
        method: "PATCH",
        body: { after_symbol: afterSymbol ?? null, before_symbol: beforeSymbol ?? null },
      }),
    onMutate: async ({ symbol, afterSymbol, beforeSymbol }) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData(queryKey);
      if (previous) {
        const items = previous.items.filter((item) => item.symbol !== symbol);
        const moved = previous.items.find((item) => item.symbol === symbol);
        const anchorIndex = afterSymbol
          ? items.findIndex((item) => item.symbol === afterSymbol) + 1
          : beforeSymbol
            ? items.findIndex((item) => item.symbol === beforeSymbol)
            : items.length;
        items.splice(anchorIndex, 0, moved);
        queryClient.setQueryData(queryKey, { items });
      }
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey }),
  });
}

/**
 * The status strip must never go quietly out of date — it is the one component
 * whose entire job is telling the truth about how old everything else is. It
 * refetches on the §21 polling cadence and keeps polling in the background.
 */
export function useMarketStatus() {
  return useQuery({
    queryKey: queryKeys.marketStatus,
    queryFn: ({ signal }) =>
      apiFetch("/market/status", { schema: marketStatusSchema, signal }),
    refetchInterval: POLL_INTERVAL_SECONDS * 1000,
    refetchIntervalInBackground: false,
    staleTime: POLL_INTERVAL_SECONDS * 1000,
  });
}

/**
 * The brief for a cursor position.
 *
 * The cursor is part of the query key, so dragging the spine produces a genuine
 * refetch for the new period rather than a filtered view of one payload. That
 * is the difference between a cursor and a date picker.
 */
export function useBrief(watchlistId, asOf) {
  const search = new URLSearchParams();
  if (watchlistId) search.set("watchlist_id", watchlistId);
  if (asOf) search.set("as_of", asOf);
  return useQuery({
    enabled: Boolean(watchlistId && asOf),
    queryKey: queryKeys.brief(watchlistId, asOf),
    queryFn: ({ signal }) =>
      apiFetch(`/brief?${search}`, { schema: briefSchema, signal }),
    staleTime: BRIEF_CACHE_TTL_SECONDS * 1000,
    // Holding the previous brief while the next one loads keeps the page from
    // collapsing to a skeleton every time the cursor moves one session.
    placeholderData: (previous) => previous,
  });
}

/** The full derivation behind one item. Fetched only when the panel opens. */
export function useExplain(signalEventId) {
  return useQuery({
    enabled: Boolean(signalEventId),
    queryKey: queryKeys.explain(signalEventId),
    queryFn: ({ signal }) =>
      apiFetch(`/brief/explain/${signalEventId}`, { schema: explainSchema, signal }),
    staleTime: Infinity,
  });
}

export function useEval() {
  const funnel = useQuery({ queryKey: ["eval", "funnel"], queryFn: () => apiFetch("/eval/funnel", { schema: evalFunnelSchema }), staleTime: Infinity });
  const cases = useQuery({ queryKey: ["eval", "cases"], queryFn: () => apiFetch("/eval/cases", { schema: evalCasesSchema }), staleTime: Infinity });
  const continuation = useQuery({ queryKey: ["eval", "continuation"], queryFn: () => apiFetch("/eval/continuation", { schema: evalContinuationSchema }), staleTime: Infinity });
  return { funnel, cases, continuation };
}
