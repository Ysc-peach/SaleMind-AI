"""Async mode: the start endpoint enqueues instead of holding the request."""

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.sales.models import SolutionGenerationJob
from apps.sales.tests.test_solution_review_workflow_api import (  # noqa: F401
    _client,
    _start,
    _status_url,
    workflow_api_context,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def async_mode(settings):
    settings.SOLUTION_GENERATION_ASYNC = True


def test_start_enqueues_a_job_and_returns_202(async_mode, workflow_api_context):
    response = _start(workflow_api_context)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["solution_draft_id"] is None
    assert body["allowed_actions"] == []
    assert not workflow_api_context["generation_calls"]
    assert SolutionGenerationJob.objects.count() == 1


def test_duplicate_start_reuses_the_queued_job(async_mode, workflow_api_context):
    key = uuid4()

    first = _start(workflow_api_context, key=key)
    second = _start(workflow_api_context, key=key)

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["workflow_id"] == second.json()["workflow_id"]
    assert SolutionGenerationJob.objects.count() == 1
    assert not workflow_api_context["generation_calls"]


def test_status_reports_the_queue_position(async_mode, workflow_api_context):
    started = _start(workflow_api_context).json()

    response = _client(workflow_api_context["sales"]).get(
        _status_url(started["workflow_id"])
    )

    assert response.status_code == 200
    assert response.json()["status"] == "QUEUED"
    assert response.json()["solution_draft_id"] is None


def test_a_failed_job_exposes_only_its_error_code(async_mode, workflow_api_context):
    started = _start(workflow_api_context).json()
    now = timezone.now()
    SolutionGenerationJob.objects.filter(
        workflow_id=started["workflow_id"]
    ).update(
        status="failed",
        started_at=now,
        finished_at=now,
        error_code="solution_draft_not_grounded",
    )

    response = _client(workflow_api_context["sales"]).get(
        _status_url(started["workflow_id"])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["error_code"] == "solution_draft_not_grounded"
    assert body["solution_draft_id"] is None


def test_another_sales_user_cannot_poll_the_job(async_mode, workflow_api_context):
    started = _start(workflow_api_context).json()

    response = _client(workflow_api_context["other_sales"]).get(
        _status_url(started["workflow_id"])
    )

    assert response.status_code == 404
