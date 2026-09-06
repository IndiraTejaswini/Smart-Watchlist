"""Unit coverage for chronological, calendar-gated backfill orchestration."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from app.ingest import backfill


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, statement, params):
        text = str(statement)
        if "FROM trading_calendar" in text:
            rows = self.rows
            return type("Result", (), {"all": lambda self: rows})()
        return type("Result", (), {"scalar_one": lambda self: 0})()


class FakeEngine:
    def __init__(self, rows):
        self.rows = rows

    def connect(self):
        engine = self

        class Context:
            def __enter__(self):
                return FakeConnection(engine.rows)

            def __exit__(self, *_args):
                return None

        return Context()


def test_runner_skips_weekend_holiday_and_processes_special_session(monkeypatch):
    start = date(2026, 9, 3)
    rows = [
        (
            start + timedelta(days=offset),
            offset not in (2, 3),
            "MUHURAT" if offset == 1 else "REGULAR",
        )
        for offset in range(5)
    ]
    engine = FakeEngine(rows)
    calls: list[tuple[str, date]] = []

    def payload(name):
        def fetch(*args, **kwargs):
            calls.append((name, args[0]))
            return b"payload"

        return fetch

    monkeypatch.setattr(backfill, "_fetch_payload", payload("bhavcopy"))
    monkeypatch.setattr(backfill.delivery, "fetch_payload", payload("delivery"))
    monkeypatch.setattr(backfill.index_data, "fetch_payload", payload("index"))
    monkeypatch.setattr(
        backfill,
        "ingest_bhavcopy",
        lambda payload, target_date, **kwargs: SimpleNamespace(status="OK"),
    )
    monkeypatch.setattr(
        backfill.delivery,
        "ingest_delivery",
        lambda payload, target_date, **kwargs: SimpleNamespace(status="SKIPPED_CACHED"),
    )
    monkeypatch.setattr(
        backfill.index_data,
        "ingest_index_eod",
        lambda payload, target_date, **kwargs: SimpleNamespace(status="OK"),
    )
    monkeypatch.setattr(backfill, "capture_index_snapshot_0930", lambda *args, **kwargs: {})
    monkeypatch.setattr(backfill, "_quarantine_count", lambda *args: 0)

    report = backfill.run_backfill(start, start + timedelta(days=4), engine=engine)
    assert report.calendar_days_scanned == 5
    assert report.holidays_skipped == 2
    assert report.successful_days == 3
    assert calls == [
        ("bhavcopy", start),
        ("delivery", start),
        ("index", start),
        ("bhavcopy", start + timedelta(days=1)),
        ("delivery", start + timedelta(days=1)),
        ("index", start + timedelta(days=1)),
        ("bhavcopy", start + timedelta(days=4)),
        ("delivery", start + timedelta(days=4)),
        ("index", start + timedelta(days=4)),
    ]
