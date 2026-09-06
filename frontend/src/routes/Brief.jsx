import { useEffect, useState } from "react";
import { useMe, useBrief } from "../lib/api/queries.js";
import { useCursorStore } from "../store/useCursorStore.js";
import { Register } from "../lib/register.jsx";
import BriefItem from "../components/BriefItem.jsx";
import BudgetLine from "../components/BudgetLine.jsx";
import CorpActionNotice from "../components/CorpActionNotice.jsx";
import ExplainPanel from "../components/ExplainPanel.jsx";
import QuietLine from "../components/QuietLine.jsx";

function BriefSkeleton() {
  return (
    <div aria-label="Loading brief" className="animate-pulse">
      <div className="h-10 w-5/6 border-b border-hairline" />
      <div className="mt-10 h-24 border-b border-hairline" />
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className="border-t border-hairline py-8">
          <div className="h-7 w-2/3 bg-panel" />
          <div className="mt-5 h-24 max-w-measure bg-panel" />
          <div className="mt-5 h-5 w-1/3 bg-panel" />
        </div>
      ))}
      <div className="h-16 border-t border-hairline" />
    </div>
  );
}

function EmptyBrief() {
  return (
    <div className="border-t border-hairline py-8 font-prose text-read leading-[1.65] text-chalk">
      <p>Nothing notable since <span className="num">09:15</span> this morning.</p>
      <p>Your names moved less than their own normal range.</p>
      <p>Move the cursor back to see a longer period.</p>
    </div>
  );
}

export default function Brief() {
  const { data: me } = useMe();
  const cursorIso = useCursorStore((state) => state.cursorIso);
  const [explainId, setExplainId] = useState(null);
  const watchlistId = me?.default_watchlist_id;
  const brief = useBrief(watchlistId, cursorIso);

  useEffect(() => {
    if (me?.cursor?.acknowledged_through) {
      useCursorStore.getState().hydrate(me.cursor.acknowledged_through);
    }
  }, [me]);

  return (
    <Register value="dispatch">
      <section className="mx-auto w-full max-w-[66ch] px-6 py-12">
        {brief.isPending ? <BriefSkeleton /> : null}
        {brief.isError ? (
          <p className="border-t border-hairline py-8 font-prose text-read text-chalk">
            The brief is unavailable while market data is being checked.
          </p>
        ) : null}
        {brief.data ? (
          <>
            <header className="border-b border-hairline pb-8">
              <h1 className="font-prose text-section leading-[1.3] text-chalk">
                {brief.data.headline}
              </h1>
              {brief.data.market_rollup.present ? (
                <p className="mt-5 font-prose text-read leading-[1.65] text-slate">
                  {brief.data.market_rollup.text}
                </p>
              ) : null}
            </header>
            {brief.data.items.length === 0 ? <EmptyBrief /> : null}
            {brief.data.items.map((item) => (
              <BriefItem key={item.signal_event_id} item={item} onExplain={setExplainId} />
            ))}
            <QuietLine text={brief.data.quiet.text} />
            {brief.data.corporate_action_notices.map((notice) => (
              <CorpActionNotice key={`${notice.symbol}-${notice.ex_date}`} notice={notice} />
            ))}
            <BudgetLine budget={{ ...brief.data.budget, below_cap: 20 }} />
          </>
        ) : null}
        {explainId ? (
          <ExplainPanel
            item={brief.data?.items.find((item) => item.signal_event_id === explainId) ?? null}
            onClose={() => setExplainId(null)}
          />
        ) : null}
      </section>
    </Register>
  );
}
