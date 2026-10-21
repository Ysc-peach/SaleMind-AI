"""Recover manual review submission, never generation or a completed decision."""

from copy import deepcopy
from contextlib import contextmanager
from uuid import uuid4

import pytest

from apps.sales.models import OpportunityRequirementAnalysis, SolutionDraftRecord, SolutionReview
from apps.sales.services.solution_review_workflow import build_solution_review_graph
from apps.sales.api import solution_workflow_views
from apps.sales.tests.test_solution_review_workflow_api import (
    workflow_api_context, _client, _start, _resume, _status_url,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _legacy_block(context, *, state_changes=None):
    started = _start(context).json()
    config = {"configurable": {"thread_id": started["workflow_id"]}}
    with solution_workflow_views.open_solution_workflow_checkpointer() as saver:
        graph = build_solution_review_graph(saver)
        # Reproduce the pre-fix terminal checkpoint, with no review committed.
        graph.update_state(config, {
            "workflow_stage": "terminal", "workflow_outcome": "blocked",
            "error_code": "solution_review_submit_blocked", "human_action": "submit_for_review",
            "actor_id": context["sales"].pk, **(state_changes or {}),
        }, as_node="approve")
    return started, config


def _read_state(config):
    with solution_workflow_views.open_solution_workflow_checkpointer() as saver:
        return build_solution_review_graph(saver).get_state(config)


def _supersede_analysis(context):
    previous = context["analysis"]
    OpportunityRequirementAnalysis.objects.create(
        opportunity=context["opportunity"], created_by=context["sales"],
        summary="Customer confirmed newer facts", requirements=previous.requirements,
        conflicts=previous.conflicts, clarifying_questions=previous.clarifying_questions,
        source_raw_requirement=previous.source_raw_requirement, source_context=previous.source_context,
        analysis_version="v2", llm_provider="fake", llm_model="fake-model",
    )


@pytest.mark.parametrize("problem", ["missing", "inactive"])
def test_corrected_reviewer_can_resubmit_without_regeneration(workflow_api_context, problem):
    c = workflow_api_context
    if problem == "missing":
        c["opportunity"].presales_owner = None
        c["opportunity"].save(update_fields=["presales_owner"])
    else:
        c["presales"].is_active = False
        c["presales"].save(update_fields=["is_active"])
    started = _start(c).json()
    failed = _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"})
    assert failed.status_code == 409
    expected = "solution_review_missing_reviewer" if problem == "missing" else "solution_review_invalid_reviewer"
    assert failed.json()["code"] == expected
    assert not SolutionReview.objects.exists()

    c["presales"].is_active = True
    c["presales"].save(update_fields=["is_active"])
    assigned = _client(c["sales"]).patch(
        f'/api/opportunities/{c["opportunity"].pk}/', {"presales_owner": c["presales"].pk}, format="json",
    )
    assert assigned.status_code == 200
    status = _client(c["sales"]).get(_status_url(started["workflow_id"])).json()
    assert status["allowed_actions"] == ["SUBMIT_FOR_REVIEW"]
    submitted = _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"})
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "WAITING_FOR_PRESALES_REVIEW"
    assert SolutionReview.objects.get().reviewer_id == c["presales"].pk
    assert SolutionDraftRecord.objects.count() == 1
    assert len(c["generation_calls"]) == 1


def test_legacy_get_offers_recovery_without_mutating_checkpoint_or_solution(workflow_api_context):
    c = workflow_api_context
    started, config = _legacy_block(c)
    before = _read_state(config)
    solution = SolutionDraftRecord.objects.get(pk=started["solution_draft_id"])
    payload = deepcopy(solution.draft_payload)
    response = _client(c["sales"]).get(_status_url(started["workflow_id"]))
    assert response.status_code == 200
    assert response.json()["status"] == "WAITING_FOR_SALES_CONFIRMATION"
    assert response.json()["allowed_actions"] == ["SUBMIT_FOR_REVIEW"]
    after = _read_state(config)
    assert after.config == before.config
    assert after.values == before.values
    solution.refresh_from_db()
    assert solution.review_status == "draft"
    assert solution.draft_payload == payload
    assert not SolutionReview.objects.exists()


def test_legacy_manual_recovery_preserves_checkpoint_history_and_supports_review(workflow_api_context):
    c = workflow_api_context
    started, config = _legacy_block(c)
    original = deepcopy(SolutionDraftRecord.objects.get(pk=started["solution_draft_id"]).draft_payload)
    recovered = _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"})
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "WAITING_FOR_PRESALES_REVIEW"
    replay = _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"})
    assert replay.status_code == 200
    assert SolutionReview.objects.count() == 1
    approved = _resume(c, started["workflow_id"], {"action": "APPROVE"}, user=c["presales"])
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert SolutionReview.objects.get().status == "approved"
    assert SolutionDraftRecord.objects.get().draft_payload == original
    assert len(c["generation_calls"]) == 1
    with solution_workflow_views.open_solution_workflow_checkpointer() as saver:
        history = list(build_solution_review_graph(saver).get_state_history(config))
    assert any(s.values.get("error_code") == "solution_review_submit_blocked" for s in history)


@pytest.mark.parametrize("problem", ["missing", "inactive", "self", "stale", "known_permission_failure"])
def test_legacy_recovery_remains_closed_when_current_business_checks_fail(workflow_api_context, problem):
    c = workflow_api_context
    overrides = {"submission_error_code": "solution_review_permission_denied"} if problem == "known_permission_failure" else None
    started, config = _legacy_block(c, state_changes=overrides)
    if problem == "missing":
        c["opportunity"].presales_owner = None
        c["opportunity"].save(update_fields=["presales_owner"])
    elif problem == "inactive":
        c["presales"].is_active = False
        c["presales"].save(update_fields=["is_active"])
    elif problem == "self":
        SolutionDraftRecord.objects.filter(pk=started["solution_draft_id"]).update(created_by=c["presales"])
    elif problem == "stale":
        _supersede_analysis(c)
    before = _read_state(config)
    status = _client(c["sales"]).get(_status_url(started["workflow_id"]))
    assert status.json()["allowed_actions"] == []
    result = _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"})
    assert result.status_code == 409
    assert _read_state(config).config == before.config
    assert not SolutionReview.objects.exists()
    # A read-only recovery check must detect new evidence without marking it stale.
    assert not SolutionDraftRecord.objects.get(pk=started["solution_draft_id"]).is_stale


@pytest.mark.parametrize("overrides", [
    {"error_code": "solution_generation_failed", "workflow_outcome": "failed"},
    {"error_code": "solution_review_approve_blocked"},
    {"error_code": "review_decision_conflict", "workflow_outcome": "conflict"},
    {"solution_version": 99},
    {"opportunity_id": -1},
])
def test_unrelated_terminal_failure_or_mismatched_checkpoint_is_not_recoverable(workflow_api_context, overrides):
    c = workflow_api_context
    started, config = _legacy_block(c, state_changes=overrides)
    before = _read_state(config)
    status = _client(c["sales"]).get(_status_url(started["workflow_id"]))
    assert status.json()["allowed_actions"] == []
    assert _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"}).status_code == 409
    assert _read_state(config).config == before.config
    assert not SolutionReview.objects.exists()


def test_recovery_does_not_grant_other_sales_visibility_or_submission(workflow_api_context):
    c = workflow_api_context
    started, config = _legacy_block(c)
    before = _read_state(config)
    assert _client(c["other_sales"]).get(_status_url(started["workflow_id"])).status_code == 404
    assert _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"}, user=c["other_sales"]).status_code == 404
    assert _read_state(config).config == before.config
    assert not SolutionReview.objects.exists()


def test_current_state_is_revalidated_after_recovery_action_is_offered(workflow_api_context):
    c = workflow_api_context
    started, config = _legacy_block(c)
    status = _client(c["sales"]).get(_status_url(started["workflow_id"]))
    assert status.json()["allowed_actions"] == ["SUBMIT_FOR_REVIEW"]
    c["opportunity"].presales_owner = None
    c["opportunity"].save(update_fields=["presales_owner"])
    before = _read_state(config)
    assert _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"}).status_code == 409
    assert _read_state(config).config == before.config
    assert not SolutionReview.objects.exists()


def test_checkpoint_copied_to_another_thread_cannot_recover_that_solution(workflow_api_context):
    c = workflow_api_context
    started, config = _legacy_block(c)
    state = dict(_read_state(config).values)
    foreign_id = str(uuid4())
    foreign_config = {"configurable": {"thread_id": foreign_id}}
    with solution_workflow_views.open_solution_workflow_checkpointer() as saver:
        graph = build_solution_review_graph(saver)
        graph.update_state(foreign_config, state, as_node="approve")
    before = _read_state(foreign_config)
    response = _client(c["sales"]).get(_status_url(foreign_id))
    assert response.json()["allowed_actions"] == []
    assert _resume(c, foreign_id, {"action": "SUBMIT_FOR_REVIEW"}).status_code == 409
    assert _read_state(foreign_config).config == before.config
    assert not SolutionReview.objects.exists()


def test_legacy_recovery_survives_real_postgres_checkpointer_reconstruction(workflow_api_context, monkeypatch):
    from apps.sales.services.solution_workflow_checkpoint import (
        open_solution_workflow_checkpointer, setup_solution_workflow_checkpoint_schema,
    )
    from apps.sales.tests.test_solution_review_workflow import _test_database_conninfo

    conninfo = _test_database_conninfo()
    setup_solution_workflow_checkpoint_schema(conninfo)

    @contextmanager
    def open_test_checkpointer():
        with open_solution_workflow_checkpointer(conninfo) as saver:
            yield saver

    monkeypatch.setattr(solution_workflow_views, "open_solution_workflow_checkpointer", open_test_checkpointer)
    c = workflow_api_context
    started, config = _legacy_block(c)
    blocked_checkpoint = _read_state(config).config
    assert _client(c["sales"]).get(_status_url(started["workflow_id"])).json()["allowed_actions"] == ["SUBMIT_FOR_REVIEW"]
    submitted = _resume(c, started["workflow_id"], {"action": "SUBMIT_FOR_REVIEW"})
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "WAITING_FOR_PRESALES_REVIEW"
    pending = _read_state(config)
    assert pending.next == ("wait_for_presales_review",)
    assert SolutionReview.objects.count() == 1
    assert len(c["generation_calls"]) == 1
    with open_test_checkpointer() as saver:
        history = list(build_solution_review_graph(saver).get_state_history(config))
    assert any(s.config == blocked_checkpoint for s in history)
