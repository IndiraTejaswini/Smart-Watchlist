from datetime import UTC, datetime

from app.crud.read_cursor import upsert_read_cursor


class _Result:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


def test_read_cursor_merge_sql_is_monotonic_and_idempotent() -> None:
    statements: list[str] = []

    class FakeSession:
        def execute(self, statement, params):
            statements.append(str(statement))
            return _Result(max(params["incoming_seq"], 0))

        def commit(self):
            return None

    db = FakeSession()
    timestamp = datetime(2026, 4, 6, 10, tzinfo=UTC)
    assert upsert_read_cursor(db, "USER_ALPHA", "candidates_stream", 50, timestamp) == 50
    assert upsert_read_cursor(db, "USER_ALPHA", "candidates_stream", 100, timestamp) == 100
    assert "GREATEST" in statements[0]
    assert "ON CONFLICT (user_id, feed_id)" in statements[0]
