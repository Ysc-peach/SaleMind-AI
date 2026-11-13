"""The worker claims queued rows and records exactly one terminal state."""

from uuid import uuid4

import pytest

from apps.sales.models import SolutionGenerationJob, SolutionGenerationJobStatus
from apps.sales.services import solution_generation_jobs as jobs
from apps.sales.services.solution_generation_capacity import (
    GenerationCapacityReached,
)
from apps.sales.services.solution_workflow_runner import WorkflowFailedOutcome
from apps.sales.tests.test_solution_persistence_service import (  # noqa: F401
    persistence_context,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def queued_job(persistence_context):
    owner, _customer, opportunity, analysis, _create_analysis = persistence_context
    return SolutionGenerationJob.objects.create(
        workflow_id=uuid4(),
        opportunity=opportunity,
        requirement_analysis=analysis,
        requested_by=owner,
    )


def test_claim_moves_the_oldest_job_to_running(queued_job):
    claimed = jobs.claim_next_job()

    assert claimed is not None
    claimed.refresh_from_db()
    assert claimed.pk == queued_job.pk
    assert claimed.status == SolutionGenerationJobStatus.RUNNING
    assert claimed.started_at is not None
    assert claimed.attempts == 1


def test_claim_returns_none_when_nothing_is_queued(queued_job):
    jobs.claim_next_job()

    assert jobs.claim_next_job() is None


def test_a_running_job_is_not_claimed_twice(queued_job):
    first = jobs.claim_next_job()
    second = jobs.claim_next_job()

    assert first is not None and second is None


def test_execute_records_success(monkeypatch, queued_job):
    monkeypatch.setattr(jobs, "start_workflow", lambda **kwargs: None)
    job = jobs.claim_next_job()

    status = jobs.execute_job(job)

    job.refresh_from_db()
    assert status == SolutionGenerationJobStatus.SUCCEEDED
    assert job.status == SolutionGenerationJobStatus.SUCCEEDED
    assert job.finished_at is not None
    assert job.error_code == ""


def test_execute_records_a_failed_outcome(monkeypatch, queued_job):
    def fail(**kwargs):
        raise WorkflowFailedOutcome("failed", "solution_draft_not_grounded")

    monkeypatch.setattr(jobs, "start_workflow", fail)
    job = jobs.claim_next_job()

    jobs.execute_job(job)

    job.refresh_from_db()
    assert job.status == SolutionGenerationJobStatus.FAILED
    assert job.error_code == "solution_draft_not_grounded"
    assert job.finished_at is not None


def test_execute_requeues_when_every_slot_is_busy(monkeypatch, queued_job):
    def busy(**kwargs):
        raise GenerationCapacityReached()

    monkeypatch.setattr(jobs, "start_workflow", busy)
    job = jobs.claim_next_job()

    status = jobs.execute_job(job)

    job.refresh_from_db()
    assert status == SolutionGenerationJobStatus.QUEUED
    assert job.status == SolutionGenerationJobStatus.QUEUED
    assert job.started_at is None
    assert job.attempts == 0


def test_unexpected_errors_do_not_leak_into_the_row(monkeypatch, queued_job):
    def explode(**kwargs):
        raise RuntimeError("PRIVATE_PROVIDER_BODY")

    monkeypatch.setattr(jobs, "start_workflow", explode)
    job = jobs.claim_next_job()

    jobs.execute_job(job)

    job.refresh_from_db()
    assert job.status == SolutionGenerationJobStatus.FAILED
    assert job.error_code == "workflow_generation_error"
    assert "PRIVATE_PROVIDER_BODY" not in job.error_code
