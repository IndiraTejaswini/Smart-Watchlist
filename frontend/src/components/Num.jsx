import { FRESHNESS_DISPLAY } from "../lib/constants.js";
import {
  formatPercent,
  formatPrice,
  formatRatioPct,
  formatSigned,
  formatTurnover,
  formatZ,
} from "../lib/format.js";
import { useAllowsDirectionColour } from "../lib/register.jsx";

/**
 * Num — every numeral in the application goes through this component.
 *
 * It exists for three reasons, in order of importance:
 *
 * 1. §2.2 makes JetBrains Mono with tabular figures non-negotiable. Routing all
 *    numbers through one component means that rule cannot be forgotten, and a
 *    table of live prices never jitters on a tick.
 * 2. Colour policy is a property of the *surface*, not of the call site. `Num`
 *    resolves its own tone against the register context, so directional green
 *    and red simply do not appear on the Brief even if someone asks for them.
 * 3. R5 — never render a stale price as though it were live. A freshness state
 *    that means "do not trust this" overrides every other colour decision,
 *    including a directional one.
 *
 * @param {object} props
 * @param {number|null|undefined} props.value
 * @param {"price"|"percent"|"signed"|"turnover"|"z"|"ratio"|"plain"} [props.kind]
 * @param {number} [props.dp] decimal places; per-kind default when omitted
 * @param {"neutral"|"direction"|"confidence"} [props.tone]
 * @param {"final"|"provis"|"stale"} [props.confidence] required when tone="confidence"
 * @param {string} [props.freshness] a §14.2 freshness state; may force --stale
 * @param {string} [props.prefix] e.g. "₹"
 * @param {string} [props.suffix] e.g. "×"
 * @param {string} [props.className]
 * @param {string} [props.title]
 */
export default function Num({
  value,
  kind = "plain",
  dp,
  tone = "neutral",
  confidence,
  freshness,
  prefix,
  suffix,
  className = "",
  title,
  ...rest
}) {
  const allowsDirection = useAllowsDirectionColour();
  const text = render(value, kind, dp);
  const colour = resolveColour({
    value,
    tone,
    confidence,
    freshness,
    allowsDirection,
  });

  return (
    <span className={`num ${colour} ${className}`.trim()} title={title} {...rest}>
      {prefix}
      {text}
      {suffix}
    </span>
  );
}

function render(value, kind, dp) {
  switch (kind) {
    case "price":
      return formatPrice(value, dp ?? 2);
    case "percent":
      return formatPercent(value, dp ?? 2);
    case "signed":
      return formatSigned(value, dp ?? 2);
    case "turnover":
      return formatTurnover(value);
    case "z":
      return formatZ(value);
    case "ratio":
      return formatRatioPct(value, dp ?? 0);
    case "plain":
    default:
      return formatPrice(value, dp ?? 0);
  }
}

/**
 * The whole colour policy, in one readable block.
 *
 * Order is deliberate: freshness wins over everything, because a number nobody
 * should trust must never be dressed in a confident colour. Then the register
 * veto. Then the requested tone.
 */
function resolveColour({ value, tone, confidence, freshness, allowsDirection }) {
  if (freshness) {
    const display = FRESHNESS_DISPLAY[freshness];
    if (display && display.tone === "stale") return "text-stale";
  }

  if (tone === "confidence") {
    if (confidence === "final") return "text-final";
    if (confidence === "provis") return "text-provis";
    if (confidence === "stale") return "text-stale";
    return "text-chalk";
  }

  if (tone === "direction") {
    // §2.1 — green and red are forbidden on the Brief. The Dispatch register
    // carries direction with a signed number and a magnitude bar instead, so a
    // directional request there resolves to neutral rather than throwing: the
    // signed number is still correct and still legible, it simply is not hued.
    if (!allowsDirection) return "text-chalk";
    if (value > 0) return "text-up";
    if (value < 0) return "text-down";
    return "text-slate";
  }

  return "";
}
