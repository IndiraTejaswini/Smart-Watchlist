import { create } from "zustand";

const INITIAL_QUOTES = {
  RELIANCE: { ltp: 2942.35, chp: 1.24, change: 36.1, turnover: 1.8, delivery: 42.4, state: "LIVE", freshness: "final" },
  TCS: { ltp: 3518.2, chp: -0.42, change: -14.85, turnover: 1.2, delivery: 38.1, state: "LIVE", freshness: "final" },
  INFY: { ltp: 1492.75, chp: 0.86, change: 12.7, turnover: 1.5, delivery: 41.2, state: "LIVE", freshness: "final" },
  WIPRO: { ltp: 517.4, chp: -0.18, change: -0.94, turnover: 0.9, delivery: 35.6, state: "LIVE", freshness: "provis" },
  HCLTECH: { ltp: 1668.5, chp: 0.31, change: 5.15, turnover: 1.1, delivery: 44.8, state: "LIVE", freshness: "final" },
  HDFCBANK: { ltp: 1742.1, chp: 0.64, change: 11.05, turnover: 1.4, delivery: 39.7, state: "LIVE", freshness: "final" },
  ICICIBANK: { ltp: 1288.3, chp: -0.27, change: -3.5, turnover: 1.0, delivery: 36.2, state: "LIVE", freshness: "final" },
  SBIN: { ltp: 821.65, chp: 0.48, change: 3.92, turnover: 1.7, delivery: 33.8, state: "LIVE", freshness: "final" },
  AXISBANK: { ltp: 1195.4, chp: -0.11, change: -1.32, turnover: 0.8, delivery: 31.5, state: "LIVE", freshness: "provis" },
  TATAMOTORS: { ltp: 1048.6, chp: 1.12, change: 11.62, turnover: 2.1, delivery: 46.3, state: "LIVE", freshness: "final" },
  MARUTI: { ltp: 12540.2, chp: -0.36, change: -45.3, turnover: 0.7, delivery: 37.9, state: "LIVE", freshness: "final" },
  BHARTIARTL: { ltp: 1912.8, chp: 0.22, change: 4.2, turnover: 1.3, delivery: 40.1, state: "LIVE", freshness: "final" },
  IDEA: { ltp: 8.42, chp: -1.64, change: -0.14, turnover: 2.8, delivery: 52.6, state: "LIVE", freshness: "stale" },
  SUNPHARMA: { ltp: 1724.9, chp: 0.53, change: 9.1, turnover: 1.0, delivery: 43.7, state: "LIVE", freshness: "final" },
};

export const useQuoteStore = create((set) => ({
  quotes: INITIAL_QUOTES,
  subscribedSymbols: [],
  feedState: "LIVE",
  applyTick: (symbol, tick) => set((state) => ({
    quotes: { ...state.quotes, [symbol]: { ...state.quotes[symbol], ...tick } },
  })),
  // Merges in quotes for symbols the store does not have yet, without
  // touching ones already ticking (a re-seed on remount must not reset a
  // live price back to its opening synthetic value).
  seedQuotes: (quotesBySymbol) => set((state) => {
    let changed = false;
    const next = { ...state.quotes };
    for (const [symbol, quote] of Object.entries(quotesBySymbol)) {
      if (!next[symbol]) {
        next[symbol] = quote;
        changed = true;
      }
    }
    return changed ? { quotes: next } : {};
  }),
  setSubscriptions: (symbols) => set({ subscribedSymbols: symbols }),
  setFeedState: (feedState) => set({ feedState }),
}));

