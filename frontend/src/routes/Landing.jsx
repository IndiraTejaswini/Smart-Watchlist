import { Link } from "react-router-dom";
import Num from "../components/Num.jsx";
import SubtractionHero from "../components/SubtractionHero.jsx";

const STEPS = [
  ["01", "Regulatory gate", "No corporate action becomes a false signal.", "R2"],
  ["02", "Statistical abnormality", "Own-history baselines separate unusual from ordinary.", "R7"],
  ["03", "Explanation", "Market, sector and filing context are tested.", "N1"],
  ["04", "Personal ranking", "A bounded brief puts the highest-value changes first.", "R10"],
];

const MPM_ROWS = [
  ["Tier 1", "₹0 to ₹1,000", "3.0%"],
  ["Tier 2", "₹1,001 to ₹5,000", "2.0%"],
  ["Tier 3", "₹5,001 to ₹10,000", "1.5%"],
  ["Tier 4", "Above ₹10,000", "1.0%"],
];

export default function Landing() {
  return (
    <main className="min-h-dvh bg-abyss">
      <header className="flex items-center justify-between border-b border-hairline px-6 py-5">
        <span className="text-ui text-chalk">Smart Watchlist</span>
        <nav className="flex items-center gap-6 text-ui text-slate">
          <a href="#how-it-decides">How it decides</a>
          <a href="#evidence">Evidence</a>
          <Link to="/login" className="rounded-[3px] border border-hairline px-4 py-2 text-chalk">Open</Link>
        </nav>
      </header>
      <div className="mx-auto max-w-[1200px] px-6">
        <SubtractionHero />
        <section className="border-b border-hairline py-16">
          <div className="max-w-[62ch] space-y-6 font-prose text-read leading-[1.65] text-chalk">
            <p>Most watchlists tell you what changed since yesterday&apos;s close, a date the exchange chose.</p>
            <p>Markets do not have a reading cursor. You cannot ask what changed since you last looked.</p>
            <p>This register keeps the period personal, then says nothing happened when that is the honest answer.</p>
          </div>
        </section>
        <section id="how-it-decides" className="border-b border-hairline py-16">
          <h2 className="text-section text-chalk">How it decides</h2>
          <div className="mt-10 grid gap-8 md:grid-cols-4">
            {STEPS.map(([number, title, text, clause]) => (
              <article key={number} className="border-t border-hairline pt-4">
                <Num value={Number(number)} kind="plain" className="text-slate" />
                <h3 className="mt-5 text-ui text-chalk">{title}</h3>
                <p className="mt-3 text-ui leading-[1.45] text-slate">{text}</p>
                <span className="mt-5 block num text-micro text-slate">{clause}</span>
              </article>
            ))}
          </div>
        </section>
        <section className="border-b border-hairline py-16">
          <h2 className="text-section text-chalk">The subtraction</h2>
          <p className="mt-3 text-ui text-slate">A reconciled evaluation funnel from the dispatch register.</p>
          <div className="mt-8 space-y-3">
            {[["Evaluated", 41], ["Corporate action", 2], ["Market-wide", 11], ["Sector", 4], ["Below the cap", 20], ["Shown", 4]].map(([label, value]) => (
              <div key={label} className="grid grid-cols-[9rem_auto_1fr] items-center gap-4 text-ui">
                <span className="text-slate">{label}</span>
                <Num value={value} kind="plain" className="text-chalk" />
                <span className="h-2 bg-hairline"><span className="block h-full bg-slate" style={{ width: `${Math.max(8, value / 41 * 100)}%` }} /></span>
              </div>
            ))}
          </div>
        </section>
        <section id="evidence" className="border-b border-hairline py-16">
          <h2 className="text-section text-chalk">Where the numbers come from</h2>
          <p className="mt-3 max-w-[62ch] font-prose text-read leading-[1.65] text-slate">
            The MPM thresholds are applied to adjusted prices and recorded with their source.
          </p>
          <table className="mt-8 w-full border-collapse text-left text-ui">
            <thead><tr className="border-b border-hairline text-slate"><th className="py-3">Tier</th><th>Price band</th><th>Threshold</th></tr></thead>
            <tbody>{MPM_ROWS.map((row) => <tr key={row[0]} className="border-b border-hairline"><td className="py-3 num">{row[0]}</td><td className="num">{row[1]}</td><td className="num">{row[2]}</td></tr>)}</tbody>
          </table>
          <a className="mt-6 inline-block text-ui text-slate underline decoration-hairline underline-offset-4" href="https://www.sebi.gov.in/legal/circulars.html" target="_blank" rel="noreferrer">SEBI circular reference</a>
        </section>
        <footer className="flex flex-wrap gap-6 py-10 text-micro text-slate">
          <span>NSE cash equity only. No BSE or derivatives.</span>
          <a href="https://github.com/" target="_blank" rel="noreferrer">Repository</a>
          <a href="/docs">Architecture documentation</a>
          <a href="/docs">Frontend specification</a>
        </footer>
      </div>
    </main>
  );
}
