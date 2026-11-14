"""Queue health signal and its fail-fast management command."""

import json
from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.sales.models import SolutionGenerationJob, SolutionGenerationJobStatus
from apps.sales.services.generation_health import collect_health
from apps.sales.tests.test_solution_persistence_service import (  # noqa: F401
    persistence_context,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def job_context(persistence_context):
    owner, _customer, opportunity, analysis, _create_analysis = persistence_context
    return owner, opportunity, analysis


def _add_job(context, **overrides):
    owner, opportunity, analysis = context
    values = {
        "workflow_id": uuid4(),
        "opportunity": opportunity,
        "requirement_analysis": analysis,
        "requested_by": owner,
    }
    values.update(overrides)
    return SolutionGenerationJob.objects.create(**values)


def _run(**options):
    output = StringIO()
    call_command("check_generation_health", stdout=output, **options)
    return json.loads(output.getvalue())


def test_an_idle_queue_is_healthy(job_context):
    report = _run()

    assert report["health"]["queued"] == 0
    assert report["health"]["oldest_queued_wait_seconds"] == 0
    assert report["breaches"] == []


def test_backlog_over_the_threshold_exits_non_zero(job_context):
    for _ in range(3):
        _add_job(job_context)

    with pytest.raises(CommandError, match="queued"):
        _run(max_queued=2)


def test_a_job_waiting_too_long_is_reported(job_context):
    job = _add_job(job_context)
    SolutionGenerationJob.objects.filter(pk=job.pk).update(
        created_at=timezone.now() - timedelta(minutes=20)
    )

    output = StringIO()
    with pytest.raises(CommandError, match="oldest_queued_wait_seconds"):
        call_command(
            "check_generation_health", stdout=output, max_wait_seconds=600
        )

    report = json.loads(output.getvalue())
    assert report["breaches"] == ["oldest_queued_wait_seconds"]
    assert report["health"]["oldest_queued_wait_seconds"] > 600


def test_recent_failures_are_counted(job_context):
    now = timezone.now()
    for _ in range(2):
        _add_job(
            job_context,
            status=SolutionGenerationJobStatus.FAILED,
            started_at=now - timedelta(minutes=2),
            finished_at=now - timedelta(minutes=1),
            error_code="workflow_generation_error",
        )

    with pytest.raises(CommandError, match="failed_last_hour"):
        _run(max_failed_last_hour=1)

    report = collect_health()
    assert report.failed_last_hour == 2


def test_running_and_old_failures_are_visible_but_not_breaches(job_context):
    now = timezone.now()
    _add_job(
        job_context,
        status=SolutionGenerationJobStatus.RUNNING,
        started_at=now,
        heartbeat_at=now,
        attempts=1,
    )
    _add_job(
        job_context,
        status=SolutionGenerationJobStatus.FAILED,
        started_at=now - timedelta(days=2),
        finished_at=now - timedelta(days=2),
        error_code="workflow_generation_error",
    )

    report = _run()

    assert report["health"]["running"] == 1
    assert report["health"]["failed_last_hour"] == 0
    assert report["breaches"] == []
