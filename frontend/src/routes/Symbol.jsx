import { useState } from "react";
import { useParams } from "react-router-dom";
import Num from "../components/Num.jsx";
import PriceChartDetail from "../components/PriceChartDetail.jsx";
import FreshnessDot from "../components/FreshnessDot.jsx";
import { Register } from "../lib/register.jsx";
import { useQuoteStore } from "../store/useQuoteStore.js";

export default function Symbol() {
  const { symbol = "RELIANCE" } = useParams();
  const [asTraded, setAsTraded] = useState(false);
  const quote = useQuoteStore((state) => state.quotes[symbol]) ?? { ltp: 0, chp: 0, change: 0 };
  return (
    <Register value="terminal">
      <section className="mx-auto w-full max-w-[1440px] px-6 py-6">
        <header className="mb-6 flex items-end justify-between border-b border-hairline pb-4">
          <div><span className="num text-micro text-slate">SYMBOL</span><h1 className="mt-2 text-section text-chalk">{symbol}</h1></div>
          <div className="flex items-center gap-5"><Num value={quote.ltp} kind="price" /><Num value={quote.chp} kind="percent" tone="direction" /><label className="flex items-center gap-2 text-ui text-slate"><input type="checkbox" checked={asTraded} onChange={(event) => setAsTraded(event.target.checked)} /> As traded</label></div>
        </header>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[3fr_2fr]">
          <PriceChartDetail asTraded={asTraded} />
          <aside className="space-y-6 border-l border-hairline pl-6">
            <section><h2 className="text-ui uppercase tracking-[0.14em] text-slate">What we know</h2><dl className="mt-4 space-y-3 text-ui"><div className="flex justify-between border-b border-hairline pb-2"><dt className="text-slate">Baseline window</dt><dd className="num text-chalk">20 sessions</dd></div><div className="flex justify-between border-b border-hairline pb-2"><dt className="text-slate">Data quality</dt><dd><FreshnessDot tone="final" label="Final" /></dd></div><div className="flex justify-between border-b border-hairline pb-2"><dt className="text-slate">09:30 index source</dt><dd className="num text-chalk">Captured live</dd></div><div className="flex justify-between border-b border-hairline pb-2"><dt className="text-slate">Liquidity floor</dt><dd className="text-final">Passed</dd></div></dl></section>
            <section><h2 className="text-ui uppercase tracking-[0.14em] text-slate">Signal history</h2><p className="mt-3 text-ui text-chalk">Engine marks on 03 August and 10 August. Each mark retains its input snapshot.</p></section>
            <section><h2 className="text-ui uppercase tracking-[0.14em] text-slate">Linked filings</h2><ul className="mt-3 space-y-2 text-ui text-chalk"><li className="flex justify-between"><span>Quarterly filing</span><span className="num text-slate">12 Aug 16:10 IST</span></li><li className="flex justify-between"><span>Exchange notice</span><span className="num text-slate">08 Aug 09:22 IST</span></li></ul></section>
          </aside>
        </div>
      </section>
    </Register>
  );
}
