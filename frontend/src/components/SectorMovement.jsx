import Num from "./Num.jsx";

const SECTORS = [
  ["IT", -3.9],
  ["Banking", -2.4],
  ["Auto", -1.1],
  ["FMCG", 0.3],
  ["Pharma", 0.8],
];

export default function SectorMovement() {
  return (
    <section className="border-t border-hairline py-6 md:pl-8">
      <h2 className="text-ui text-chalk">Where the movement was</h2>
      <div className="mt-5 space-y-3">
        {SECTORS.map(([sector, change]) => (
          <div key={sector} className="grid grid-cols-[5rem_1fr_auto] items-center gap-3 text-micro">
            <span className="text-slate">{sector}</span>
            <span className="h-1 bg-hairline">
              <span className={change < 0 ? "block h-full bg-down" : "block h-full bg-up"} style={{ width: `${Math.max(10, Math.abs(change) * 18)}%` }} />
            </span>
            <Num value={change} kind="percent" dp={1} tone="direction" />
          </div>
        ))}
      </div>
    </section>
  );
}
