/**
 * watchlist.js — the demo user's list.
 *
 * Fourteen names, because FRONTEND_SPEC §5.1 and §5.4 both describe a list of
 * fourteen and the Brief's quiet line ("Nine others: nothing notable") only adds
 * up against that number.
 *
 * The composition is chosen to exercise the engine's own branches rather than
 * to look plausible:
 *
 *   Four IT names   INFY, TCS, WIPRO, HCLTECH — exactly SECTOR_MIN_PEERS (=4),
 *                   so the sector-wide grouping branch in §16's `sector_groups`
 *                   has the minimum peer count it needs to fire at all.
 *   Four banks      A second sector large enough to group, so "grouped, not
 *                   surfaced" is demonstrably a decision and not an artefact of
 *                   there being only one candidate group.
 *   IDEA            A low-priced name, which is the tier where the MPM
 *                   threshold is 5.0% rather than 3.0%, and the carrier of the
 *                   1:1 bonus corporate-action notice in §16.
 *
 * Company names and sectors only; no prices live here. Quotes arrive from the
 * quote source, and a hard-coded price in a fixture is the fastest way to end
 * up rendering a number nobody can trace.
 */

/** @typedef {{symbol: string, company_name: string, sector: string}} WatchlistItem */

export const DEMO_WATCHLIST_ID = "wl_demo";

/** @type {WatchlistItem[]} */
export const DEMO_WATCHLIST = [
  { symbol: "RELIANCE", company_name: "Reliance Industries Ltd", sector: "Energy" },
  { symbol: "TCS", company_name: "Tata Consultancy Services Ltd", sector: "IT" },
  { symbol: "INFY", company_name: "Infosys Ltd", sector: "IT" },
  { symbol: "WIPRO", company_name: "Wipro Ltd", sector: "IT" },
  { symbol: "HCLTECH", company_name: "HCL Technologies Ltd", sector: "IT" },
  { symbol: "HDFCBANK", company_name: "HDFC Bank Ltd", sector: "Banking" },
  { symbol: "ICICIBANK", company_name: "ICICI Bank Ltd", sector: "Banking" },
  { symbol: "SBIN", company_name: "State Bank of India", sector: "Banking" },
  { symbol: "AXISBANK", company_name: "Axis Bank Ltd", sector: "Banking" },
  { symbol: "TATAMOTORS", company_name: "Tata Motors Ltd", sector: "Auto" },
  { symbol: "MARUTI", company_name: "Maruti Suzuki India Ltd", sector: "Auto" },
  { symbol: "BHARTIARTL", company_name: "Bharti Airtel Ltd", sector: "Telecom" },
  { symbol: "IDEA", company_name: "Vodafone Idea Ltd", sector: "Telecom" },
  { symbol: "SUNPHARMA", company_name: "Sun Pharmaceutical Industries Ltd", sector: "Pharma" },
];

/** @type {Record<string, WatchlistItem>} */
export const BY_SYMBOL = Object.fromEntries(
  DEMO_WATCHLIST.map((item) => [item.symbol, item]),
);
