import { mockBrief } from "./brief.js";
import { mockExplain } from "./explain.js";
import { mockMarketStatus } from "./marketStatus.js";
import { mockMe } from "./me.js";
import { selectMarks } from "./signals.js";
import { CALENDAR_WINDOW, TRADING_SESSIONS } from "./tradingCalendar.js";
import { mockEvalCases, mockEvalContinuation, mockEvalFunnel } from "./eval.js";

/**
 * mock/index.js — the mock transport.
 *
 * This sits behind the identical function signature as the real fetch, so that
 * swapping `VITE_USE_MOCK` changes nothing above this line. Payloads match
 * ARCHITECTURE.md §16 exactly. When a screen needs a field the mock does not
 * have, the fix is to the mock, never to the component.
 *
 * Routes are registered as [method, RegExp, handler]. Handlers receive the URL
 * match groups and the parsed query string.
 */

const ROUTES = [
  ["GET", /^\/me$/, () => mockMe()],

  // The brief for a cursor position. `as_of` is what the spine sends when it
  // is dragged, so the period genuinely widens rather than replaying a fixture.
  ["GET", /^\/brief$/, (_m, query) => mockBrief(query.as_of)],
  ["GET", /^\/brief\/explain\/([^/]+)$/, (match) => mockExplain(match[1])],
  ["GET", /^\/market\/status$/, () => mockMarketStatus()],
  ["GET", /^\/eval\/funnel$/, () => mockEvalFunnel()],
  ["GET", /^\/eval\/cases$/, () => mockEvalCases()],
  ["GET", /^\/eval\/suppression-cases$/, () => mockEvalCases()],
  ["GET", /^\/eval\/continuation$/, () => mockEvalContinuation()],

  // The cursor spine's session axis. Clamped to the generated window rather
  // than extrapolated: the calendar knows what it was built from, and a spine
  // drawn past the end of real data would be inventing sessions.
  ["GET", /^\/market\/calendar$/, (_m, query) => {
    const from = query.from ?? CALENDAR_WINDOW.from;
    const to = query.to ?? CALENDAR_WINDOW.to;
    return {
      window: { from, to },
      sessions: TRADING_SESSIONS.filter((s) => s.date >= from && s.date <= to),
    };
  }],

  // Signal marks for the spine. `symbol` narrows it to one name, which is what
  // /symbol/:symbol needs (§3).
  ["GET", /^\/watchlists\/([^/]+)\/signals$/, (match, query) => ({
    watchlist_id: match[1],
    marks: selectMarks({
      from: query.from,
      to: query.to,
      symbol: query.symbol,
    }),
  })],
];

/**
 * A small artificial latency. Without it every screen renders instantly and the
 * loading and skeleton states — which §7 requires to exist and to match the
 * loaded geometry — never actually get exercised during development.
 */
const MOCK_LATENCY_MS = 120;

/**
 * @param {string} method
 * @param {string} path e.g. "/brief?watchlist_id=wl_1"
 * @param {unknown} body
 */
export async function handleMock(method, path, body) {
  const [pathname, search = ""] = path.split("?");
  const query = Object.fromEntries(new URLSearchParams(search));

  for (const [routeMethod, pattern, handler] of ROUTES) {
    if (routeMethod !== method) continue;
    const match = pattern.exec(pathname);
    if (!match) continue;
    await delay(MOCK_LATENCY_MS);
    return handler(match, query, body);
  }

  // A missing mock route is a real gap and should read like one, in the same
  // RFC 7807 shape the backend uses (§16), not as an undefined that quietly
  // renders as an empty screen.
  await delay(MOCK_LATENCY_MS);
  const error = new Error(`No mock route for ${method} ${pathname}`);
  error.status = 404;
  error.title = "Not implemented in the mock";
  error.detail = `No mock route for ${method} ${pathname}`;
  throw error;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
