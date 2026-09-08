"""End-to-end batch run of Phase 3/4/5/6 over the real ingested history.

Computes and persists, for every symbol with data:
  - symbol_adjustment_factors      (Phase 3.2)
  - market_model_parameters        (Phase 4.1)
  - turnover_baselines             (Phase 4.2)
  - delivery_baselines             (Phase 4.3)
  - market_extremes_adv            (Phase 4.4)

Then, for the 200 most liquid symbols across the most recent 126 real trading
sessions (BUILD_PLAN Task 13.1's own scope), evaluates the MPM gate and
abnormality layer, generates candidates (Phase 5.4), classifies them
(EXPLAINED / MARKET_WIDE / SECTOR_WIDE / CORPORATE_ACTION, Phase 6), and
persists to `candidates`.

Not a permanent CLI surface — a one-shot orchestration script, run once to
populate the database from the already-ingested cache so the rest of the
product (Brief, explain, eval replay) has real numbers to compute from
instead of an empty table.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import sqlalchemy as sa

sys.path.insert(0, ".")

from app.analytics.abnormality import (  # noqa: E402
    AbnormalityScores,
    compute_abnormal_return,
    compute_sar,
    compute_scar,
)
from app.analytics.announcement_matcher import link_candidate_announcements  # noqa: E402
from app.analytics.delivery import (  # noqa: E402
    estimate_delivery_baselines,
    persist_delivery_baselines,
)
from app.analytics.engine import (  # noqa: E402
    CorporateAction,
    CorporateActionRegistry,
    score_candidates,
)
from app.analytics.extremes import estimate_extremes_and_adv, persist_extremes_and_adv  # noqa: E402
from app.analytics.fact_bundle import (  # noqa: E402
    DailyBarFact,
    DeliveryBaselineFact,
    ExtremesAdvFact,
    FactBundle,
    MarketModelFact,
    TurnoverBaselineFact,
)
from app.analytics.market_model import (  # noqa: E402
    estimate_market_model,
    persist_market_model_parameters,
)
from app.analytics.mpm import evaluate_mpm_gate  # noqa: E402
from app.analytics.turnover import (  # noqa: E402
    estimate_turnover_baselines,
    persist_turnover_baselines,
)
from app.constants import EQUITY_SERIES, EVAL_DAYS, EVAL_SYMBOLS  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.ingest.adjustments import recompute_symbol_adjustment_factors  # noqa: E402
from app.ingest.announcement_ingest import Announcement  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
ENGINE = get_engine()


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


# ─── Phase 3.2 — adjustment factors ─────────────────────────────────────────
def run_adjustment_factors() -> None:
    with ENGINE.connect() as conn:
        symbols = conn.execute(sa.text("SELECT DISTINCT symbol FROM daily_bars")).scalars().all()
    log(f"adjustment factors: {len(symbols)} symbols")
    for i, symbol in enumerate(symbols, 1):
        recompute_symbol_adjustment_factors(ENGINE, symbol)
        if i % 500 == 0:
            log(f"  adjustment factors {i}/{len(symbols)}")


# ─── Phase 4 — baselines ────────────────────────────────────────────────────
def load_wide_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with ENGINE.connect() as conn:
        bars = pd.read_sql(
            sa.text(
                "SELECT b.symbol, b.date, b.turnover, v.adj_close "
                "FROM daily_bars b JOIN v_adjusted_bars v "
                "ON v.symbol = b.symbol AND v.date = b.date"
            ),
            conn,
        )
        delivery = pd.read_sql(
            sa.text(
                "SELECT symbol, date, delivery_pct, traded_qty FROM delivery_stats"
            ),
            conn,
        )
        index_bars = pd.read_sql(
            sa.text(
                "SELECT date, close FROM index_bars WHERE index_symbol = 'Nifty 50' ORDER BY date"
            ),
            conn,
        )
    return bars, delivery, index_bars, bars.copy()


def run_baselines(
    bars: pd.DataFrame, delivery: pd.DataFrame, index_bars: pd.DataFrame
) -> pd.DataFrame:
    log(f"baselines: {bars['symbol'].nunique()} symbols, {bars['date'].nunique()} sessions")
    benchmark_close = index_bars.set_index("date")["close"].astype(float).sort_index()
    benchmark_returns = benchmark_close.pct_change()

    prices = bars.pivot(index="date", columns="symbol", values="adj_close").sort_index()
    stock_returns = prices.pct_change()
    wide_returns = stock_returns.join(benchmark_returns.rename("BENCHMARK"), how="left")
    wide_returns["BENCHMARK"] = wide_returns["BENCHMARK"].fillna(0.0)

    market_params = estimate_market_model(wide_returns)
    with ENGINE.begin() as conn:
        n = persist_market_model_parameters(conn, market_params)
    log(f"  market_model_parameters: {n} rows")

    turnover_wide = bars.pivot(index="date", columns="symbol", values="turnover").sort_index()
    turnover_baselines = estimate_turnover_baselines(turnover_wide)
    with ENGINE.begin() as conn:
        n = persist_turnover_baselines(conn, turnover_baselines)
    log(f"  turnover_baselines: {n} rows")

    delivery_baselines = estimate_delivery_baselines(delivery)
    with ENGINE.begin() as conn:
        n = persist_delivery_baselines(conn, delivery_baselines)
    log(f"  delivery_baselines: {n} rows")

    extremes = estimate_extremes_and_adv(bars)
    with ENGINE.begin() as conn:
        n = persist_extremes_and_adv(conn, extremes)
    log(f"  market_extremes_adv: {n} rows")

    # Real 3-session CAR/SCAR, vectorised — compute_abnormality_bundle's own
    # single-date shortcut cannot express a genuine multi-session window.
    market_by_date_symbol = market_params.set_index(["date", "symbol"])
    alpha = (
        market_by_date_symbol["alpha"].astype(float).unstack("symbol").reindex(wide_returns.index)
    )
    beta = (
        market_by_date_symbol["beta"].astype(float).unstack("symbol").reindex(wide_returns.index)
    )
    expected = alpha.add(beta.mul(wide_returns["BENCHMARK"], axis=0))
    ar = stock_returns.reindex_like(expected).sub(expected)
    car_3d = ar.rolling(3, min_periods=3).sum()
    car_3d = car_3d.stack(future_stack=True).rename("car_3d").reset_index()
    car_3d = car_3d.rename(columns={"level_0": "date", "level_1": "symbol"})
    return car_3d


def run_index_snapshots_lookup() -> pd.DataFrame:
    with ENGINE.connect() as conn:
        return pd.read_sql(
            sa.text(
                "SELECT trading_date AS date, value FROM index_snapshots_0930 "
                "WHERE index_symbol = 'Nifty 50'"
            ),
            conn,
        )


# ─── Phase 5/6 — candidates ─────────────────────────────────────────────────
def load_corporate_action_registry() -> CorporateActionRegistry:
    with ENGINE.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT ca.symbol, ca.ex_date, ca.record_date, ca.action_type, "
                "ca.price_factor, ca.purpose_raw, ca.source, db.close AS cum_close "
                "FROM corporate_actions ca "
                "LEFT JOIN daily_bars db "
                "ON db.symbol = ca.symbol AND db.date = ca.record_date "
                # DISCREPANCY belongs here too: R6 says when uncertain whether
                # a move is a corporate-action artefact, suppress it. A
                # DISCREPANCY *is* that uncertainty (the parsed factor did not
                # match the observed ex-date gap) — showing a signal because
                # our own verification failed is the opposite of fail-safe.
                "WHERE ca.verification IN ('VERIFIED','INFERRED','DISCREPANCY')"
            )
        ).mappings()
        actions = []
        for row in rows:
            cum_date = row["record_date"] or row["ex_date"] - timedelta(days=1)
            factor = Decimal(str(row["price_factor"] or 1))
            as_traded = (
                Decimal(str(row["cum_close"])) if row["cum_close"] is not None else Decimal("0")
            )
            actions.append(
                CorporateAction(
                    symbol=row["symbol"],
                    ex_date=row["ex_date"],
                    cum_date=cum_date,
                    action_type=row["action_type"] or "OTHER",
                    as_traded_cum_close=as_traded,
                    adjusted_prev_close=(as_traded * factor).quantize(Decimal("0.0001")),
                    adjustment_factor=factor,
                    ratio_or_amount=(row["purpose_raw"] or "")[:64],
                    source_url=row["source"] or "",
                )
            )
    return CorporateActionRegistry(actions)


def load_equity_universe() -> set[str]:
    """Symbols the instruments master lists as NSE cash equity — §2.1.

    The bhavcopy is not an equity list: it also carries ETFs, which have no
    row in `instruments` at all. Selecting the universe from it directly puts
    the money-market ETFs at the top on turnover alone, and because they carry
    no sector they cannot be sector-rolled-up either, so one silver move takes
    three slots in a five-item Brief.
    """
    with ENGINE.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT symbol FROM instruments "
                "WHERE is_active AND series IN :series"
            ).bindparams(sa.bindparam("series", value=tuple(EQUITY_SERIES), expanding=True))
        ).scalars().all()
    return set(rows)


def pick_universe(bars: pd.DataFrame, n: int) -> list[str]:
    equities = load_equity_universe()
    eligible = bars[bars["symbol"].isin(equities)]
    mean_turnover = eligible.groupby("symbol")["turnover"].mean().sort_values(ascending=False)
    return list(mean_turnover.head(n).index)


def run_candidates(bars: pd.DataFrame, car_3d: pd.DataFrame) -> None:
    with ENGINE.connect() as conn:
        market_params = pd.read_sql(sa.text("SELECT * FROM market_model_parameters"), conn)
        turnover_baselines = pd.read_sql(sa.text("SELECT * FROM turnover_baselines"), conn)
        delivery_baselines = pd.read_sql(sa.text("SELECT * FROM delivery_baselines"), conn)
        extremes = pd.read_sql(sa.text("SELECT * FROM market_extremes_adv"), conn)
        sectors = pd.read_sql(sa.text("SELECT symbol, sector FROM instruments"), conn)
        raw_bars = pd.read_sql(
            sa.text(
                "SELECT symbol, date, high, low, close, prev_close, turnover FROM daily_bars"
            ),
            conn,
        )
        adj_bars = pd.read_sql(sa.text("SELECT symbol, date, adj_close FROM v_adjusted_bars"), conn)
        announcement_rows = pd.read_sql(
            sa.text(
                "SELECT id, symbol, filed_at, subject, category, raw_json, content_hash "
                "FROM announcements"
            ),
            conn,
        )

    index_snapshots = run_index_snapshots_lookup()

    trading_dates = sorted(bars["date"].unique())
    universe = pick_universe(bars, EVAL_SYMBOLS)
    scored_dates = trading_dates[-EVAL_DAYS:]
    log(f"candidates: universe={len(universe)} symbols, window={len(scored_dates)} sessions")

    market_idx = market_params.set_index(["symbol", "date"])
    turnover_idx = turnover_baselines.set_index(["symbol", "date"])
    delivery_idx = delivery_baselines.set_index(["symbol", "date"])
    extremes_idx = extremes.set_index(["symbol", "date"])
    car_idx = car_3d.set_index(["symbol", "date"])
    raw_idx = raw_bars.set_index(["symbol", "date"])
    adj_idx = adj_bars.set_index(["symbol", "date"])
    sector_by_symbol = sectors.set_index("symbol")["sector"].to_dict()
    index_by_date = index_snapshots.set_index("date")["value"].to_dict()

    from app.ingest.calendar import load_trading_calendar
    from app.timeutil import TradingCalendar

    with ENGINE.connect() as conn:
        calendar: TradingCalendar = load_trading_calendar(
            conn, trading_dates[0], trading_dates[-1]
        )

    announcements_by_symbol: dict[str, list[Announcement]] = {}
    for row in announcement_rows.itertuples(index=False):
        raw = json.loads(row.raw_json) if isinstance(row.raw_json, str) else row.raw_json
        ann = Announcement(
            symbol=row.symbol,
            filed_at=row.filed_at if row.filed_at.tzinfo else row.filed_at.replace(tzinfo=IST),
            subject=row.subject,
            category=row.category,
            para_ref=None,
            attachment_url=None,
            raw_json=raw or {},
            content_hash=row.content_hash,
        )
        announcements_by_symbol.setdefault(row.symbol, []).append(ann)

    registry = load_corporate_action_registry()

    fixtures = []
    for symbol in universe:
        prior_close = None
        for d in scored_dates:
            key = (symbol, d)
            if key not in raw_idx.index or key not in market_idx.index:
                continue
            raw_row = raw_idx.loc[key]
            adj_row = adj_idx.loc[key] if key in adj_idx.index else None
            no_prev_close = (
                raw_row["prev_close"] is None or float(raw_row["prev_close"]) <= 0
            )
            if adj_row is None or no_prev_close:
                continue

            mm = market_idx.loc[key]
            market_model = MarketModelFact(
                alpha=Decimal(str(mm["alpha"])),
                beta=Decimal(str(mm["beta"])),
                r2=None if pd.isna(mm["r2"]) else Decimal(str(mm["r2"])),
                resid_sd=Decimal(str(mm["resid_sd"])),
                n_obs=int(mm["n_obs"]),
                quality_flag=mm["quality_flag"],
            )
            turnover_baseline = None
            if key in turnover_idx.index:
                tb = turnover_idx.loc[key]
                turnover_baseline = TurnoverBaselineFact(
                    mean_log_turnover=Decimal(str(tb["mean_log_turnover"])),
                    std_log_turnover=Decimal(str(tb["std_log_turnover"])),
                    n_obs=int(tb["n_obs"]),
                    quality_flag=tb["quality_flag"],
                )
            delivery_baseline = None
            if key in delivery_idx.index:
                db_row = delivery_idx.loc[key]
                delivery_baseline = DeliveryBaselineFact(
                    raw_delivery_pct=Decimal(str(db_row["raw_delivery_pct"])),
                    logit_delivery=Decimal(str(db_row["logit_delivery"])),
                    mean_logit_20d=Decimal(str(db_row["mean_logit_20d"])),
                    std_logit_20d=Decimal(str(db_row["std_logit_20d"])),
                    delivery_z_score=Decimal(str(db_row["delivery_z_score"])),
                    n_obs=int(db_row["n_obs"]),
                    quality_flag=db_row["quality_flag"],
                )
            extremes_fact = None
            if key in extremes_idx.index:
                ex_row = extremes_idx.loc[key]
                extremes_fact = ExtremesAdvFact(
                    high_52w=Decimal(str(ex_row["high_52w"])),
                    low_52w=Decimal(str(ex_row["low_52w"])),
                    distance_to_52w_high_pct=Decimal(str(ex_row["distance_to_52w_high_pct"])),
                    distance_to_52w_low_pct=Decimal(str(ex_row["distance_to_52w_low_pct"])),
                    adv_20d=Decimal(str(ex_row["adv_20d"])),
                )

            adj_close = Decimal(str(adj_row["adj_close"]))
            adj_prev_close = Decimal(str(prior_close)) if prior_close is not None else None
            if adj_prev_close is None or adj_prev_close <= 0:
                prior_close = adj_row["adj_close"]
                continue

            current_bar = DailyBarFact(
                adj_close=adj_close,
                turnover=Decimal(str(raw_row.get("turnover", 0) or 0))
                if "turnover" in raw_row
                else None,
                volume=None,
                adj_prev_close=adj_prev_close,
            )

            bundle = FactBundle(
                symbol=symbol,
                date=d,
                market_model=market_model,
                turnover_baseline=turnover_baseline,
                delivery_baseline=delivery_baseline,
                extremes=extremes_fact,
                recent_announcements=(),
                current_bar=current_bar,
                completeness=frozenset({"BARS", "MARKET_MODEL"}),
            )

            # Index return anchored at the 09:30 snapshot per §14 / MPM_INDEX_SNAPSHOT_TIME.
            index_val = index_by_date.get(d)
            index_prev = None
            for back in range(1, 6):
                idx = trading_dates.index(d) - back if d in trading_dates else None
                if idx is not None and idx >= 0:
                    index_prev = index_by_date.get(trading_dates[idx])
                    if index_prev is not None:
                        break
            index_return = Decimal("0")
            if index_val is not None and index_prev is not None and float(index_prev) > 0:
                index_return = (Decimal(str(index_val)) - Decimal(str(index_prev))) / Decimal(
                    str(index_prev)
                )

            adj_high_ratio = (
                float(raw_row["high"]) / float(raw_row["close"]) if float(raw_row["close"]) else 1.0
            )
            adj_low_ratio = (
                float(raw_row["low"]) / float(raw_row["close"]) if float(raw_row["close"]) else 1.0
            )
            adj_high = adj_close * Decimal(str(adj_high_ratio))
            adj_low = adj_close * Decimal(str(adj_low_ratio))

            try:
                mpm = evaluate_mpm_gate(
                    adj_prev_close, adj_high, adj_low, adj_close, index_return
                )
            except ValueError:
                prior_close = adj_row["adj_close"]
                continue

            ar = compute_abnormal_return(
                adj_close,
                adj_prev_close,
                index_return,
                float(market_model.alpha),
                float(market_model.beta),
            )
            sar = compute_sar(ar, float(market_model.resid_sd))
            scar_3d = None
            car_val = None
            if key in car_idx.index and not pd.isna(car_idx.loc[key]["car_3d"]):
                car_val = float(car_idx.loc[key]["car_3d"])
                scar_3d = compute_scar(car_val, float(market_model.resid_sd), 3)

            turnover_z = None
            if turnover_baseline is not None and current_bar.turnover is not None:
                turnover_z = (
                    math.log1p(float(current_bar.turnover))
                    - float(turnover_baseline.mean_log_turnover)
                ) / float(turnover_baseline.std_log_turnover)

            abnormality = AbnormalityScores(
                symbol=symbol,
                date=d,
                ar=ar,
                sar=sar,
                car_3d=car_val,
                scar_3d=scar_3d,
                turnover_z=turnover_z,
                delivery_z=(
                    float(delivery_baseline.delivery_z_score) if delivery_baseline else None
                ),
                dist_52w_high_pct=(
                    float(extremes_fact.distance_to_52w_high_pct) if extremes_fact else None
                ),
                dist_52w_low_pct=(
                    float(extremes_fact.distance_to_52w_low_pct) if extremes_fact else None
                ),
                quality_flag=market_model.quality_flag,
                inputs_hash="",
            )

            fixtures.append((bundle, mpm, abnormality))
            prior_close = adj_row["adj_close"]

    log(f"  evaluated {len(fixtures)} symbol-days through the MPM gate + abnormality layer")
    candidates, notices = score_candidates(fixtures, registry=registry)
    log(f"  {len(candidates)} raw candidates, {len(notices)} corporate-action notices")

    # EXPLAINED linking (Phase 6.4)
    linked = []
    for c in candidates:
        anns = announcements_by_symbol.get(c.symbol, [])
        linked.append(link_candidate_announcements(c, anns, calendar) if anns else c)

    # MARKET_WIDE attribution is computed at read time in build_digest (it
    # mirrors sector grouping, which already works that way) — the pipeline
    # only persists the raw, linked candidates plus their sector.
    final_candidates = [(c, sector_by_symbol.get(c.symbol)) for c in linked]

    log(f"  persisting {len(final_candidates)} candidates")
    with ENGINE.begin() as conn:
        conn.execute(sa.text("DELETE FROM candidates"))
        rows = []
        for c, sector in final_candidates:
            rows.append(
                {
                    "id": f"{c.date}:{c.symbol}",
                    "date": c.date,
                    "symbol": c.symbol,
                    "signal_families": [f.value for f in c.signal_families],
                    "primary_signal": c.primary_signal.value,
                    "sar": round(c.sar, 4),
                    "turnover_z": round(c.turnover_z, 4) if c.turnover_z is not None else None,
                    "delivery_z": round(c.delivery_z, 4) if c.delivery_z is not None else None,
                    "scar_3d": round(c.metadata.get("scar_3d", 0.0), 4)
                    if c.metadata.get("scar_3d") is not None
                    else None,
                    "has_material_filing": c.has_material_filing,
                    "inputs_hash": uuid4().hex,
                    "linked_announcement_ids": list(c.linked_announcement_ids),
                    "primary_category": c.primary_category,
                    "is_explained": c.is_explained,
                    "sector": sector,
                    "revision": 1,
                    "status": "FINAL",
                    "was_restated": False,
                    # created_at drives the Brief's "since you last looked" cursor
                    # query — it must track the candidate's own trading date (at
                    # session close IST), not the batch's insert wall-clock time,
                    # or every historical as_of ever passed matches zero rows.
                    "created_at": datetime.combine(c.date, time(15, 30), tzinfo=IST),
                }
            )
        if rows:
            conn.execute(
                sa.text(
                    "INSERT INTO candidates "
                    "(id, date, symbol, signal_families, primary_signal, sar, turnover_z, "
                    "delivery_z, scar_3d, has_material_filing, inputs_hash, "
                    "linked_announcement_ids, primary_category, is_explained, sector, "
                    "revision, status, was_restated, created_at) "
                    "VALUES (:id, :date, :symbol, :signal_families, :primary_signal, :sar, "
                    ":turnover_z, :delivery_z, :scar_3d, :has_material_filing, :inputs_hash, "
                    ":linked_announcement_ids, :primary_category, :is_explained, :sector, "
                    ":revision, :status, :was_restated, :created_at)"
                ),
                rows,
            )

        conn.execute(sa.text("DELETE FROM corporate_action_notices"))
        notice_rows = [
            {
                "symbol": n.symbol,
                "ex_date": n.ex_date,
                "cum_date": n.cum_date,
                "action_type": n.action_type,
                "as_traded_cum_close": n.as_traded_cum_close,
                "adjusted_prev_close": n.adjusted_prev_close,
                "adjustment_factor": n.adjustment_factor,
                "ratio_or_amount": n.ratio_or_amount,
                "headline": n.headline,
                "detail_text": n.detail_text,
                "source_url": n.source_url,
                "created_at": n.created_at,
            }
            for n in notices
        ]
        if notice_rows:
            conn.execute(
                sa.text(
                    "INSERT INTO corporate_action_notices "
                    "(symbol, ex_date, cum_date, action_type, as_traded_cum_close, "
                    "adjusted_prev_close, adjustment_factor, ratio_or_amount, headline, "
                    "detail_text, source_url, created_at) "
                    "VALUES (:symbol, :ex_date, :cum_date, :action_type, :as_traded_cum_close, "
                    ":adjusted_prev_close, :adjustment_factor, :ratio_or_amount, :headline, "
                    ":detail_text, :source_url, :created_at) "
                    "ON CONFLICT DO NOTHING"
                ),
                notice_rows,
            )
    log("done")


if __name__ == "__main__":
    run_adjustment_factors()
    bars, delivery, index_bars, _ = load_wide_frames()
    car_3d = run_baselines(bars, delivery, index_bars)
    run_candidates(bars, car_3d)
