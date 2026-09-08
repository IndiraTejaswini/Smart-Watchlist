import { NavLink } from "react-router-dom";
import { useMe } from "../../lib/api/queries.js";

/**
 * NavBar — §4. 52px, --abyss ground, one hairline underneath.
 *
 * The wordmark is a small filled diamond and the product name. The diamond is
 * --chalk, not --flare: amber marks a position in time and a logo is not one
 * (§2.1). Active link is --chalk with a 2px --chalk underline, inactive
 * --slate. No icons — §6 admits them only where they carry meaning, and a house
 * icon beside the word "Brief" carries none.
 */

export default function NavBar() {
  const { data: me } = useMe();
  // The route is /watchlist/:id (no bare /watchlist), so "Lists" needs a
  // real id to link to. A hardcoded mock id here resolves to nothing against
  // the real API — see /api/me's default_watchlist_id instead. useMe() has
  // staleTime: Infinity, so this is a cache hit, not a second request, once
  // any other screen has already fetched it.
  const links = [
    { to: "/brief", label: "Brief" },
    { to: "/overview", label: "Overview" },
    // Falls back to /brief, not a bare /watchlist/, in the brief window
    // before /api/me resolves — the route requires :id, so an empty segment
    // 404s rather than rendering anything.
    { to: me?.default_watchlist_id ? `/watchlist/${me.default_watchlist_id}` : "/brief", label: "Lists" },
    { to: "/eval", label: "Evaluation" },
  ];

  return (
    <header className="flex h-nav shrink-0 items-center gap-8 border-b border-hairline bg-abyss px-5">
      <NavLink
        to="/brief"
        className="flex items-center gap-2.5 rounded-edge text-chalk"
      >
        <span
          aria-hidden="true"
          className="size-2 rotate-45 bg-chalk"
        />
        <span className="font-ui text-ui font-semibold tracking-[-0.01em]">
          Smart Watchlist
        </span>
      </NavLink>

      <nav className="flex items-center gap-6" aria-label="Primary">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              [
                "relative rounded-edge py-1 text-ui transition-colors",
                isActive
                  ? "text-chalk after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-chalk"
                  : "text-slate hover:text-chalk",
              ].join(" ")
            }
          >
            {link.label}
          </NavLink>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-4">
        <button
          type="button"
          className="rounded-edge border border-hairline px-2 py-1 text-micro text-slate hover:border-slate hover:text-chalk"
        >
          {/* Mono for a keycap and for initials, but not the `.num` class:
              that class asserts "this is a numeral" and carries tabular
              figures, which neither of these is. */}
          <span className="font-num">⌘K</span>
          <span className="ml-2">Search</span>
        </button>
        <span
          className="flex size-7 items-center justify-center rounded-full bg-panel text-micro text-slate"
          title="Demo account"
        >
          <span className="font-num">AR</span>
        </span>
      </div>
    </header>
  );
}
