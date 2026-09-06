import { Link } from "react-router-dom";
import Num from "./Num.jsx";

/**
 * BudgetLine — "We looked at 41 changes and showed you 4."
 *
 * §16.1: "The budget block is returned on every response and rendered. It is
 * the product's own argument made visible." §5.4 makes it permanent, not a
 * tooltip — so it renders at the bottom of every brief, present or empty,
 * rather than appearing only when there is something to boast about.
 *
 * "see how" is a plain link to the funnel on /eval — the full accounting of
 * where the other 37 went — not a repetition of the funnel here. The Brief
 * states the headline number; /eval is where it is proven.
 */
export default function BudgetLine({ budget }) {
  return (
    <div className="flex items-baseline justify-between border-t border-hairline py-6 text-ui text-slate">
      <p>
        We looked at <Num value={budget.candidates_detected} kind="plain" className="text-chalk" />{" "}
        changes and showed you{" "}
        <Num value={budget.surfaced} kind="plain" className="text-chalk" />.
      </p>
      <Link
        to="/eval"
        className="rounded-edge text-micro text-slate underline decoration-hairline underline-offset-4 hover:text-chalk"
      >
        see how
      </Link>
    </div>
  );
}
