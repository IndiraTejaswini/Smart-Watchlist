import { SESSION_LABELS } from "../lib/constants.js";

/**
 * SessionBadge — which phase the exchange is in.
 *
 * Sentence case, not all-caps (§2.2). No fill, no pill, no shadow: a hairline
 * outline and the machined 3px edge, so it reads as a state annotation rather
 * than as a button someone forgot to wire up.
 *
 * @param {object} props
 * @param {"PRE_OPEN"|"REGULAR"|"POST_CLOSE"|"CLOSED"|"HALTED"} props.session
 * @param {string} [props.className]
 */
export default function SessionBadge({ session, className = "" }) {
  const label = SESSION_LABELS[session] ?? "Unknown";
  return (
    <span
      className={`inline-block rounded-edge border border-hairline px-1.5 py-px text-micro text-slate ${className}`.trim()}
    >
      {label}
    </span>
  );
}
