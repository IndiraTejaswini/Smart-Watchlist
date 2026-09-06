import { FRESHNESS_DISPLAY } from "../../lib/constants.js";
import { formatIsoDate } from "../../lib/format.js";
import { useMarketStatus } from "../../lib/api/queries.js";
import FreshnessDot from "../FreshnessDot.jsx";

/**
 * StatusStrip — §4. Fixed to the bottom, always visible, always honest.
 *
 * "Almost no consumer product tells you the age and confidence of what it is
 * showing you." That is the whole argument for this component, and it is why it
 * is 28px of permanent chrome rather than a tooltip on an info icon.
 *
 * R5 is enforced here and in Num together: when the feed state resolves to a
 * stale tone this strip says so in plain English, and every price on screen
 * drops to --stale at the same moment because both read the same table.
 */
export default function StatusStrip() {
  const { data, isPending, isError } = useMarketStatus();

  if (isPending) {
    // The skeleton matches the loaded geometry exactly (§7) — same height, same
    // padding — so nothing shifts when the first status lands.
    return (
      <Strip>
        <span className="text-stale">Checking feed state</span>
      </Strip>
    );
  }

  if (isError || !data) {
    return (
      <Strip>
        <FreshnessDot tone="stale" label="Cannot reach the server — nothing on this screen is live" />
      </Strip>
    );
  }

  const display = FRESHNESS_DISPLAY[data.feed_state] ?? FRESHNESS_DISPLAY.NO_DATA;
  const quality = data.data_quality;
  const deliveryFinal =
    quality.delivery_final_through &&
    quality.delivery_final_through === quality.last_bhavcopy_date;

  return (
    <Strip>
      <FreshnessDot tone={display.tone} label={display.label} />
      <Divider />
      <span className="text-slate">
        Bhavcopy{" "}
        <span className="num text-chalk">
          {formatIsoDate(quality.last_bhavcopy_date)}
        </span>{" "}
        final
      </span>
      <Divider />
      <span className="text-slate">
        {deliveryFinal
          ? "Delivery final"
          : `Delivery final through ${formatIsoDate(quality.delivery_final_through)}`}
      </span>
      {data.banner ? (
        <>
          <Divider />
          <span className="text-provis">{data.banner}</span>
        </>
      ) : null}
    </Strip>
  );
}

function Strip({ children }) {
  return (
    <footer
      className="flex h-strip shrink-0 items-center gap-3 border-t border-hairline bg-abyss px-5 text-micro"
      aria-live="polite"
    >
      {children}
    </footer>
  );
}

function Divider() {
  return <span aria-hidden="true" className="text-hairline">·</span>;
}
