"""Constants registry — THE LAW.

docs/BUILD_SPEC.md Section 21, implemented verbatim. Nothing numeric appears
anywhere else in the codebase.

Two classes of constant live here:

  [REGULATORY]  Copied from an exchange or regulator document. Never changed,
                never refactored, never "simplified", never moved.
  [TUNED]       Ours. Changed only via the eval harness (docs/BUILD_SPEC.md §18).

If you need a number that is not in this file, STOP and ask the human. Do not
invent one. See BUILD_PLAN.md rule R1.
"""

# ─── [REGULATORY] — NEVER CHANGE ────────────────────────────────────────────
# Framework on Material Price Movement (Equity Cash Markets), NSE/BSE,
# 21 May 2024, under SEBI LODR Reg 30(11).
MPM_TIER_THRESHOLDS = ((100.00, 5.0), (200.00, 4.0), (float("inf"), 3.0))
MPM_INDEX_ADJUST_MIN_PCT = 1.0
MPM_INDEX_SNAPSHOT_TIME  = "09:30"
MPM_INTRADAY_USES_INDEX  = False

# SEBI LODR Reg 30(6) disclosure timelines
REG30_BOARD_MEETING_MINUTES = 30
REG30_INTERNAL_EVENT_HOURS  = 12
REG30_EXTERNAL_EVENT_HOURS  = 24

# NSE/BSE index-based market-wide circuit breaker stages
MARKET_CIRCUIT_STAGES_PCT = (10.0, 15.0, 20.0)

# Session defaults, IST (trading_calendar overrides per date)
SESSION_PRE_OPEN_START = "09:00"
SESSION_OPEN           = "09:15"
SESSION_CLOSE          = "15:30"

# ─── [TUNED] — ours; change only via the eval harness ───────────────────────
CANONICAL_FLOAT_DP = 8

# Market model
BETA_WINDOW_DAYS = 120
BETA_GAP_DAYS    = 5
BETA_MIN_OBS     = 60
BETA_MIN, BETA_MAX = 0.0, 3.0
RESID_SD_FLOOR   = 0.004
WINSOR_PCT       = 0.01

# Rolling baselines
VOL_WINDOW_DAYS      = 20
DELIVERY_WINDOW_DAYS = 20
EXTREME_WINDOW_DAYS  = 252
BASELINE_MIN_SHORT_OBS  = 10
LOG_TO_SD_FLOOR         = 0.15
DELIVERY_LOGIT_EPS      = 1e-4
DELIVERY_LOGIT_SD_FLOOR = 0.15

# Candidate gates
SAR_CANDIDATE_MIN        = 2.0
TURNOVER_Z_CANDIDATE_MIN = 2.5
DELIVERY_Z_CANDIDATE_MIN = 2.0
SCAR_MIN                 = 2.0
EXTREME_PROXIMITY_PCT    = 1.0  # within N% of the 52-week high/low

# Classification
MARKET_ATTRIB_RATIO = 0.70
MARKET_SAR_CEILING  = 1.5
MARKET_WIDE_BENCHMARK_MOVE_MIN = 0.020
MARKET_WIDE_MIN_SYMBOLS        = 3
SECTOR_MIN_PEERS    = 3  # BUILD_PLAN 6.3 accept: "≥3 peers group into one line"
SECTOR_TOLERANCE_SD = 1.0
SUPPRESS_TURNOVER_FLOOR    = 8_000_000     # ₹80 lakh   — hysteresis low
ACTIVATE_TURNOVER_FLOOR    = 12_000_000    # ₹1.2 crore — hysteresis high
EX_DATE_OPEN_PAUSE_MINUTES = 15

# Corporate actions
CA_VERIFY_TOLERANCE     = 0.08
CA_INFER_SNAP_TOLERANCE = 0.02
SUMMARY_MAX_CHARS       = 180
CA_CLEAN_FACTORS = (      # standard bonus ratios and face-value splits
    0.1, 0.125, 1/6, 0.2, 0.25, 1/3, 0.4, 0.5, 0.6, 0.625,
    2/3, 0.7, 0.75, 0.8, 5/6, 2.0, 5.0, 10.0,
)

