import { memo, useEffect, useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Link, useParams } from "react-router-dom";
import FreshnessDot from "../components/FreshnessDot.jsx";
import Num from "../components/Num.jsx";
import Sparkline from "../components/Sparkline.jsx";
import { Register } from "../lib/register.jsx";
import { DEMO_WATCHLIST } from "../lib/mock/watchlist.js";
import { startMockTickStream } from "../lib/mock/ticks.js";
import { useQuoteStore } from "../store/useQuoteStore.js";

const ROW_HEIGHT = 58;

const QuoteRow = memo(function QuoteRow({ item, virtualRow, quote, feedState }) {
  const degraded = feedState === "FEED_DOWN" || feedState === "HALTED_MARKET";
  if (!quote) return null;
  const tone = degraded ? "stale" : quote.freshness;
  return (
    <div
      className="absolute left-0 right-0 grid grid-cols-[28px_1.4fr_1fr_0.9fr_0.9fr_0.9fr_0.9fr_74px] items-center gap-3 border-b border-hairline px-4 hover:bg-panel-hi"
      style={{ height: ROW_HEIGHT, transform: `translateY(${virtualRow.start}px)`, contain: "content" }}
    >
      <FreshnessDot tone={tone} srLabel={degraded ? "Stale" : tone} />
      <Link to={`/symbol/${item.symbol}`} className="num text-ui text-chalk">{item.symbol}</Link>
      <Num value={quote.ltp} kind="price" freshness={degraded ? feedState : undefined} className="text-right" />
      <Num value={quote.change} kind="signed" tone="direction" freshness={degraded ? feedState : undefined} className="text-right" />
      <Num value={quote.chp} kind="percent" tone="direction" className="text-right" />
      <Num value={quote.turnover * 10000000} kind="turnover" className="text-right" />
      <Num value={quote.delivery} kind="ratio" className="text-right" />
      <Sparkline value={quote.chp} className={quote.chp >= 0 ? "text-up" : "text-down"} />
    </div>
  );
}, (previous, next) => {
  const a = previous.virtualRow;
  const b = next.virtualRow;
  const previousQuote = previous.quote;
  const nextQuote = next.quote;
  return previous.item.symbol === next.item.symbol
    && a.index === b.index
    && a.start === b.start
    && previousQuote?.ltp === nextQuote?.ltp
    && previousQuote?.chp === nextQuote?.chp
    && previousQuote?.state === nextQuote?.state;
});

const ConnectedQuoteRow = function ConnectedQuoteRow({ item, virtualRow }) {
  const quote = useQuoteStore((state) => state.quotes[item.symbol]);
  const feedState = useQuoteStore((state) => state.feedState);
  return (
    <QuoteRow item={item} virtualRow={virtualRow} quote={quote} feedState={feedState} />
  );
};

export default function Watchlist() {
  const { id } = useParams();
  const parentRef = useRef(null);
  const setSubscriptions = useQuoteStore((state) => state.setSubscriptions);
  const feedState = useQuoteStore((state) => state.feedState);
  const virtualizer = useVirtualizer({ count: DEMO_WATCHLIST.length, getScrollElement: () => parentRef.current, estimateSize: () => ROW_HEIGHT, overscan: 3 });
  const virtualRows = virtualizer.getVirtualItems();
  const visibleKey = useMemo(() => virtualRows.map((row) => DEMO_WATCHLIST[row.index].symbol).join("|"), [virtualRows]);

  useEffect(() => {
    const handle = setTimeout(() => setSubscriptions(visibleKey ? visibleKey.split("|") : []), 200);
    return () => clearTimeout(handle);
  }, [setSubscriptions, visibleKey]);

  useEffect(() => startMockTickStream(visibleKey ? visibleKey.split("|") : []), [visibleKey]);

  return (
    <Register value="terminal">
      <section className="mx-auto flex h-full w-full max-w-[1440px] flex-col px-6 py-6">
        <header className="mb-5 flex items-baseline justify-between border-b border-hairline pb-4">
          <div><p className="text-micro uppercase tracking-[0.18em] text-slate">Watchlist</p><h1 className="mt-2 text-section text-chalk">Live register</h1></div>
          <span className="num text-micro text-slate">{id ?? "wl_demo"} · {DEMO_WATCHLIST.length} names</span>
        </header>
        <div className="grid grid-cols-[28px_1.4fr_1fr_0.9fr_0.9fr_0.9fr_0.9fr_74px] gap-3 border-b border-hairline px-4 pb-2 text-micro uppercase tracking-[0.12em] text-slate">
          <span>State</span><span>Symbol</span><span className="text-right">Last</span><span className="text-right">Change</span><span className="text-right">Change %</span><span className="text-right">Turnover</span><span className="text-right">Delivery</span><span>Range</span>
        </div>
        <div ref={parentRef} className="min-h-0 flex-1 overflow-auto">
          <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
            {virtualRows.map((virtualRow) => <ConnectedQuoteRow key={DEMO_WATCHLIST[virtualRow.index].symbol} item={DEMO_WATCHLIST[virtualRow.index]} virtualRow={virtualRow} />)}
          </div>
        </div>
        <div className="border-t border-hairline py-3 text-ui text-slate">
          {feedState === "FEED_DOWN" ? "The quote feed is unavailable. Prices are held as stale." : feedState === "HALTED_MARKET" ? "The market is halted. Prices are held as stale." : "Live quote feed · viewport subscriptions only"}
        </div>
      </section>
    </Register>
  );
}
