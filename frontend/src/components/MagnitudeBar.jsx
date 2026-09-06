/**
 * MagnitudeBar — FRONTEND_SPEC §5.4. Direction by geometry, not by hue.
 *
 * The Brief is the one surface in the app that may not use --up or --down: §2.1
 * reserves green and red for the Terminal, and colour on the Dispatch means
 * data confidence, never direction. So a move is drawn as a bar extending left
 * or right of a centre rule — a negative number's bar grows leftward, a
 * positive one's rightward — with the signed number doing the rest of the work.
 * Nothing here reads register state itself; it is simply never given a hue.
 *
 * Magnitude is scaled against `scaleMax`, not against the other items on the
 * page, so one item's bar is comparable across two different briefs — a
 * consistent yardstick is what makes "how big is this, really" answerable at a
 * glance instead of only relative to whatever else happened to surface today.
 */

const DEFAULT_SCALE_MAX = 10; // percent. A single-session MPM tier is 3-5%; a
// multi-session move like TATAMOTORS's 7.2% should not already paint the bar.

/**
 * @param {object} props
 * @param {number} props.value signed, in percent
 * @param {number} [props.scaleMax]
 * @param {string} [props.className]
 */
export default function MagnitudeBar({ value, scaleMax = DEFAULT_SCALE_MAX, className = "" }) {
  const fraction = Math.min(Math.abs(value) / scaleMax, 1);
  const negative = value < 0;

  return (
    <span
      className={`relative inline-block h-3 w-24 shrink-0 align-middle ${className}`.trim()}
      role="img"
      aria-label={`Magnitude bar, ${negative ? "left" : "right"} of centre`}
    >
      {/* The centre rule. Half-height so the bar reads as extending from it
          rather than as a bracket around it. */}
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-hairline"
      />
      <span
        aria-hidden="true"
        className={`absolute inset-y-0 bg-chalk/70 ${negative ? "right-1/2" : "left-1/2"}`}
        style={{ width: `${fraction * 50}%` }}
      />
    </span>
  );
}
