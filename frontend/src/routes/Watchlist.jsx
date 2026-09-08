import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Link, useParams } from "react-router-dom";
import FreshnessDot from "../components/FreshnessDot.jsx";
import Num from "../components/Num.jsx";
import Sparkline from "../components/Sparkline.jsx";
import { Register } from "../lib/register.jsx";
import { useReorderWatchlistItem, useWatchlistItems } from "../lib/api/queries.js";
import { GENERATED_QUOTES, LIVE_BY_SYMBOL } from "../lib/mock/liveWatchlist.js";
import { startMockTickStream } from "../lib/mock/ticks.js";
import { useQuoteStore } from "../store/useQuoteStore.js";

const ROW_HEIGHT = 58;
const DEFAULT_WATCHLIST_ID = "wl_demo";

const QuoteRow = memo(function QuoteRow({
  item,
  virtualRow,
  quote,
  feedState,
  isDragging,
  isDropTarget,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}) {
  const degraded = feedState === "FEED_DOWN" || feedState === "HALTED_MARKET";
  if (!quote) return null;
  const tone = degraded ? "stale" : quote.freshness;
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      className={`absolute left-0 right-0 grid grid-cols-[20px_28px_1.4fr_1fr_0.9fr_0.9fr_0.9fr_0.9fr_74px] items-center gap-3 border-b border-hairline px-4 hover:bg-panel-hi ${isDragging ? "opacity-40" : ""} ${isDropTarget ? "border-t-2 border-t-chalk" : ""}`}
      style={{ height: ROW_HEIGHT, transform: `translateY(${virtualRow.start}px)`, contain: "content" }}
    >
      <span className="cursor-grab select-none text-slate" aria-hidden="true" title="Drag to reorder">⠿</span>
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
    && previousQuote?.state === nextQuote?.state
    && previous.isDragging === next.isDragging
    && previous.isDropTarget === next.isDropTarget;
});

const ConnectedQuoteRow = function ConnectedQuoteRow({ item, virtualRow, dragState, dragHandlers }) {
  const quote = useQuoteStore((state) => state.quotes[item.symbol]);
  const feedState = useQuoteStore((state) => state.feedState);
  return (
    <QuoteRow
      item={item}
      virtualRow={virtualRow}
      quote={quote}
      feedState={feedState}
      isDragging={dragState.draggedSymbol === item.symbol}
      isDropTarget={dragState.dropTargetSymbol === item.symbol}
      onDragStart={() => dragHandlers.onDragStart(item.symbol)}
      onDragOver={(event) => dragHandlers.onDragOver(event, item.symbol)}
      onDrop={() => dragHandlers.onDrop(item.symbol)}
      onDragEnd={dragHandlers.onDragEnd}
    />
  );
};

function WatchlistSkeleton() {
  return (
    <div className="space-y-3 px-4 pt-4">
      {Array.from({ length: 12 }, (_, index) => (
        <div key={index} className="h-[42px] animate-pulse rounded-[3px] bg-panel-hi" />
      ))}
    </div>
  );
}

