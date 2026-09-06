"""Constants registry — THE LAW.

ARCHITECTURE.md Section 21, implemented verbatim. Nothing numeric appears
anywhere else in the codebase.

Two classes of constant live here:

  [REGULATORY]  Copied from an exchange or regulator document. Never changed,
                never refactored, never "simplified", never moved.
  [TUNED]       Ours. Changed only via the eval harness (ARCHITECTURE.md §18).

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
LOG_TO_SD_FLOOR         = 0.15
DELIVERY_LOGIT_EPS      = 1e-4
DELIVERY_LOGIT_SD_FLOOR = 0.15

# Candidate gates
SAR_CANDIDATE_MIN        = 2.0
TURNOVER_Z_CANDIDATE_MIN = 2.5
DELIVERY_Z_CANDIDATE_MIN = 2.0
SCAR_MIN                 = 2.0

# Classification
MARKET_ATTRIB_RATIO = 0.70
MARKET_SAR_CEILING  = 1.5
SECTOR_MIN_PEERS    = 4
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

# Dedup
REFRACTORY_HOURS      = 24
REFRACTORY_ESCALATION = 0.50

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
POLL_INTERVAL_SECONDS         = 5
SIGNAL_EVAL_INTERVAL_SECONDS  = 30

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

# Eval
EVAL_SYMBOLS = 200
EVAL_DAYS    = 126

# ─── Banned user-facing copy — §17.6, enforced by R12 ───────────────────────
# ONE list. The build-time lint over the copy modules and the runtime check on
# any model-generated text both import this. Matched case-insensitively on word
# boundaries; EXCLAMATION_MARK is matched as a literal character.
BANNED_COPY_TERMS = (
    "buy",
    "sell",
    "should",
    "consider",
    "opportunity",
    "target price",
    "undervalued",
    "overvalued",
    "bullish",
    "bearish",
    "act now",
    "don't miss",
    "hurry",
)
BANNED_COPY_CHARS = ("!",)
