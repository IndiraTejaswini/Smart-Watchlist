import Num from "./Num.jsx";
import FreshnessDot from "./FreshnessDot.jsx";

const DEFAULT_SIGNALS = [
  { date: "4 Sep 15:29", symbol: "TATAMOTORS", change: -7.2, classification: "explained" },
  { date: "4 Sep 14:02", symbol: "BHARTIARTL", change: 4.1, classification: "unexplained" },
  { date: "3 Sep 15:30", symbol: "IDEA", change: 0, classification: "corp action" },
];

export default function RecentSignals({ signals = DEFAULT_SIGNALS }) {
  return (
    <section className="border-t border-hairline py-6">
      <h2 className="text-ui text-chalk">Recent signals</h2>
      <div className="mt-3">
        {signals.map((signal) => (
          <div key={`${signal.date}-${signal.symbol}`} className="grid grid-cols-[7rem_1fr_4rem_6rem_auto] items-center gap-3 border-b border-hairline py-3 text-micro">
            <span className="num text-slate">{signal.date}</span>
            <span className="num text-chalk">{signal.symbol}</span>
            <Num value={signal.change} kind="percent" dp={1} tone="direction" />
            <span className="text-slate">{signal.classification}</span>
            <FreshnessDot tone="final" srLabel="Final" />
          </div>
        ))}
      </div>
    </section>
  );
}
