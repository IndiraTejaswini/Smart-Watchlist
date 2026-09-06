import { Link } from "react-router-dom";
import Num from "./Num.jsx";

const STEPS = [
  ["Detected", 41],
  ["Corporate action", 2],
  ["Market-wide", 11],
  ["Sector-grouped", 4],
  ["Below the cap", 20],
  ["Shown", 4],
];

export default function AttentionBudget() {
  return (
    <section className="border-t border-hairline py-6 md:border-r md:pr-8">
      <h2 className="text-ui text-chalk">Attention budget</h2>
      <div className="mt-5 space-y-3">
        {STEPS.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[1fr_auto] items-center gap-4 text-micro text-slate">
            <span>{label}</span>
            <Num value={value} kind="plain" className="text-chalk" />
            <span className="col-span-2 h-1 bg-hairline">
              <span className="block h-full bg-slate" style={{ width: `${Math.max(8, (value / 41) * 100)}%` }} />
            </span>
          </div>
        ))}
      </div>
      <Link to="/eval" className="mt-5 inline-block rounded-[3px] text-micro text-slate underline decoration-hairline underline-offset-4 hover:text-chalk">
        [ see how ]
      </Link>
    </section>
  );
}
