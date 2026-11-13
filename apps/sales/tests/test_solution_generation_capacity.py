"""The generation slots bound concurrency without a queue or extra service."""

import pytest

from apps.sales.services import solution_generation_capacity as capacity


class FakeCursor:
    """Records statements and replays the advisory-lock answers in order."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return (self.answers.pop(0),)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _patch(monkeypatch, cursor):
    monkeypatch.setattr(capacity.connection, "cursor", lambda: cursor)


def test_first_free_slot_is_used_and_released(monkeypatch, settings):
    settings.SOLUTION_GENERATION_MAX_CONCURRENT = 2
    cursor = FakeCursor([False, True, True])
    _patch(monkeypatch, cursor)

    with capacity.generation_slot():
        pass

    sqls = [sql for sql, _ in cursor.statements]
    assert sum("pg_try_advisory_lock" in sql for sql in sqls) == 2
    assert sum("pg_advisory_unlock" in sql for sql in sqls) == 1


def test_no_free_slot_fails_closed_without_unlocking(monkeypatch, settings):
    settings.SOLUTION_GENERATION_MAX_CONCURRENT = 3
    cursor = FakeCursor([False, False, False])
    _patch(monkeypatch, cursor)

    with pytest.raises(capacity.GenerationCapacityReached):
        with capacity.generation_slot():
            pass

    sqls = [sql for sql, _ in cursor.statements]
    assert sum("pg_try_advisory_lock" in sql for sql in sqls) == 3
    assert not any("pg_advisory_unlock" in sql for sql in sqls)


def test_limit_is_never_below_one(monkeypatch, settings):
    settings.SOLUTION_GENERATION_MAX_CONCURRENT = 0
    cursor = FakeCursor([True, True])
    _patch(monkeypatch, cursor)

    with capacity.generation_slot():
        pass

    sqls = [sql for sql, _ in cursor.statements]
    assert sum("pg_try_advisory_lock" in sql for sql in sqls) == 1
