"""Claim and execute queued Solution generation jobs.

The worker is a plain management command rather than a broker process: the
queue lives in the same PostgreSQL database the project already depends on, and
``FOR UPDATE SKIP LOCKED`` gives exactly-one-claim semantics without Redis.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import connections, transaction
from django.db.models import Q
from django.utils import timezone

from apps.sales.models import (
    SolutionGenerationJob,
    SolutionGenerationJobStatus,
)
from apps.sales.services.solution_generation_capacity import (
    GenerationCapacityReached,
)
from apps.sales.services.solution_workflow_runner import (
    WorkflowFailedOutcome,
    start_workflow,
)

logger = logging.getLogger(__name__)


def claim_next_job() -> SolutionGenerationJob | None:
    """Move the oldest queued job to running, or return None when idle."""

    with transaction.atomic():
        job = (
            SolutionGenerationJob.objects.select_for_update(skip_locked=True)
            .filter(status=SolutionGenerationJobStatus.QUEUED)
            .order_by("created_at", "id")
            .first()
        )
        if job is None:
            return None
        now = timezone.now()
        job.status = SolutionGenerationJobStatus.RUNNING
        job.started_at = now
        job.heartbeat_at = now
        job.attempts += 1
        job.save(
            update_fields=["status", "started_at", "heartbeat_at", "attempts"],
        )
    return job


def _finish(job: SolutionGenerationJob, *, status: str, error_code: str = "") -> None:
    job.status = status
    job.error_code = error_code
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error_code", "finished_at"])


def _requeue(job: SolutionGenerationJob) -> None:
    job.status = SolutionGenerationJobStatus.QUEUED
    job.started_at = None
    job.heartbeat_at = None
    job.attempts = max(0, job.attempts - 1)
    job.save(update_fields=["status", "started_at", "heartbeat_at", "attempts"])


def _requeue_lost(job: SolutionGenerationJob) -> None:
    """Return a lost job to the queue without refunding the attempt.

    Unlike the capacity requeue, this attempt was really spent: the worker died
    while owning it. Keeping the counter is what eventually turns a repeatedly
    crashing job into a visible failure instead of an endless retry loop.
    """

    job.status = SolutionGenerationJobStatus.QUEUED
    job.started_at = None
    job.heartbeat_at = None
    job.save(update_fields=["status", "started_at", "heartbeat_at"])


def stale_running_queryset(*, now=None):
    """RUNNING rows whose worker stopped heartbeating.

    Shared with the health check. When the only worker dies, nothing calls
    ``reclaim_stale_jobs``, so the operator needs to see the very same rows from
    the outside rather than infer them from a queue that never drains.
    """

    now = now or timezone.now()
    cutoff = now - timedelta(
        seconds=settings.SOLUTION_GENERATION_JOB_STALE_SECONDS
    )
    return SolutionGenerationJob.objects.filter(
        status=SolutionGenerationJobStatus.RUNNING
    ).filter(
        Q(heartbeat_at__lt=cutoff)
        | Q(heartbeat_at__isnull=True, started_at__lt=cutoff)
    )


def reclaim_stale_jobs(*, now=None) -> int:
    """Requeue or fail jobs whose worker stopped heartbeating.

    A worker killed mid-run leaves its row in RUNNING forever: the client polls
    until its own timeout and the job never completes. Liveness is judged from
    ``heartbeat_at``, falling back to ``started_at`` for rows written before the
    heartbeat column was populated.
    """

    max_attempts = settings.SOLUTION_GENERATION_JOB_MAX_ATTEMPTS
    reclaimed = 0

    with transaction.atomic():
        stale = (
            stale_running_queryset(now=now)
            .select_for_update(skip_locked=True)
            .order_by("started_at", "id")
        )
        for job in stale:
            if job.attempts >= max_attempts:
                _finish(
                    job,
                    status=SolutionGenerationJobStatus.FAILED,
                    error_code="workflow_worker_lost",
                )
                logger.warning(
                    "generation job %s failed: worker lost after %s attempts",
                    job.pk, job.attempts,
                )
            else:
                _requeue_lost(job)
                logger.info(
                    "generation job %s requeued: worker stopped heartbeating",
                    job.pk,
                )
            reclaimed += 1

    return reclaimed


def heartbeat_interval_seconds() -> float:
    """Beat often enough that a healthy run never crosses the stale window.

    The configured interval is clamped to a third of the stale window, so a
    deployment that sets both to the same value cannot make its own runs look
    dead.
    """

    configured = max(1, settings.SOLUTION_GENERATION_JOB_HEARTBEAT_SECONDS)
    window = max(3, settings.SOLUTION_GENERATION_JOB_STALE_SECONDS)
    return min(configured, window / 3)


class _Heartbeat:
    """Refresh ``heartbeat_at`` while a job is actually running.

    The claim writes the heartbeat once. Without a refresh, any run longer than
    the stale window looks abandoned and ``reclaim_stale_jobs`` either requeues
    it or fails it as ``workflow_worker_lost``, even though the worker is fine.
    The beat runs on a daemon thread with its own database connection, which is
    closed when the thread stops so a long-lived worker does not leak them.
    """

    def __init__(self, job_id: int, interval_seconds: float):
        self._job_id = job_id
        self._interval = max(0.01, interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_Heartbeat":
        self._thread = threading.Thread(
            target=self._run,
            name=f"generation-heartbeat-{self._job_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval * 2 + 5)
        return False

    def _run(self) -> None:
        try:
            while not self._stop.wait(self._interval):
                self._beat()
        finally:
            # The thread opened its own connection; leaving it open would keep a
            # database session alive for every run served by this worker.
            connections.close_all()

    def _beat(self) -> None:
        try:
            SolutionGenerationJob.objects.filter(
                pk=self._job_id,
                status=SolutionGenerationJobStatus.RUNNING,
            ).update(heartbeat_at=timezone.now())
        except Exception:
            # A missed beat must never abort the run: the stale window still
            # covers the last successful one.
            logger.warning(
                "generation job %s heartbeat update failed", self._job_id
            )


def execute_job(job: SolutionGenerationJob) -> str:
    """Run one claimed job and record its terminal state.

    Returns the resulting status. Provider and guard failures are recorded as a
    failed job rather than raised: the worker keeps serving the queue.
    """

    try:
        with _Heartbeat(job.pk, heartbeat_interval_seconds()):
            start_workflow(
                workflow_id=job.workflow_id,
                opportunity=job.opportunity,
                analysis=job.requirement_analysis,
                actor=job.requested_by,
            )
    except GenerationCapacityReached:
        # Another run holds every slot. Put the job back rather than burning an
        # attempt; the next poll retries it.
        _requeue(job)
        logger.info("generation job %s requeued: capacity reached", job.pk)
        return SolutionGenerationJobStatus.QUEUED
    except WorkflowFailedOutcome as error:
        _finish(
            job,
            status=SolutionGenerationJobStatus.FAILED,
            error_code=error.error_code or error.outcome or "workflow_failed",
        )
        logger.info("generation job %s failed: %s", job.pk, error.error_code)
        return SolutionGenerationJobStatus.FAILED
    except Exception:
        # Never log the message or traceback: provider errors can carry payload.
        _finish(
            job,
            status=SolutionGenerationJobStatus.FAILED,
            error_code="workflow_generation_error",
        )
        logger.warning("generation job %s failed with an unexpected error", job.pk)
        return SolutionGenerationJobStatus.FAILED

    _finish(job, status=SolutionGenerationJobStatus.SUCCEEDED)
    logger.info("generation job %s succeeded", job.pk)
    return SolutionGenerationJobStatus.SUCCEEDED