# Announcements
ANNOUNCEMENT_TAIL_MINUTES = 180
ANNOUNCEMENT_POLL_SECONDS = 180

# Dedup — BUILD_PLAN 5.5: "a three-day slide produces one item; a fourth day
# 60% larger re-surfaces"
REFRACTORY_HOURS          = 24
REFRACTORY_WINDOW_SESSIONS = 3
REFRACTORY_ESCALATION     = 0.60
REFRACTORY_MEMORY_TTL_DAYS = 5

# Ranking
W_SCAR, W_TURNOVER, W_DELIVERY, W_EXTREME = 0.45, 0.25, 0.20, 0.10
MULT_EXPLAINED_A   = 1.35
MULT_EXPLAINED_B   = 1.15
MULT_UNEXPLAINED   = 1.00
MULT_SECTOR_WIDE   = 0.55
MULT_MARKET_WIDE   = 0.25
MULT_CORP_ACTION   = 0.00
MULT_HOLDING       = 1.35
MULT_LEVEL_SET     = 1.30
MULT_LEVEL_CROSSED = 1.80
MULT_PINNED        = 1.20
MULT_RECENT_ADD    = 1.15
MULT_NEVER_OPENED  = 1.10
PERSONAL_CAP       = 2.00
DECAY_TAU_SESSIONS = 5.0

# The budget — N3
BRIEF_MAX_ITEMS         = 5
BRIEF_CACHE_TTL_SECONDS = 60

# Freshness (seconds)
FEED_HEARTBEAT_MAX_S    = 10
DELAYED_S               = 15
BAND_LOCK_MIN_S         = 60
STALE_THIN_S            = 300
MARKET_HALT_SILENT_FRAC = 0.90
MARKET_HALT_MIN_S       = 60
BAND_PROXIMITY_PCT      = 0.001

# Realtime
CONFLATION_INTERVAL_MS        = 400
WS_QUEUE_MAX                  = 500
WS_MAX_SUBSCRIPTIONS_PER_CONN = 60
WS_SLOW_CLIENT_TIMEOUT_S       = 30.0
WS_HEARTBEAT_INTERVAL_S        = 15.0
POLL_INTERVAL_SECONDS         = 5
SIGNAL_EVAL_INTERVAL_SECONDS  = 30

# Freshness state machine timing (milliseconds) — §14.2 waterfall
FRESHNESS_LIVE_MAX_AGE_MS    = 5_000
FRESHNESS_FLOW_MAX_AGE_MS    = 90_000
FRESHNESS_THIN_SILENCE_MS    = 90_000
FRESHNESS_ANCHOR_SILENCE_MS  = 15_000
FRESHNESS_SIMPLE_STALE_MAX_AGE_MS = 60_000  # crud/quotes.py's 3-state variant
BENCHMARK_ANCHOR_SYMBOL      = "NIFTY 50"

# Redis Streams tick transport
STREAM_TICKS_KEY               = "stream:market:ticks"
STREAM_TICKS_DLQ_KEY           = "stream:market:ticks:dlq"
STREAM_TICKS_MAXLEN            = 100_000
STREAM_CONSUMER_BATCH_SIZE     = 100
STREAM_CONSUMER_BLOCK_MS       = 2_000
STREAM_CLAIM_MIN_IDLE_TIME_MS  = 5_000
STREAM_MAX_DELIVERY_ATTEMPTS   = 3

# Ingest
NSE_MAX_ATTEMPTS       = 5
NSE_BREAKER_FAILURES   = 3
NSE_BREAKER_COOLDOWN_S = 300
ROW_COUNT_DEVIATION    = 0.20
ACTIVE_ROW_FLOOR_FRAC  = 0.98
QUARANTINE_ABORT_FRAC  = 0.02