export default function Watchlist() {
  const { id } = useParams();
  const watchlistId = id ?? DEFAULT_WATCHLIST_ID;
  const parentRef = useRef(null);
  const setSubscriptions = useQuoteStore((state) => state.setSubscriptions);
  const seedQuotes = useQuoteStore((state) => state.seedQuotes);
  const feedState = useQuoteStore((state) => state.feedState);
  const itemsQuery = useWatchlistItems(watchlistId);
  const reorder = useReorderWatchlistItem(watchlistId);
  const [dragState, setDragState] = useState({ draggedSymbol: null, dropTargetSymbol: null });

  useEffect(() => {
    seedQuotes(GENERATED_QUOTES);
  }, [seedQuotes]);

  const rows = useMemo(
    () =>
      (itemsQuery.data?.items ?? []).map(
        (row) => LIVE_BY_SYMBOL[row.symbol] ?? { symbol: row.symbol, company_name: row.symbol, sector: "Unassigned" },
      ),
    [itemsQuery.data],
  );

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 6,
  });
  const virtualRows = virtualizer.getVirtualItems();
  const visibleKey = useMemo(() => virtualRows.map((row) => rows[row.index]?.symbol).join("|"), [virtualRows, rows]);

  useEffect(() => {
    const handle = setTimeout(() => setSubscriptions(visibleKey ? visibleKey.split("|") : []), 200);
    return () => clearTimeout(handle);
  }, [setSubscriptions, visibleKey]);

  useEffect(() => startMockTickStream(visibleKey ? visibleKey.split("|") : []), [visibleKey]);

  const dragHandlers = useMemo(() => ({
    onDragStart: (symbol) => setDragState({ draggedSymbol: symbol, dropTargetSymbol: null }),
    onDragOver: (event, symbol) => {
      event.preventDefault();
      setDragState((state) =>
        state.dropTargetSymbol === symbol ? state : { ...state, dropTargetSymbol: symbol },
      );
    },
    onDrop: (targetSymbol) => {
      setDragState((state) => {
        const { draggedSymbol } = state;
        if (draggedSymbol && draggedSymbol !== targetSymbol) {
          const targetIndex = rows.findIndex((row) => row.symbol === targetSymbol);
          const beforeSymbol = rows[targetIndex]?.symbol;
          const afterSymbol = targetIndex > 0 ? rows[targetIndex - 1]?.symbol : undefined;
          if (afterSymbol !== draggedSymbol) {
            reorder.mutate({ symbol: draggedSymbol, afterSymbol, beforeSymbol });
          }
        }
        return { draggedSymbol: null, dropTargetSymbol: null };
      });
    },
    onDragEnd: () => setDragState({ draggedSymbol: null, dropTargetSymbol: null }),
  }), [rows, reorder]);

  return (
    <Register value="terminal">
      <section className="mx-auto flex h-full w-full max-w-[1440px] flex-col px-6 py-6">
        <header className="mb-5 flex items-baseline justify-between border-b border-hairline pb-4">
          <div><p className="text-micro uppercase tracking-[0.18em] text-slate">Watchlist</p><h1 className="mt-2 text-section text-chalk">Live register</h1></div>
          <span className="num text-micro text-slate">{watchlistId} · {rows.length} names</span>
        </header>
        <div className="grid grid-cols-[20px_28px_1.4fr_1fr_0.9fr_0.9fr_0.9fr_0.9fr_74px] gap-3 border-b border-hairline px-4 pb-2 text-micro uppercase tracking-[0.12em] text-slate">
          <span aria-hidden="true" /><span className="sr-only">State</span><span>Symbol</span><span className="text-right">Last</span><span className="text-right">Change</span><span className="text-right">Change %</span><span className="text-right">Turnover</span><span className="text-right">Delivery</span><span>Range</span>
        </div>
        {itemsQuery.isPending ? <WatchlistSkeleton /> : null}
        {itemsQuery.isError ? (
          <p className="border-t border-hairline py-8 text-ui text-slate">
            This watchlist could not be loaded. Try again in a moment.
          </p>
        ) : null}
        {!itemsQuery.isPending && !itemsQuery.isError && rows.length === 0 ? (
          <p className="border-t border-hairline py-8 text-ui text-slate">
            Nothing on this watchlist yet.
          </p>
        ) : null}
        {rows.length > 0 ? (
          <div ref={parentRef} className="min-h-0 flex-1 overflow-auto">
            <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
              {virtualRows.map((virtualRow) => (
                <ConnectedQuoteRow
                  key={rows[virtualRow.index].symbol}
                  item={rows[virtualRow.index]}
                  virtualRow={virtualRow}
                  dragState={dragState}
                  dragHandlers={dragHandlers}
                />
              ))}
            </div>
          </div>
        ) : null}
        <div className="border-t border-hairline py-3 text-ui text-slate">
          {feedState === "FEED_DOWN" ? "The quote feed is unavailable. Prices are held as stale." : feedState === "HALTED_MARKET" ? "The market is halted. Prices are held as stale." : "Live quote feed · viewport subscriptions only · drag a row to reorder"}
        </div>
      </section>
    </Register>
  );
}
