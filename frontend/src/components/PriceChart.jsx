import { useEffect, useRef } from "react";
import { createChart, LineStyle } from "lightweight-charts";

const DEFAULT_SERIES = [
  { time: "2026-08-12", watchlist: 100, benchmark: 100 },
  { time: "2026-08-13", watchlist: 99.4, benchmark: 99.7 },
  { time: "2026-08-14", watchlist: 98.8, benchmark: 99.2 },
  { time: "2026-08-17", watchlist: 98.1, benchmark: 98.9 },
  { time: "2026-08-18", watchlist: 97.6, benchmark: 98.5 },
  { time: "2026-08-19", watchlist: 97.1, benchmark: 98.1 },
];

export default function PriceChart({ data = DEFAULT_SERIES, cursorDate, asOf }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 260,
      layout: { background: { color: "#101927" }, textColor: "#7D8DA3" },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: "rgba(30, 42, 61, 0.4)", style: LineStyle.Solid },
      },
      rightPriceScale: { borderVisible: false },
      leftPriceScale: { visible: false },
      timeScale: { borderVisible: false, timeVisible: false },
      watermark: { visible: false },
    });
    const watchlist = chart.addLineSeries({
      color: "#E6EAF0",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    const benchmark = chart.addLineSeries({
      color: "#7D8DA3",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    watchlist.setData(data.map((point) => ({ time: point.time, value: point.watchlist })));
    benchmark.setData(data.map((point) => ({ time: point.time, value: point.benchmark })));
    chart.timeScale().fitContent();
    chartRef.current = chart;
    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data]);

  const cursorIndex = Math.max(
    0,
    data.findIndex((point) => point.time === cursorDate),
  );
  const cursorFraction = data.length > 1 ? cursorIndex / (data.length - 1) : 0;

  return (
    <figure className="border border-hairline bg-panel">
      <div ref={containerRef} className="relative h-[260px]">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-px bg-flare"
          style={{ left: `${cursorFraction * 100}%` }}
        />
      </div>
      <figcaption className="border-t border-hairline px-4 py-3 text-micro text-slate">
        Your equal-weight list and Nifty 50, rebased to <span className="num">100</span>.
        Adjusted prices, as of {asOf ?? "latest exchange close"}.
      </figcaption>
    </figure>
  );
}