# State
POSITION_KEY_MAX_LEN    = 32
IDEMPOTENCY_TTL_SECONDS = 86_400
SIGNAL_RETENTION_DAYS   = 90

# Infra
DB_CONNECT_TIMEOUT_S = 5

# Ingest transport mechanics — §6.3. Not judgment thresholds, but still numbers,
# so R1 applies: tuned only here, never re-invented at a call site.
NSE_REQUEST_TIMEOUT_S      = 30.0
NSE_BACKOFF_BASE_S         = 1.5
NSE_BACKOFF_MAX_S          = 60.0
NSE_INTER_REQUEST_DELAY_S  = 0.8
NSE_COOKIE_MAX_AGE_S       = 600.0
VENDOR_REQUEST_DELAY_S     = 0.35
VENDOR_TIMEOUT_S           = 30.0
VENDOR_CHECKPOINT_EVERY    = 100

# Fact bundle cache — §5.1
FACT_BUNDLE_COLD_TTL_SECONDS = 86_400

# Watchlist fractional-index rebalancing — §7.3/7.4
WATCHLIST_REBALANCE_LOCK_TTL_SECONDS = 60

# Eval-endpoint pagination (unparsed-actions listing)
EVAL_UNPARSED_DEFAULT_LIMIT = 200
EVAL_UNPARSED_MAX_LIMIT     = 1_000

# Bhavcopy row-count deviation check — §6.2
BHAVCOPY_ROW_COUNT_MEDIAN_WINDOW = 5

# Trading calendar — §1.2: history window plus this many days forward
CALENDAR_FORWARD_DAYS = 90

# Corporate-actions ingest paging window
CA_INGEST_CHUNK_DAYS = 60

# Coverage report — number of example strings shown per unparsed bucket
COVERAGE_EXAMPLE_LIMIT = 15

# EOD retry/escalation — §2.5: four polls, escalate at 20:30 IST
ESCALATION_MAX_POLL_ATTEMPTS = 4
ESCALATION_HOUR = 20
ESCALATION_MINUTE = 30

# Candidate universe — §2.1 scope: NSE cash equities only. The bhavcopy also
# carries ETFs, which are not in the instruments master; without this filter
# `pick_universe` selects on raw turnover and the money-market ETFs
# (LIQUIDBEES, LIQUIDCASE) dominate it, then escape sector rollup because they
# carry no sector. Series per NSE: EQ rolling settlement, BE trade-to-trade,
# BZ surveillance.
EQUITY_SERIES = ("EQ", "BE", "BZ")

# Eval
EVAL_SYMBOLS = 200
EVAL_DAYS    = 126

# ─── Banned user-facing copy — §17.6, enforced by R12 ───────────────────────
# ONE list. The build-time lint over the copy modules and the runtime check on
# any model-generated text both import this. Matched case-insensitively on word
# boundaries; EXCLAMATION_MARK is matched as a literal character. Phrases
# (more than one word) are matched as substrings on normalised whitespace;
# everything else is matched as a whole word.
BANNED_COPY_TERMS = (
    "buy",
    "sell",
    "should",
    "must",
    "consider",
    "opportunity",
    "opportunities",
    "target",
    "target price",
    "undervalued",
    "overvalued",
    "bullish",
    "bearish",
    "act now",
    "don't miss",
    "hurry",
    "recommend",
    "attractive",
    "accumulate",
    "avoid",
    "skyrocket",
    "skyrocketed",
    "skyrocketing",
    "plunge",
    "plunged",
    "plunging",
    "soar",
    "soared",
    "soaring",
    "crash",
    "crashed",
    "crashing",
    "tank",
    "tanked",
    "tanking",
    "dump",
    "dumped",
    "dumping",
    "pump",
    "pumped",
    "pumping",
    "moon",
    "mooning",
    "bloodbath",
    "carnage",
    "rollercoaster",
    "insane",
    "crazy",
    "huge",
    "massive",
    "explosive",
    "wild",
)
BANNED_COPY_CHARS = ("!",)
