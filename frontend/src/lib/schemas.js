import { z } from "zod";
import { FRESHNESS_STATES, SESSION_PHASES } from "./constants.js";

/**
 * schemas.js — Zod, at the API boundary and nowhere else (R8).
 *
 * These describe docs/BUILD_SPEC.md §16 responses. They are validation, not types:
 * their job is to make a contract drift fail loudly at the seam instead of
 * silently producing blank cells four components deep.
 */

export const dataQualitySchema = z.object({
  last_bhavcopy_date: z.string(),
  delivery_final_through: z.string().nullable().optional(),
  symbols_below_liquidity_floor: z.array(z.string()).default([]),
  degraded_baselines: z.array(z.string()).default([]),
  index_0930_source: z.string().nullable().optional(),
});

export const marketStatusSchema = z.object({
  as_of: z.string(),
  session: z.enum([...SESSION_PHASES, "HALTED"]),
  feed_state: z.enum(FRESHNESS_STATES),
  banner: z.string().nullable().default(null),
  data_quality: dataQualitySchema,
});
export const MarketStatusResponse = marketStatusSchema;

export const quoteDeltaPayloadSchema = z.object({
  symbol: z.string(),
  ltp: z.number(),
  chp: z.number().optional(),
  change: z.number().optional(),
  state: z.string().optional(),
  as_of: z.string().optional(),
});
export const quotePayloadSchema = quoteDeltaPayloadSchema;

/** The reading cursor, §16.1 `BriefResponse.cursor`. */
export const cursorSchema = z.object({
  acknowledged_through: z.string(),
  sessions_elapsed: z.number().int().optional(),
  calendar_days_elapsed: z.number().int().optional(),
});

export const meSchema = z.object({
  user: z.object({
    id: z.string(),
    display_name: z.string(),
    initials: z.string(),
    is_demo: z.boolean().default(false),
  }),
  default_watchlist_id: z.string(),
  // The end of the last session this dataset actually has bars for — the
  // frontend hydrates its query cursor from this, not from the browser's
  // clock, so a pre-seeded demo stays populated no matter when it's opened.
  //
  // Optional on purpose. Everything downstream of /api/me — the watchlist id,
  // the Brief, the spine, the Lists page — is unreachable if this response
  // fails to parse, so a field added after the fact must never be able to
  // take the whole app down when it is absent. Without it the cursor simply
  // stays unset and the server falls back to its own anchor.
  as_of: z.string().optional(),
  cursor: cursorSchema,
});

/**
 * The trading calendar behind the cursor spine. `session_type` is the §5.2
 * vocabulary; a MUHURAT day is a real session whose window the exchange
 * notifies separately, so the spine must not assume every session is REGULAR.
 */
export const tradingCalendarSchema = z.object({
  window: z.object({ from: z.string(), to: z.string() }),
  sessions: z.array(
    z.object({
      date: z.string(),
      session_type: z.enum(["REGULAR", "MUHURAT", "HALF_DAY"]),
    }),
  ),
});

export const signalMarksSchema = z.object({
  watchlist_id: z.string(),
  marks: z.array(
    z.object({
      signal_event_id: z.string(),
      session_date: z.string(),
      symbol: z.string(),
      surfaced: z.boolean(),
    }),
  ),
});
/** GET /api/watchlist/:id — the register a live table renders (12.6). */
export const watchlistItemsSchema = z.object({
  items: z.array(
    z.object({
      symbol: z.string(),
      position: z.union([z.string(), z.number()]),
    }),
  ),
});

/**
 * GET /api/watchlist/:id/quotes — each symbol's own latest daily_bars row.
 * Not a live tick: this build has no broker feed to poll against a frozen,
 * pre-seeded dataset, so "final" is the honest freshness for every entry.
 */
export const watchlistQuotesSchema = z.object({
  quotes: z.record(
    z.string(),
    z.object({
      ltp: z.number(),
      change: z.number(),
      chp: z.number(),
      turnover: z.number(),
      delivery: z.number().nullable(),
      as_of_date: z.string(),
      freshness: z.string(),
      state: z.string(),
    }),
  ),
});

