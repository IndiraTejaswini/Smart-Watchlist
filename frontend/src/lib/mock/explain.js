import { SCORED_ITEMS } from "./brief.js";
import {
  CLAMP_DELIVERY,
  CLAMP_SCAR,
  CLAMP_TURNOVER,
  DELIVERY_Z_CANDIDATE_MIN,
  MARKET_ATTRIB_RATIO,
  MARKET_SAR_CEILING,
  SAR_CANDIDATE_MIN,
  SCAR_MIN,
  SECTOR_MIN_PEERS,
  TURNOVER_Z_CANDIDATE_MIN,
  W_DELIVERY,
  W_EXTREME,
  W_SCAR,
  W_TURNOVER,
} from "../constants.js";

/**
 * explain.js — GET /api/brief/explain/{signal_event_id}
 *
 * §16.2: "the full FactBundle inputs, every intermediate value, the MPM tier
 * and threshold used, the classification decision path with the branch taken at
 * each step, every weight and multiplier, the final score, the completeness set,
 * and the inputs_hash."
 *
 * Its stated purpose is to be the live answer to "why is this ranked second?",
 * which means the numbers have to survive being read aloud. Everything here is
 * computed from the same fixture the brief is built from, so the base score on
 * screen really is the weighted sum of the components above it, and the final
 * score really is that times the multipliers beside it.
 *
 * The payload is shaped as titled sections of labelled rows so the panel can
 * render a definition list generically. `format` tells it how to set each value
 * — a z-score and a rupee turnover should not be printed the same way — without
 * the panel needing to know what any particular field means.
 */

const num = (label, value, format = "number", note) => ({ label, value, format, note });

