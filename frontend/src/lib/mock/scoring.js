import {
  CLAMP_DELIVERY,
  CLAMP_SCAR,
  CLAMP_TURNOVER,
  CLASSIFICATION_MULTIPLIERS,
  DECAY_TAU_SESSIONS,
  PERSONAL_CAP,
  PERSONAL_MULTIPLIERS,
  W_DELIVERY,
  W_EXTREME,
  W_SCAR,
  W_TURNOVER,
} from "../constants.js";

/**
 * scoring.js — FIXTURE GENERATION ONLY. Not application logic.
 *
 * Read this before assuming the frontend scores signals: it does not, and must
 * not. R2 keeps the signal engine pure and server-side, and in production every
 * number the explain panel shows arrives from /api/brief/explain already
 * computed. Nothing outside src/lib/mock imports this file.
 *
 * It exists because of what the explain panel is *for*. §16.2's purpose is that
 * a reader can check the arithmetic live — "why is this ranked second?" — and a
 * fixture whose intermediate values do not actually produce its final score
 * would fail at precisely the moment the panel is supposed to prove rigour. So
 * the mock derives its scores from the §13 formula and the §21 constants rather
 * than stating a plausible-looking number.
 *
 * A consequence worth stating plainly: the score in ARCHITECTURE §16's example
 * (1.42 for TATAMOTORS) is not reproducible from the metrics printed beside it
 * — the §13.1 formula with those inputs cannot exceed about 1.40 even at the
 * personal cap with no decay. The example is illustrative. These fixtures are
 * computed, so they differ from it, and they reconcile.
 */

const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value));

/**
 * §13.1 — the base score. Four weighted, clamped, normalised components.
 * @param {{scar:number, turnover_z:number, delivery_z:number, extreme:boolean}} m
 */
export function baseScore(m) {
  const scar = (W_SCAR * clamp(Math.abs(m.scar), 0, CLAMP_SCAR)) / CLAMP_SCAR;
  const turnover =
    (W_TURNOVER * clamp(Math.max(m.turnover_z, 0), 0, CLAMP_TURNOVER)) / CLAMP_TURNOVER;
  const delivery =
    (W_DELIVERY * clamp(Math.abs(m.delivery_z), 0, CLAMP_DELIVERY)) / CLAMP_DELIVERY;
  const extreme = W_EXTREME * (m.extreme ? 1 : 0);
  return {
    scar,
    turnover,
    delivery,
    extreme,
    total: scar + turnover + delivery + extreme,
  };
}

/** §13.3 — multiplicative, product capped at PERSONAL_CAP. */
export function personalMultiplier(keys) {
  const applied = keys.map((key) => ({ key, ...PERSONAL_MULTIPLIERS[key] }));
  const raw = applied.reduce((acc, m) => acc * m.value, 1);
  return { applied, raw, capped: Math.min(raw, PERSONAL_CAP), cap: PERSONAL_CAP };
}

/** §13.4 — decay in trading sessions, never calendar days. */
export function recencyDecay(ageSessions) {
  return Math.exp(-ageSessions / DECAY_TAU_SESSIONS);
}

/**
 * The whole derivation, kept as one object so the explain panel can render each
 * step rather than only the answer.
 *
 * @param {object} input
 * @param {{scar:number,turnover_z:number,delivery_z:number,extreme:boolean}} input.metrics
 * @param {keyof CLASSIFICATION_MULTIPLIERS} input.classificationKey
 * @param {string[]} input.personalKeys
 * @param {number} input.ageSessions
 */
export function score({ metrics, classificationKey, personalKeys, ageSessions }) {
  const base = baseScore(metrics);
  const classification = CLASSIFICATION_MULTIPLIERS[classificationKey];
  const personal = personalMultiplier(personalKeys);
  const decay = recencyDecay(ageSessions);
  const final = base.total * classification.value * personal.capped * decay;
  return {
    base,
    classification: { key: classificationKey, ...classification },
    personal,
    decay: { ageSessions, tau: DECAY_TAU_SESSIONS, factor: decay },
    final,
  };
}