export const evalFunnelSchema = z.object({
  evaluated: z.number().int(),
  corporate_action: z.number().int(),
  market_wide: z.number().int(),
  sector_grouped: z.number().int(),
  below_cap: z.number().int(),
  surfaced: z.number().int(),
});
export const evalCasesSchema = z.array(z.object({
  symbol: z.string(),
  event: z.string(),
  naive_change_pct: z.number(),
  system_title: z.string(),
  system_text: z.string(),
}));
export const evalContinuationSchema = z.array(z.object({
  category: z.string(),
  n: z.number().int(),
  mean_ar: z.number(),
  median_ar: z.number(),
  same_direction_pct: z.number(),
}));

// ─── §16.1 BriefResponse ────────────────────────────────────────────────────

export const briefItemSchema = z.object({
  signal_event_id: z.string(),
  symbol: z.string(),
  company_name: z.string(),
  family: z.enum(["PRICE_MOVE", "TURNOVER_SURGE", "DELIVERY_SHIFT"]),
  classification: z.enum([
    "EXPLAINED",
    "UNEXPLAINED",
    "SECTOR_WIDE",
    "MARKET_WIDE",
    "CORPORATE_ACTION",
  ]),
  rank: z.number().int(),
  score: z.number(),
  what: z.string(),
  how_unusual: z.string(),
  cause: z.string(),
  freshness: z.string(),
  metrics: z.object({
    pct_move: z.number(),
    scar: z.number(),
    turnover_z: z.number(),
    delivery_z: z.number(),
    delivery_pct: z.number(),
    mpm_triggered: z.boolean(),
    mpm_threshold_used: z.number(),
  }),
  provisional: z.boolean(),
  revision: z.number().int(),
  was_restated: z.boolean(),
  completeness: z.array(z.string()),
  linked_announcement_ids: z.array(z.number()),
  links: z.object({
    announcement: z.string().nullable(),
    explain: z.string(),
  }),
});

export const briefSchema = z.object({
  generated_at: z.string(),
  cursor: cursorSchema,
  headline: z.string(),
  market_rollup: z.object({
    present: z.boolean(),
    text: z.string(),
    index_change_pct: z.number(),
    symbols_attributed: z.array(z.string()),
  }),
  items: z.array(briefItemSchema),
  sector_groups: z.array(
    z.object({ sector: z.string(), text: z.string(), symbols: z.array(z.string()) }),
  ),
  corporate_action_notices: z.array(
    z.object({
      symbol: z.string(),
      action_type: z.string(),
      ex_date: z.string(),
      text: z.string(),
    }),
  ),
  quiet: z.object({ count: z.number().int(), text: z.string() }),
  budget: z.object({
    candidates_detected: z.number().int(),
    suppressed_corporate_action: z.number().int(),
    rolled_up_market_wide: z.number().int(),
    grouped_sector_wide: z.number().int(),
    below_cap: z.number().int(),
    surfaced: z.number().int(),
    cap: z.number().int(),
  }),
  data_quality: dataQualitySchema,
});
export const BriefResponse = briefSchema;

// ─── §16.2 ExplainResponse ──────────────────────────────────────────────────

export const explainSchema = z.object({
  signal_event_id: z.string(),
  symbol: z.string(),
  session_date: z.string(),
  family: z.string(),
  classification: z.string(),
  rank: z.number().int(),
  final_score: z.number(),
  completeness: z.array(z.string()),
  inputs_hash: z.string(),
  sections: z.array(
    z.object({
      title: z.string(),
      note: z.string().optional(),
      rows: z.array(
        z.object({
          label: z.string(),
          value: z.union([z.number(), z.string(), z.boolean()]),
          format: z.string(),
          note: z.string().optional(),
        }),
      ),
    }),
  ),
  decision_path: z.array(
    z.object({
      step: z.number().int(),
      rule: z.string(),
      test: z.string(),
      evaluated: z.string(),
      taken: z.boolean(),
    }),
  ),
});
