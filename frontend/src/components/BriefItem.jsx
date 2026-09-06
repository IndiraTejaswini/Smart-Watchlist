import Num from "./Num.jsx";
import MagnitudeBar from "./MagnitudeBar.jsx";
import FreshnessDot from "./FreshnessDot.jsx";
import Prose from "./Prose.jsx";

/**
 * BriefItem — FRONTEND_SPEC §5.4. One ranked entry in the dispatch.
 *
 * No card. A hairline rule above and below is the only separation, which is
 * the point: a card gives equal visual weight to unequal items, and this
 * screen's whole argument is that the items are not equal — they are ranked.
 *
 * The header carries the one number allowed any visual weight: the move
 * itself, in mono, beside a bar that says which side of zero it is on. §13.6's
 * three-part copy — what moved, how unusual, whether there is a cause — reads
 * as one flowing paragraph rather than three separate lines, because in
 * practice they are one thought: "it moved this much, that's unusual for it,
 * and here is why." Splitting them would manufacture structure the sentence
 * does not need.
 *
 * Classification is never printed as a label. §11's own instruction for
 * DELIVERY_SHIFT — "describe, do not label" — is applied to every
 * classification here: EXPLAINED and UNEXPLAINED already show up as "Q2
 * results, filed Tuesday" versus "No filing found" in the cause sentence. A
 * badge reading "UNEXPLAINED" next to that sentence would say the same thing
 * twice, once honestly and once like a system category.
 */

/**
 * @param {import("../lib/schemas.js").briefItemSchema._type} props.item
 * @param {(item: object) => void} props.onExplain
 */
export default function BriefItem({ item, onExplain }) {
  const confidence = item.provisional ? "provis" : "final";

  return (
    <article className="border-t border-hairline py-8 first:border-t-0">
      <header className="flex items-baseline justify-between gap-6">
        <h3 className="num text-section text-chalk">{item.symbol}</h3>
        <div className="flex items-center gap-3">
          <Num
            value={item.metrics.pct_move}
            kind="percent"
            dp={1}
            tone="direction"
            className="text-section"
          />
          <MagnitudeBar value={item.metrics.pct_move} />
        </div>
      </header>
      <p className="mt-0.5 text-dense text-slate">{item.company_name}</p>

      <Prose
        text={`${item.what} ${item.how_unusual} ${item.cause}`}
        className="mt-4 max-w-measure font-prose text-read text-chalk"
      />

      <div className="mt-5 flex items-center justify-between">
        <FreshnessDot tone={confidence} label={<Prose as="span" text={item.freshness} />} />
        <button
          type="button"
          onClick={() => onExplain(item.signal_event_id)}
          className="rounded-edge text-micro text-slate underline decoration-hairline underline-offset-4 hover:text-chalk"
        >
          why this?
        </button>
      </div>
    </article>
  );
}
