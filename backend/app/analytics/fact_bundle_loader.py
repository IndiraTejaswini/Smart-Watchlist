"""Database and Redis loading for immutable cold fact bundles."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.analytics.fact_bundle import (
    AnnouncementFact,
    DailyBarFact,
    DeliveryBaselineFact,
    ExtremesAdvFact,
    FactBundle,
    MarketModelFact,
    Snapshot0930Fact,
    TurnoverBaselineFact,
)

TTL_SECONDS = 86_400


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _row(conn: Any, query: str, params: dict[str, Any]) -> Any | None:
    return conn.execute(query, params).mappings().first()


def load_cold_fact_bundle_from_db(db: Any, symbol: str, target_date: date) -> FactBundle:
    params = {"symbol": symbol, "date": target_date}
    bar = _row(db, "SELECT close, prev_close, turnover, volume FROM daily_bars "
                   "WHERE symbol = :symbol AND date = :date", params)
    model = _row(db, "SELECT alpha, beta, r2, resid_sd, n_obs, quality_flag "
                    "FROM market_model_parameters WHERE symbol = :symbol AND date = :date", params)
    turnover = _row(db, "SELECT mean_log_turnover, std_log_turnover, n_obs, quality_flag "
                       "FROM turnover_baselines WHERE symbol = :symbol AND date = :date", params)
    delivery = _row(db, "SELECT raw_delivery_pct, logit_delivery, mean_logit_20d, "
                        "std_logit_20d, delivery_z_score, n_obs, quality_flag "
                        "FROM delivery_baselines WHERE symbol = :symbol AND date = :date", params)
    extremes = _row(db, "SELECT high_52w, low_52w, distance_to_52w_high_pct, "
                        "distance_to_52w_low_pct, adv_20d FROM market_extremes_adv "
                        "WHERE symbol = :symbol AND date = :date", params)
    announcements = db.execute(
        "SELECT filed_at, subject, category, attachment_url FROM announcements "
        "WHERE symbol = :symbol AND filed_at::date = :date ORDER BY filed_at",
        params,
    ).mappings()
    snapshot = _row(db, "SELECT value, quality_flag FROM index_snapshots_0930 "
                       "WHERE index_symbol = :symbol AND trading_date = :date", params)

    completeness: set[str] = set()
    current_bar = (
        DailyBarFact(
            _decimal(bar["close"]),
            _decimal(bar["turnover"]) if bar["turnover"] is not None else None,
            bar["volume"],
            _decimal(bar["prev_close"]) if bar["prev_close"] is not None else None,
        )
        if bar else None
    )
    if current_bar:
        completeness.add("BARS")
    market_model = (
        MarketModelFact(_decimal(model["alpha"]), _decimal(model["beta"]),
                        _decimal(model["r2"]) if model["r2"] is not None else None,
                        _decimal(model["resid_sd"]), int(model["n_obs"]), model["quality_flag"])
        if model else None
    )
    if market_model:
        completeness.add("MARKET_MODEL")
    turnover_fact = (
        TurnoverBaselineFact(
            _decimal(turnover["mean_log_turnover"]),
            _decimal(turnover["std_log_turnover"]),
            int(turnover["n_obs"]),
            turnover["quality_flag"],
        )
        if turnover else None
    )
    if turnover_fact:
        completeness.add("TURNOVER_BASELINE")
    delivery_fact = (
        DeliveryBaselineFact(
            _decimal(delivery["raw_delivery_pct"]),
            _decimal(delivery["logit_delivery"]),
            _decimal(delivery["mean_logit_20d"]),
            _decimal(delivery["std_logit_20d"]),
            _decimal(delivery["delivery_z_score"]),
            int(delivery["n_obs"]),
            delivery["quality_flag"],
        )
        if delivery else None
    )
    if delivery_fact:
        completeness.add("DELIVERY_BASELINE")
    extremes_fact = (
        ExtremesAdvFact(
            _decimal(extremes["high_52w"]),
            _decimal(extremes["low_52w"]),
            _decimal(extremes["distance_to_52w_high_pct"]),
            _decimal(extremes["distance_to_52w_low_pct"]),
            _decimal(extremes["adv_20d"]),
        )
        if extremes else None
    )
    if extremes_fact:
        completeness.add("EXTREMES")
    announcement_facts = tuple(
        AnnouncementFact(row["filed_at"], row["subject"], row["category"], row["attachment_url"])
        for row in announcements
    )
    if announcement_facts:
        completeness.add("ANNOUNCEMENTS")
    snapshot_fact = (
        Snapshot0930Fact(_decimal(snapshot["value"]), snapshot["quality_flag"])
        if snapshot else None
    )
    return FactBundle(
        symbol, target_date, market_model, turnover_fact, delivery_fact, extremes_fact,
        announcement_facts, current_bar, snapshot_fact, frozenset(completeness),
    )


def _encode(bundle: FactBundle) -> str:
    def default(value: Any) -> Any:
        if isinstance(value, frozenset):
            return sorted(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        raise TypeError(type(value).__name__)

    return json.dumps(asdict(bundle), default=default, sort_keys=True, separators=(",", ":"))


def _decode(payload: str) -> FactBundle:
    raw = json.loads(payload)
    raw["date"] = date.fromisoformat(raw["date"])
    raw["completeness"] = frozenset(raw["completeness"])
    if raw.get("market_model"):
        value = raw["market_model"]
        value["alpha"] = _decimal(value["alpha"])
        value["beta"] = _decimal(value["beta"])
        value["r2"] = _decimal(value["r2"]) if value["r2"] is not None else None
        value["resid_sd"] = _decimal(value["resid_sd"])
        raw["market_model"] = MarketModelFact(**value)
    if raw.get("turnover_baseline"):
        value = raw["turnover_baseline"]
        for key in ("mean_log_turnover", "std_log_turnover"):
            value[key] = _decimal(value[key])
        raw["turnover_baseline"] = TurnoverBaselineFact(**value)
    if raw.get("delivery_baseline"):
        value = raw["delivery_baseline"]
        for key in ("raw_delivery_pct", "logit_delivery", "mean_logit_20d",
                    "std_logit_20d", "delivery_z_score"):
            value[key] = _decimal(value[key])
        raw["delivery_baseline"] = DeliveryBaselineFact(**value)
    if raw.get("extremes"):
        value = raw["extremes"]
        for key in ("high_52w", "low_52w", "distance_to_52w_high_pct",
                    "distance_to_52w_low_pct", "adv_20d"):
            value[key] = _decimal(value[key])
        raw["extremes"] = ExtremesAdvFact(**value)
    if raw.get("current_bar"):
        value = raw["current_bar"]
        value["adj_close"] = _decimal(value["adj_close"])
        value["turnover"] = _decimal(value["turnover"]) if value["turnover"] is not None else None
        raw["current_bar"] = DailyBarFact(**value)
    if raw.get("index_snapshot_0930"):
        value = raw["index_snapshot_0930"]
        value["value"] = _decimal(value["value"])
        raw["index_snapshot_0930"] = Snapshot0930Fact(**value)
    raw["recent_announcements"] = tuple(
        AnnouncementFact(
            datetime.fromisoformat(item["filed_at"])
            if isinstance(item["filed_at"], str) else item["filed_at"],
            item["subject"], item["category"], item["attachment_url"],
        )
        for item in raw["recent_announcements"]
    )
    return FactBundle(
        **raw,
    )


def get_cold_fact_bundle(redis_client: Any, db: Any, symbol: str, target_date: date) -> FactBundle:
    key = f"factbundle:cold:{symbol}:{target_date.isoformat()}"
    payload = redis_client.get(key)
    if payload:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return _decode(payload)
    bundle = load_cold_fact_bundle_from_db(db, symbol, target_date)
    redis_client.setex(key, TTL_SECONDS, _encode(bundle))
    return bundle


def purge_cold_fact_bundle_cache(redis_client: Any, symbol: str, target_date: date) -> None:
    redis_client.delete(f"factbundle:cold:{symbol}:{target_date.isoformat()}")
