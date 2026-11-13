"""Bound how many workflows may generate at the same time in one deployment.

Generation is synchronous today: one request holds a worker for 95-98 seconds.
Without a bound, three concurrent clicks occupy every gunicorn worker and the
whole intranet instance stops answering, including login. The slots are
PostgreSQL advisory locks, so the bound holds across worker processes and is
released automatically if a worker dies mid-request.

This is a stop-gap, not a queue: a caller that finds no slot is told to retry
later instead of being queued silently.
"""

from contextlib import contextmanager

from django.conf import settings
from django.db import connection

# Arbitrary namespace so these locks cannot collide with the workflow
# idempotency locks in solution_persistence.
_SLOT_NAMESPACE = 8_675_309


class GenerationCapacityReached(Exception):
    """No generation slot is free right now."""


def _slot_limit() -> int:
    return max(1, int(settings.SOLUTION_GENERATION_MAX_CONCURRENT))


@contextmanager
def generation_slot():
    """Hold one generation slot for the duration of the block."""

    acquired: int | None = None
    with connection.cursor() as cursor:
        for slot in range(_slot_limit()):
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s)", [_SLOT_NAMESPACE + slot],
            )
            if cursor.fetchone()[0]:
                acquired = slot
                break

    if acquired is None:
        raise GenerationCapacityReached()

    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(%s)", [_SLOT_NAMESPACE + acquired],
            )
