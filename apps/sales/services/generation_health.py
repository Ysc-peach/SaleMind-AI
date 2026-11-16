"""Read-only queue health signal for operators and scheduled monitoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta

from django.utils import timezone

from apps.sales.models import (
    SolutionGenerationJob,
    SolutionGenerationJobStatus,
)
from apps.sales.services.solution_generation_jobs import stale_running_queryset


@dataclass(frozen=True)
class GenerationHealth:
    queued: int
    running: int
    stale_running: int
    oldest_queued_wait_seconds: float
    failed_last_hour: int

    def as_dict(self) -> dict:
        return asdict(self)


def collect_health(*, now=None) -> GenerationHealth:
    """One cheap snapshot; never mutates a job and never contacts a provider."""

    now = now or timezone.now()
    queued = SolutionGenerationJob.objects.filter(
        status=SolutionGenerationJobStatus.QUEUED
    )
    oldest = queued.order_by("created_at").values_list(
        "created_at", flat=True
    ).first()
    wait = max(0.0, (now - oldest).total_seconds()) if oldest else 0.0

    return GenerationHealth(
        queued=queued.count(),
        running=SolutionGenerationJob.objects.filter(
            status=SolutionGenerationJobStatus.RUNNING
        ).count(),
        # A worker that died cannot reclaim its own job, so this is the only
        # signal an operator gets from outside the worker process.
        stale_running=stale_running_queryset(now=now).count(),
        oldest_queued_wait_seconds=wait,
        failed_last_hour=SolutionGenerationJob.objects.filter(
            status=SolutionGenerationJobStatus.FAILED,
            finished_at__gte=now - timedelta(hours=1),
        ).count(),
    )
