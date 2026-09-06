import Num from "./Num.jsx";

const DEFAULTS = [
  { name: "NIFTY 50", value: 24812.3, change: -1.84, points: [8, 5, 7, 3, 6, 4, 6] },
  { name: "NIFTY BANK", value: 52104.85, change: -2.1, points: [6, 8, 5, 7, 3, 6, 4] },
  { name: "NIFTY MIDCAP 150", value: 21338.9, change: -0.92, points: [7, 6, 8, 5, 7, 4, 3] },
];

function Sparkline({ points }) {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 60;
      const y = 17 - ((point - min) / (max - min || 1)) * 14;
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
  return (
    <svg width="60" height="18" viewBox="0 0 60 18" aria-hidden="true">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.25" />
    </svg>
  );
}

export default function BenchmarkCards({ cards = DEFAULTS }) {
  return (
    <section className="grid grid-cols-1 border-y border-hairline sm:grid-cols-3">
      {cards.map((card) => (
        <article key={card.name} className="border-b border-hairline px-4 py-4 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
          <h2 className="num text-ui text-slate">{card.name}</h2>
          <Num value={card.value} kind="price" dp={2} className="mt-2 block text-section text-chalk" />
          <div className="mt-1 flex items-center gap-3">
            <Num value={card.change} kind="percent" dp={2} tone="direction" />
            <span className={card.change < 0 ? "text-down" : "text-up"}>
              <Sparkline points={card.points} />
            </span>
          </div>
        </article>
      ))}
    </section>
  );
}
