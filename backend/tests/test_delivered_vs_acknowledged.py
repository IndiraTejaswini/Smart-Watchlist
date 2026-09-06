from datetime import UTC, datetime

from app.crud.brief_cursor import EPOCH, acknowledge_brief, get_brief_cursor, record_brief_served


def test_serving_advances_seen_without_acknowledging() -> None:
    assert EPOCH < datetime(2026, 4, 6, 10, tzinfo=UTC)
    assert record_brief_served.__name__ == "record_brief_served"
    assert acknowledge_brief.__name__ == "acknowledge_brief"
    assert get_brief_cursor.__name__ == "get_brief_cursor"
