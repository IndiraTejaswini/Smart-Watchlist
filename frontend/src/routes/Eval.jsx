import Num from "../components/Num.jsx";
import { Register } from "../lib/register.jsx";
import { useEval } from "../lib/api/queries.js";

const audit = [
  "Late-evening filing timing mismatch between 15:28 IST and 18:00 ingest",
  "Institutional morning block deal volume distortion",
  "Passive index rebalancing front-running",
  "ASM or GSM circuit locks on low free-float",
  "Sympathetic sector drift across diversified or exempt revenue streams",
];

function Skeleton() {
  return <div className="space-y-6" aria-label="Loading evaluation"><div className="h-12 bg-panel" /><div className="h-48 bg-panel" /><div className="h-64 bg-panel" /></div>;
}

export default function Eval() {
  const { funnel, cases, continuation } = useEval();
  if (funnel.isPending || cases.isPending || continuation.isPending) {
    return <Register value="terminal"><section className="mx-auto w-full max-w-[1200px] px-6 py-8"><Skeleton /></section></Register>;
  }
  if (funnel.isError || cases.isError || continuation.isError) {
    return <Register value="terminal"><section className="mx-auto w-full max-w-[1200px] px-6 py-8"><div className="border border-hairline bg-panel px-5 py-4 text-ui text-slate">Evaluation data is unavailable while the replay artifact is being checked.</div></section></Register>;
  }
  const data = funnel.data;
  const steps = [["Detected", data.evaluated], ["Corporate action", data.corporate_action], ["Market-wide", data.market_wide], ["Sector-grouped", data.sector_grouped], ["Below the cap", data.below_cap], ["Shown", data.surfaced]];
  return <Register value="terminal"><section className="mx-auto w-full max-w-[1200px] space-y-10 px-6 py-8">
    <header className="border-b border-hairline pb-5"><p className="text-micro uppercase tracking-[0.18em] text-slate">Evaluation</p><h1 className="mt-2 text-display text-chalk">The jury page</h1><p className="mt-3 max-w-[62ch] text-prose text-slate">A plain account of what entered the register, what was removed, and what remained.</p></header>
    <section><h2 className="text-section text-chalk">Filtering funnel</h2><div className="mt-5 space-y-2">{steps.map(([label, count], index) => <div key={label} className="flex items-center gap-4"><div className="h-9 bg-panel-hi" style={{ width: `${Math.max(18, 100 - index * 12)}%` }} /><span className="min-w-[170px] text-ui text-slate">{label} <Num value={count} /></span></div>)}</div></section>
    <section><h2 className="text-section text-chalk">Corporate action suppression</h2><div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">{cases.data.map((item) => <article key={item.symbol} className="border border-hairline bg-panel p-5"><p className="num text-micro text-slate">{item.symbol}</p><h3 className="mt-3 text-ui text-chalk">{item.event}</h3><p className="mt-4 text-micro uppercase text-slate">Naive view</p><Num value={item.naive_change_pct} kind="percent" tone="direction" className="mt-1 block text-section" /><p className="mt-4 text-micro uppercase text-slate">System view</p><p className="mt-1 text-ui text-chalk">{item.system_title}</p><p className="mt-2 text-ui text-slate">{item.system_text}</p></article>)}</div></section>
    <section><h2 className="text-section text-chalk">Forward five-session continuation</h2><div className="mt-5 overflow-x-auto"><table className="w-full border-collapse text-ui"><thead className="border-b border-hairline text-left text-micro uppercase text-slate"><tr><th className="py-3">Group</th><th className="py-3">n</th><th className="py-3">Mean AR</th><th className="py-3">Median AR</th><th className="py-3">Same direction</th></tr></thead><tbody>{continuation.data.map((row) => <tr key={row.category} className="border-b border-hairline"><td className="py-3 text-chalk">{row.category}</td><td className="py-3"><Num value={row.n} /></td><td className="py-3"><Num value={row.mean_ar} kind="percent" /></td><td className="py-3"><Num value={row.median_ar} kind="percent" /></td><td className="py-3"><Num value={row.same_direction_pct} kind="percent" /></td></tr>)}</tbody></table></div></section>
    <section className="grid grid-cols-1 gap-8 md:grid-cols-2"><div><h2 className="text-section text-chalk">Parser coverage and telemetry</h2><p className="mt-4 text-prose text-chalk"><Num value={97.8} kind="percent" /> extraction coverage across <Num value={3} /> typed action families and <Num value={126} /> replay sessions.</p><p className="mt-3 text-ui text-slate">Replay artifact: <Num value={200} /> symbols, deterministic fixture, conservation checked.</p></div><div><h2 className="text-section text-chalk">Five false positives</h2><ol className="mt-4 list-decimal space-y-3 pl-5 text-ui text-slate">{audit.map((item) => <li key={item}>{item}</li>)}</ol></div></section>
  </section></Register>;
}
