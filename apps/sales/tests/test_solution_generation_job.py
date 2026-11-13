"""Durable queue rows for asynchronous Solution generation."""

from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.sales.models import SolutionGenerationJob, SolutionGenerationJobStatus
from apps.sales.tests.test_solution_persistence_service import (  # noqa: F401
    persistence_context,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def job_context(persistence_context):
    owner, _customer, opportunity, analysis, _create_analysis = persistence_context
    return owner, opportunity, analysis


def _create_job(owner, opportunity, analysis, **overrides):
    values = {
        "workflow_id": uuid4(),
        "opportunity": opportunity,
        "requirement_analysis": analysis,
        "requested_by": owner,
    }
    values.update(overrides)
    return SolutionGenerationJob.objects.create(**values)


def test_a_new_job_waits_in_the_queue(job_context):
    owner, opportunity, analysis = job_context

    job = _create_job(owner, opportunity, analysis)

    assert job.status == SolutionGenerationJobStatus.QUEUED
    assert job.attempts == 0
    assert job.error_code == ""
    assert job.started_at is None and job.finished_at is None


def test_the_same_workflow_cannot_be_queued_twice(job_context):
    owner, opportunity, analysis = job_context
    workflow_id = uuid4()
    _create_job(owner, opportunity, analysis, workflow_id=workflow_id)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _create_job(owner, opportunity, analysis, workflow_id=workflow_id)


def test_a_running_job_must_record_when_it_started(job_context):
    owner, opportunity, analysis = job_context

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _create_job(
                owner, opportunity, analysis,
                status=SolutionGenerationJobStatus.RUNNING,
            )


def test_a_terminal_job_must_record_when_it_finished(job_context):
    owner, opportunity, analysis = job_context

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _create_job(
                owner, opportunity, analysis,
                status=SolutionGenerationJobStatus.SUCCEEDED,
                started_at=timezone.now(),
            )
