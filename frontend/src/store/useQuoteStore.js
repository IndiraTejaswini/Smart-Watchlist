import { create } from "zustand";

export const useQuoteStore = create((set) => ({
  quotes: {},
  subscribedSymbols: [],
  feedState: "LIVE",
  applyTick: (symbol, tick) => set((state) => ({
    quotes: { ...state.quotes, [symbol]: { ...state.quotes[symbol], ...tick } },
  })),
  /**
   * Authoritative replace for a batch of symbols — used for the real
   * end-of-day quotes fetched from GET /api/watchlist/:id/quotes. Unlike a
   * tick stream, a re-fetch of this data should always win over whatever
   * was there before, not merge into it.
   */
  setQuotes: (quotesBySymbol) => set((state) => ({
    quotes: { ...state.quotes, ...quotesBySymbol },
  })),
  setSubscriptions: (symbols) => set({ subscribedSymbols: symbols }),
  setFeedState: (feedState) => set({ feedState }),
}));
