import { useEffect, useRef } from "react";
import { createChart, LineStyle } from "lightweight-charts";

const SERIES = [
  { time: "2026-07-27", open: 2860, high: 2910, low: 2838, close: 2898 },
  { time: "2026-07-28", open: 2898, high: 2940, low: 2880, close: 2922 },
  { time: "2026-07-29", open: 2922, high: 2950, low: 2892, close: 2904 },
  { time: "2026-07-30", open: 2904, high: 2930, low: 2870, close: 2888 },
  { time: "2026-07-31", open: 2888, high: 2920, low: 2862, close: 2912 },
  { time: "2026-08-03", open: 2912, high: 2968, low: 2900, close: 2951 },
  { time: "2026-08-04", open: 2951, high: 2974, low: 2926, close: 2940 },
  { time: "2026-08-05", open: 2940, high: 2960, low: 2906, close: 2928 },
  { time: "2026-08-06", open: 2928, high: 2962, low: 2918, close: 2958 },
  { time: "2026-08-07", open: 2958, high: 2978, low: 2936, close: 2942 },
  { time: "2026-08-10", open: 2942, high: 2960, low: 2904, close: 2917 },
  { time: "2026-08-11", open: 2917, high: 2950, low: 2908, close: 2938 },
  { time: "2026-08-12", open: 2938, high: 2968, low: 2920, close: 2942 },
];

export default function SymbolChart({ asTraded = false, cursorDate = "2026-08-12" }) {
  const containerRef = useRef(null);
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 420,
      layout: { background: { color: "#101927" }, textColor: "#7D8DA3" },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(30, 42, 61, 0.4)", style: LineStyle.Solid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: false },
      watermark: { visible: false },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#2FCE8A",
      downColor: "#FF5A52",
      borderVisible: false,
      wickUpColor: "#2FCE8A",
      wickDownColor: "#FF5A52",
    });
    const multiplier = asTraded ? 1.02 : 1;
    series.setData(SERIES.map((point) => ({
      ...point,
      open: point.open * multiplier,
      high: point.high * multiplier,
      low: point.low * multiplier,
      close: point.close * multiplier,
    })));
    series.setMarkers([
      { time: "2026-08-03", position: "aboveBar", color: "#E6EAF0", shape: "circle", text: "engine" },
      { time: "2026-08-10", position: "belowBar", color: "#E6EAF0", shape: "circle", text: "engine" },
    ]);
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [asTraded]);

  const cursorIndex = Math.max(0, SERIES.findIndex((point) => point.time === cursorDate));
  const cursorLeft = `${(cursorIndex / (SERIES.length - 1)) * 100}%`;
  return (
    <figure className="border border-hairline bg-panel">
      <div ref={containerRef} className="relative h-[420px]">
        <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px" style={{ left: cursorLeft, backgroundColor: "#F0A500" }} />
      </div>
      <figcaption className="border-t border-hairline px-4 py-3 text-micro text-slate">
        {asTraded ? "As-traded series." : "Adjusted series."} Engine marks show dates where the statistical model fired.
      </figcaption>
    </figure>
  );
}
