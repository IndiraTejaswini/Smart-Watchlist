import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Num from "./Num.jsx";

const TICKERS = [
  "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "AXISBANK",
  "TATAMOTORS", "MARUTI", "BHARTIARTL", "SUNPHARMA", "WIPRO", "HCLTECH",
  "IDEA", "ITC", "LT", "KOTAKBANK", "ADANIENT", "ASIANPAINT", "HINDUNILVR",
  "BAJFINANCE", "M&M", "NESTLEIND", "TECHM", "POWERGRID", "NTPC", "ONGC",
  "COALINDIA", "DRREDDY", "CIPLA", "DIVISLAB", "EICHERMOT", "GRASIM",
  "JSWSTEEL", "TATASTEEL", "ULTRACEMCO", "HEROMOTOCO", "BRITANNIA", "APOLLOHOSP",
  "ADANIPORTS",
];

function TickerRows({ collapsed }) {
  return (
    <div className="space-y-1">
      {collapsed ? (
        <>
          <div className="border-b border-hairline py-3">
            <span className="num text-chalk">TATAMOTORS</span>
            <Num value={-7.2} kind="percent" dp={1} tone="direction" className="float-right" />
            <p className="mt-1 text-micro text-slate">Q2 results, filed Tuesday</p>
          </div>
          <div className="border-b border-hairline py-3">
            <span className="num text-chalk">BHARTIARTL</span>
            <Num value={4.1} kind="percent" dp={1} tone="direction" className="float-right" />
            <p className="mt-1 text-micro text-slate">No filing found</p>
          </div>
          <div className="py-3 font-prose text-read text-slate">
            <span className="num">11</span> others: nothing
          </div>
        </>
      ) : (
        TICKERS.map((ticker) => (
          <div key={ticker} className="ticker-row border-b border-hairline py-2 text-micro text-slate">
            <span className="num">{ticker}</span>
          </div>
        ))
      )}
    </div>
  );
}

export default function SubtractionHero() {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setCollapsed(true);
      return undefined;
    }
    const timer = window.setTimeout(() => setCollapsed(true), 2500);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <section className="grid gap-12 border-b border-hairline py-16 lg:grid-cols-2 lg:gap-16">
      <div className="self-center">
        <p className="font-prose text-[48px] leading-[1.05] tracking-[-0.03em] text-chalk">
          You have <Num value={14} kind="plain" /> stocks on your watchlist. Three of them did something.
        </p>
        <p className="mt-8 max-w-[62ch] font-prose text-read leading-[1.65] text-slate">
          Every watchlist measures change from the market close. This one measures
          what changed since you last looked, and stays quiet when nothing needs your attention.
        </p>
        <div className="mt-8 flex items-center gap-5">
          <Link to="/brief" className="rounded-[3px] border border-chalk bg-chalk px-4 py-3 text-ui text-abyss">
            Open the demo
          </Link>
          <Link to="/login" className="rounded-[3px] border border-hairline px-4 py-3 text-ui text-slate hover:text-chalk">
            Sign in
          </Link>
        </div>
        <p className="mt-4 text-micro text-slate">No signup needed for the demo.</p>
      </div>
      <div className={`min-h-[460px] border border-hairline bg-panel p-6 ${collapsed ? "is-collapsed" : ""}`}>
        <TickerRows collapsed={collapsed} />
        <style>{`
          .ticker-row { animation: subtraction-dim 2.5s cubic-bezier(.2,0,0,1) forwards; }
          .ticker-row:nth-child(n+4) { animation-delay: 80ms; }
          @keyframes subtraction-dim {
            0% { opacity: 1; max-height: 40px; transform: scaleY(1); }
            100% { opacity: .2; max-height: 0; padding-top: 0; padding-bottom: 0; transform: scaleY(0); overflow: hidden; }
          }
          @media (prefers-reduced-motion: reduce) {
            .ticker-row { animation: none; }
          }
        `}</style>
      </div>
    </section>
  );
}