/** djb2, hex. A real hash of the real inputs, not a decorative constant. */
function hashInputs(payload) {
  const text = JSON.stringify(payload);
  let h = 5381;
  for (let i = 0; i < text.length; i += 1) {
    h = ((h << 5) + h + text.charCodeAt(i)) >>> 0;
  }
  let h2 = 52711;
  for (let i = text.length - 1; i >= 0; i -= 1) {
    h2 = ((h2 << 5) + h2 + text.charCodeAt(i)) >>> 0;
  }
  return (h.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0")).slice(0, 16);
}

export function mockExplain(signalEventId) {
  const item = SCORED_ITEMS.find(
    (i) => `se_${i.symbol.toLowerCase()}_${i.session_date.replace(/-/g, "")}` === signalEventId,
  );
  if (!item) {
    const error = new Error(`No signal ${signalEventId}`);
    error.status = 404;
    error.title = "No such signal";
    error.detail = `There is no signal event with id ${signalEventId}.`;
    throw error;
  }

  const { model, metrics, abnormal, derivation } = item;
  const d = derivation;

  return {
    signal_event_id: signalEventId,
    symbol: item.symbol,
    session_date: item.session_date,
    family: item.family,
    classification: item.classification,
    rank: item.rank,
    final_score: d.final,
    completeness: item.completeness,
    inputs_hash: hashInputs({ model, metrics, date: item.session_date, symbol: item.symbol }),

    sections: [
      {
        title: "Inputs",
        note: "The FactBundle the engine was handed. Nothing else was available to it.",
        rows: [
          num("Session", item.session_date, "text"),
          num("Window", model.window_sessions, "sessions"),
          num("Return, cumulative", model.r_i_cum, "return"),
          num("Nifty 50 return, cumulative", model.r_m_cum, "return"),
          num("Turnover z", metrics.turnover_z, "z"),
          num("Delivery z", metrics.delivery_z, "z"),
          num("Delivery ratio", metrics.delivery_pct, "ratio"),
          num("New 52-week extreme or band hit", metrics.extreme, "bool"),
        ],
      },
      {
        title: "Market model",
        note: "OLS of the stock on the index over the estimation window, §9.",
        rows: [
          num("Alpha", model.alpha, "coef"),
          num("Beta", model.beta, "coef"),
          num("Residual standard deviation", model.resid_sd, "coef"),
          num("Observations", model.n_obs, "count"),
          num("R squared", model.r2, "coef"),
        ],
      },
      {
        title: "Abnormality",
        note: "Expected return removed, then standardised by the stock's own residual scale.",
        rows: [
          num("Expected return", abnormal.market_component, "return",
            `alpha × ${model.window_sessions} + beta × market return`),
          num("Abnormal return, signal day", abnormal.ar, "return"),
          num("SAR", abnormal.sar, "z", `AR ÷ resid_sd · gate ${SAR_CANDIDATE_MIN}`),
          num("CAR", abnormal.car, "return", "cumulative return − expected return"),
          num("SCAR", abnormal.scar, "z",
            `CAR ÷ (resid_sd × √${model.window_sessions}) · gate ${SCAR_MIN}`),
        ],
      },
      {
        title: "Regulatory gate",
        note: "Material Price Movement framework, NSE/BSE, 21 May 2024, under SEBI LODR Reg 30(11).",
        rows: [
          num("Move", metrics.pct_move, "pct"),
          num("MPM threshold for this price tier", metrics.mpm_threshold_used, "pct_unsigned"),
          num("Cleared the threshold", metrics.mpm_triggered, "bool"),
        ],
      },
      {
        title: "Base score",
        note: "§13.1. Four weighted components, each clamped and normalised to its ceiling.",
        rows: [
          num("SCAR component", d.base.scar, "score",
            `${W_SCAR} × min(|SCAR|, ${CLAMP_SCAR}) ÷ ${CLAMP_SCAR}`),
          num("Turnover component", d.base.turnover, "score",
            `${W_TURNOVER} × min(max(turnover z, 0), ${CLAMP_TURNOVER}) ÷ ${CLAMP_TURNOVER}`),
          num("Delivery component", d.base.delivery, "score",
            `${W_DELIVERY} × min(|delivery z|, ${CLAMP_DELIVERY}) ÷ ${CLAMP_DELIVERY}`),
          num("Extreme component", d.base.extreme, "score",
            `${W_EXTREME} × (1 if a new 52-week extreme or band hit, else 0)`),
          num("Base", d.base.total, "score", "the four components, summed"),
        ],
      },
      {
        title: "Multipliers",
        note: "§13.2–13.4. The personal product is capped; decay is in trading sessions.",
        rows: [
          num(`Classification — ${d.classification.label}`, d.classification.value, "mult",
            d.classification.why),
          ...d.personal.applied.map((m) => num(`Personal — ${m.label}`, m.value, "mult")),
          num("Personal product", d.personal.raw, "mult",
            d.personal.raw > d.personal.cap
              ? `capped at ${d.personal.cap}`
              : `under the cap of ${d.personal.cap}`),
          num("Personal, after the cap", d.personal.capped, "mult"),
          num("Recency decay", d.decay.factor, "mult",
            `exp(−${d.decay.ageSessions} sessions ÷ tau ${d.decay.tau})`),
        ],
      },
      {
        title: "Final score",
        note: "base × classification × personal × decay",
        rows: [
          num("Final", d.final, "score",
            `${d.base.total.toFixed(4)} × ${d.classification.value} × ` +
              `${d.personal.capped.toFixed(2)} × ${d.decay.factor.toFixed(4)}`),
          num("Rank in this brief", item.rank, "count"),
        ],
      },
    ],

    decision_path: buildDecisionPath(item),
  };
}

/**
 * §11 — one classification per candidate, first match wins. Every branch is
 * listed with the values it was evaluated against, including the ones that did
 * not fire: knowing why something was *not* called market-wide is most of the
 * answer to why it was surfaced.
 */
function buildDecisionPath(item) {
  const { model, abnormal } = item;
  const marketComponent = Math.abs(model.beta * model.r_m_cum);
  const ownMove = Math.abs(model.r_i_cum);
  const attribRatio = ownMove === 0 ? 0 : marketComponent / ownMove;

  const isCorpAction = false;
  const isMarketWide =
    attribRatio >= MARKET_ATTRIB_RATIO && Math.abs(abnormal.sar) < MARKET_SAR_CEILING;
  const isSectorWide = false;
  const isExplained = item.classification === "EXPLAINED";

  return [
    {
      step: 1,
      rule: "Corporate action",
      test: "An ex-date for this symbol inside the cursor window",
      evaluated: "No corporate action on this symbol in the window",
      taken: isCorpAction,
    },
    {
      step: 2,
      rule: "Market-wide",
      test: `|beta × market return| ≥ ${MARKET_ATTRIB_RATIO} × |own return| and |SAR| < ${MARKET_SAR_CEILING}`,
      evaluated:
        `attribution ratio ${attribRatio.toFixed(3)} ` +
        `${attribRatio >= MARKET_ATTRIB_RATIO ? "≥" : "<"} ${MARKET_ATTRIB_RATIO}; ` +
        `|SAR| ${Math.abs(abnormal.sar).toFixed(2)} ` +
        `${Math.abs(abnormal.sar) < MARKET_SAR_CEILING ? "<" : "≥"} ${MARKET_SAR_CEILING}`,
      taken: isMarketWide,
    },
    {
      step: 3,
      rule: "Sector-wide",
      test: `At least ${SECTOR_MIN_PEERS} peers, same sign as the sector median, within tolerance`,
      evaluated:
        item.symbol === "SBIN" || item.symbol === "MARUTI"
          ? "Sector peers present; this move is outside the sector tolerance band"
          : "Sector peers present; this move does not track the sector median",
      taken: isSectorWide,
    },
    {
      step: 4,
      rule: isExplained ? "Explained" : "Unexplained",
      test: "A linked announcement whose category is not OTHER",
      evaluated: isExplained
        ? `${item.linked_announcement_ids.length} linked announcement(s): ${item.cause}`
        : "No linked announcement in the window around the move",
      taken: true,
    },
  ];
}

/** Gate values, rendered beside the metrics they admit. §10. */
export const CANDIDATE_GATES = {
  SAR_CANDIDATE_MIN,
  TURNOVER_Z_CANDIDATE_MIN,
  DELIVERY_Z_CANDIDATE_MIN,
  SCAR_MIN,
};
