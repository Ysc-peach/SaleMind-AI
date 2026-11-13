"""Claim and execute queued Solution generation jobs.

The worker is a plain management command rather than a broker process: the
queue lives in the same PostgreSQL database the project already depends on, and
``FOR UPDATE SKIP LOCKED`` gives exactly-one-claim semantics without Redis.
"""

from __future__ import annotations

import logging

from django.db import transaction
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


def execute_job(job: SolutionGenerationJob) -> str:
    """Run one claimed job and record its terminal state.

    Returns the resulting status. Provider and guard failures are recorded as a
    failed job rather than raised: the worker keeps serving the queue.
    """

    try:
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
