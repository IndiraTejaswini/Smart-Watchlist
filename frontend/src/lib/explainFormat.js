import { formatPercent, formatPrice, formatRatioPct, formatSigned, formatZ } from "./format.js";

/**
 * explainFormat.js — how one ExplainPanel row renders its value.
 *
 * The explain endpoint tags each row with a `format` rather than leaving the
 * panel to guess from the value's type: a z-score, a rupee-free ratio and a
 * multiplier are all plain numbers in JavaScript, and rendering "2.81" where
 * "2.81σ" or "2.81×" is meant would misstate exactly the kind of number this
 * panel exists to get right.
 */
export function formatExplainValue(value, format) {
  switch (format) {
    case "bool":
      return value ? "Yes" : "No";
    case "text":
      return String(value);
    case "sessions":
      return `${value} ${value === 1 ? "session" : "sessions"}`;
    case "count":
      return String(value);
    case "z":
      return `${formatZ(value)}σ`;
    case "ratio":
      return formatRatioPct(value, 0);
    case "pct":
      // A signed move, e.g. metrics.pct_move.
      return formatPercent(value, 1);
    case "pct_unsigned":
      // A magnitude with no direction of its own, e.g. the MPM threshold tier.
      return `${formatPrice(value, 1)}%`;
    case "return":
      // A cumulative or expected return, stored as a fraction (0.072 = 7.2%).
      return formatPercent(value * 100, 2);
    case "coef":
      return formatSigned(value, 4);
    case "mult":
      return `${Number(value).toFixed(2)}×`;
    case "score":
      return Number(value).toFixed(4);
    default:
      return String(value);
  }
}
