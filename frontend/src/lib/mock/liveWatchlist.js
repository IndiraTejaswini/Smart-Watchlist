import { DEMO_WATCHLIST } from "./watchlist.js";

/**
 * liveWatchlist.js — a 250-name synthetic register for the live watchlist
 * table (12.6), separate from DEMO_WATCHLIST.
 *
 * DEMO_WATCHLIST (watchlist.js) is fourteen names hand-picked to exercise the
 * Brief's sector-grouping and corporate-action branches — FRONTEND_SPEC §5.1
 * and the mock signal fixtures cite that exact count and those exact symbols,
 * so it stays untouched. Task 12.6's own acceptance ("250 rows scroll
 * smoothly") is a different, purely mechanical requirement — virtualisation,
 * viewport-scoped subscriptions, row memoisation — that needs a much larger
 * register to actually exercise. This file supplies that register: the real
 * fourteen first, padded out to 250 with deterministically generated names.
 *
 * No live broker connection is available for this build, so every quote here
 * is synthetic by design — seeded, not fetched — and the tick stream
 * (mock/ticks.js) walks it forward the same way it already does for the
 * fourteen.
 */

const SECTORS = [
  "IT",
  "Banking",
  "Auto",
  "Pharma",
  "Energy",
  "FMCG",
  "Metals",
  "Telecom",
  "Realty",
  "Capital Goods",
  "Chemicals",
  "Financial Services",
];

// Deterministic PRNG (mulberry32) — same sequence on every load, matching the
// rest of the mock layer's "deterministic, not random" convention.
function mulberry32(seed) {
  let a = seed;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rand = mulberry32(20260907);

function syntheticSymbol(index) {
  return `SYN${String(index).padStart(4, "0")}`;
}

const GENERATED = Array.from({ length: 236 }, (_, index) => {
  const n = index + 1;
  const sector = SECTORS[index % SECTORS.length];
  return {
    symbol: syntheticSymbol(n),
    company_name: `${sector} Synthetic Holdings ${n}`,
    sector,
  };
});

/** @type {{symbol: string, company_name: string, sector: string}[]} */
export const LIVE_WATCHLIST = [...DEMO_WATCHLIST, ...GENERATED];

/** @type {Record<string, {symbol:string, company_name:string, sector:string}>} */
export const LIVE_BY_SYMBOL = Object.fromEntries(
  LIVE_WATCHLIST.map((item) => [item.symbol, item]),
);

/** @type {Record<string, {ltp:number, chp:number, change:number, turnover:number, delivery:number, state:string, freshness:string}>} */
export const GENERATED_QUOTES = Object.fromEntries(
  GENERATED.map(({ symbol }) => {
    const ltp = Number((20 + rand() * 3000).toFixed(2));
    const chp = Number(((rand() - 0.5) * 6).toFixed(2));
    const change = Number(((chp / 100) * ltp).toFixed(2));
    const turnover = Number((0.1 + rand() * 3).toFixed(2));
    const delivery = Number((25 + rand() * 55).toFixed(1));
    const freshness = rand() < 0.08 ? "stale" : rand() < 0.2 ? "provis" : "final";
    return [symbol, { ltp, chp, change, turnover, delivery, state: "LIVE", freshness }];
  }),
);
