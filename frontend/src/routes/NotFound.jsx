import { Link } from "react-router-dom";
import { Register } from "../lib/register.jsx";

/**
 * NotFound.jsx — the designed empty state for an unmatched path (12.3, 12.10).
 *
 * Previously a mistyped URL silently redirected to /tokens, an internal
 * design-token page, with no acknowledgement anything was wrong.
 */
export default function NotFound() {
  return (
    <Register value="dispatch">
      <section className="mx-auto flex min-h-[60vh] w-full max-w-[520px] flex-col items-start justify-center px-6 py-8">
        <p className="text-micro uppercase tracking-[0.18em] text-slate">404</p>
        <h1 className="mt-2 text-display text-chalk">Nothing at this address.</h1>
        <p className="mt-3 text-ui text-slate">
          The page you asked for does not exist, or the link is stale.
        </p>
        <Link
          to="/brief"
          className="mt-6 rounded-[3px] border border-hairline px-4 py-2 text-ui text-chalk hover:bg-panel-hi"
        >
          Go to the Brief
        </Link>
      </section>
    </Register>
  );
}
