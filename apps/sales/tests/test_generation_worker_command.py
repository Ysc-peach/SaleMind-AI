"""The worker command's loop, not just the service functions it calls.

The queue tests drive ``claim_next_job`` and ``execute_job`` directly, so the
command's own behaviour — the idle tick, the exit conditions, the poll interval
and the operator interrupt — was never executed by any test.
"""

from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from apps.sales.management.commands import run_generation_worker as worker
from apps.sales.models import SolutionGenerationJobStatus


class _Stop(Exception):
    """Sentinel raised from a patched service call to end the loop."""


class _Clock:
    def __init__(self):
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def _job(pk=41):
    return SimpleNamespace(pk=pk)


def _run(clock=None, **options):
    output = StringIO()
    options.setdefault("stdout", output)
    call_command("run_generation_worker", **options)
    return output.getvalue()


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    # The command resolves `time.sleep` through its module global, so replacing
    # the module object keeps the real clock out of the test.
    monkeypatch.setattr(worker, "time", fake)
    return fake


def test_once_executes_a_claimed_job_and_returns(monkeypatch, clock):
    executed = []
    monkeypatch.setattr(worker, "claim_next_job", lambda: _job(41))
    monkeypatch.setattr(
        worker,
        "execute_job",
        lambda job: executed.append(job.pk) or SolutionGenerationJobStatus.SUCCEEDED,
    )
    monkeypatch.setattr(
        worker, "reclaim_stale_jobs", lambda: pytest.fail("idle tick ran with work")
    )

    output = _run(clock=clock, once=True)

    assert executed == [41]
    assert "job 41 -> succeeded" in output
    assert clock.sleeps == []


def test_once_with_an_empty_queue_exits_without_waiting(monkeypatch, clock):
    monkeypatch.setattr(worker, "claim_next_job", lambda: None)
    monkeypatch.setattr(worker, "reclaim_stale_jobs", lambda: 0)
    monkeypatch.setattr(
        worker, "execute_job", lambda job: pytest.fail("executed an unclaimed job")
    )

    output = _run(clock=clock, once=True)

    assert "no queued job" in output
    assert clock.sleeps == []


def test_an_idle_tick_recovers_lost_jobs_and_says_so(monkeypatch, clock):
    monkeypatch.setattr(worker, "claim_next_job", lambda: None)
    monkeypatch.setattr(worker, "reclaim_stale_jobs", lambda: 2)
    monkeypatch.setattr(worker, "execute_job", lambda job: None)

    output = _run(clock=clock, once=True)

    assert "reclaimed 2 stale job(s)" in output
    assert "no queued job" in output


def test_a_polling_worker_waits_then_picks_the_next_job(monkeypatch, clock):
    claims = iter([None, _job(51)])

    def claim():
        return next(claims)

    def execute(job):
        raise _Stop

    monkeypatch.setattr(worker, "claim_next_job", claim)
    monkeypatch.setattr(worker, "reclaim_stale_jobs", lambda: 0)
    monkeypatch.setattr(worker, "execute_job", execute)

    with pytest.raises(_Stop):
        _run(clock=clock, poll_seconds=0.7)

    # One idle wait, then the claimed job stops the loop from the test side.
    assert clock.sleeps == [0.7]


def test_the_poll_interval_is_floored(monkeypatch, clock):
    claims = iter([None, _job(52)])

    monkeypatch.setattr(worker, "claim_next_job", lambda: next(claims))
    monkeypatch.setattr(worker, "reclaim_stale_jobs", lambda: 0)
    monkeypatch.setattr(worker, "execute_job", lambda job: (_ for _ in ()).throw(_Stop()))

    with pytest.raises(_Stop):
        _run(clock=clock, poll_seconds=0.01)

    # Below half a second the worker would spin on the database.
    assert clock.sleeps == [0.5]


def test_an_operator_interrupt_stops_the_worker_cleanly(monkeypatch, clock):
    monkeypatch.setattr(worker, "claim_next_job", lambda: _job(61))

    def execute(job):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "execute_job", execute)

    output = _run(clock=clock)

    assert "worker stopped" in output


def test_stale_connections_are_dropped_on_every_tick(monkeypatch, clock):
    calls = []
    claims = iter([None, _job(71)])

    monkeypatch.setattr(worker, "close_old_connections", lambda: calls.append(1))
    monkeypatch.setattr(worker, "claim_next_job", lambda: next(claims))
    monkeypatch.setattr(worker, "reclaim_stale_jobs", lambda: 0)
    monkeypatch.setattr(worker, "execute_job", lambda job: (_ for _ in ()).throw(_Stop()))

    with pytest.raises(_Stop):
        _run(clock=clock)

    # A long-lived worker must not hold a connection opened before a database
    # restart, so the check happens before each claim rather than once.
    assert len(calls) == 2
