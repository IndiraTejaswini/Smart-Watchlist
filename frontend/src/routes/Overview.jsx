import { useEffect } from "react";
import { Register } from "../lib/register.jsx";
import { useBrief, useMe } from "../lib/api/queries.js";
import { useCursorStore } from "../store/useCursorStore.js";
import PriceChart from "../components/PriceChart.jsx";
import BenchmarkCards from "../components/BenchmarkCards.jsx";
import AttentionBudget from "../components/AttentionBudget.jsx";
import SectorMovement from "../components/SectorMovement.jsx";
import RecentSignals from "../components/RecentSignals.jsx";

function OverviewSkeleton() {
  return (
    <div className="animate-pulse space-y-6">
      <div className="grid h-28 grid-cols-3 gap-px bg-hairline">
        {[0, 1, 2].map((item) => <div key={item} className="bg-panel" />)}
      </div>
      <div className="h-[320px] bg-panel" />
      <div className="grid h-72 grid-cols-2 gap-px bg-hairline">
        <div className="bg-panel" /><div className="bg-panel" />
      </div>
      <div className="h-48 bg-panel" />
    </div>
  );
}

export default function Overview() {
  const { data: me } = useMe();
  const cursorIso = useCursorStore((state) => state.cursorIso);
  const brief = useBrief(me?.default_watchlist_id, cursorIso);

  useEffect(() => {
    if (me?.cursor?.acknowledged_through) {
      useCursorStore.getState().hydrate(me.cursor.acknowledged_through);
    }
  }, [me]);

  return (
    <Register value="terminal">
      <section className="mx-auto w-full max-w-[1200px] px-6 py-8">
        {brief.isPending ? <OverviewSkeleton /> : null}
        {brief.data ? (
          <div className="space-y-6">
            <BenchmarkCards />
            <header className="flex items-baseline justify-between">
              <h1 className="text-section text-chalk">Your list against the market</h1>
              <span className="num text-micro text-slate">since {brief.data.cursor.acknowledged_through.slice(0, 10)}</span>
            </header>
            <PriceChart cursorDate={brief.data.cursor.acknowledged_through.slice(0, 10)} asOf={brief.data.generated_at} />
            <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
              <AttentionBudget />
              <SectorMovement />
            </div>
            <RecentSignals
              signals={brief.data.items.slice(0, 3).map((item) => ({
                date: item.session_date ?? brief.data.generated_at.slice(0, 10),
                symbol: item.symbol,
                change: item.metrics.pct_move,
                classification: item.classification.toLowerCase(),
              }))}
            />
          </div>
        ) : null}
        {!brief.isPending && !brief.data ? <OverviewSkeleton /> : null}
      </section>
    </Register>
  );
}
