"""Thin LangGraph orchestration around persisted Solution review services."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from django.db import connection
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from psycopg.conninfo import make_conninfo

from apps.accounts.models import UserRole
from apps.sales.models import (
    Customer,
    Opportunity,
    OpportunityRequirementAnalysis,
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)
from apps.sales.services.solution_review import (
    approve_solution_draft,
    request_solution_draft_revision,
)
from apps.sales.tests.solution_fakes import analysis_payload


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def workflow_context(make_user, monkeypatch):
    sales = make_user(UserRole.SALES)
    presales = make_user(UserRole.PRESALES)
    other_presales = make_user(UserRole.PRESALES)
    unrelated_sales = make_user(UserRole.SALES)
    customer = Customer.objects.create(name="Workflow customer", created_by=sales)
    opportunity = Opportunity.objects.create(
        project_name="Workflow opportunity",
        customer=customer,
        sales_owner=sales,
        presales_owner=presales,
        created_by=sales,
    )
    payload = analysis_payload()
    analysis = OpportunityRequirementAnalysis.objects.create(
        opportunity=opportunity,
        created_by=sales,
        summary=payload["summary"],
        requirements=payload["requirements"],
        conflicts=payload["conflicts"],
        clarifying_questions=payload["clarifying_questions"],
        source_raw_requirement="synthetic workflow input",
        source_context={},
        analysis_version="v1",
        llm_provider="fake",
        llm_model="fake-model",
    )
    calls = []

    def generate(actual_opportunity, actual_analysis, *, created_by, idempotency_key, **kwargs):
        calls.append(
            {
                "opportunity_id": actual_opportunity.pk,
                "analysis_id": actual_analysis.pk,
                "created_by_id": created_by.pk,
                "idempotency_key": idempotency_key,
            }
        )
        existing = SolutionDraftRecord.objects.filter(
            generation_idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing
        return SolutionDraftRecord.objects.create(
            opportunity=actual_opportunity,
            requirement_analysis=actual_analysis,
            version=actual_opportunity.solution_drafts.count() + 1,
            title="Workflow solution",
            draft_payload={
                "title": "Workflow solution",
                "executive_summary": [],
                "solution_sections": [],
                "assumptions": [],
            },
            generation_metadata={"generation_status": "generated"},
            generation_idempotency_key=idempotency_key,
            created_by=created_by,
        )

    from apps.sales.services import solution_review_workflow

    monkeypatch.setattr(
        solution_review_workflow,
        "generate_and_persist_solution_draft",
        generate,
    )
    return {
        "sales": sales,
        "presales": presales,
        "other_presales": other_presales,
        "unrelated_sales": unrelated_sales,
        "opportunity": opportunity,
        "analysis": analysis,
        "generation_calls": calls,
    }


def _initial(context, *, workflow_run_id=None):
    return {
        "workflow_run_id": str(workflow_run_id or uuid4()),
        "opportunity_id": context["opportunity"].pk,
        "requirement_analysis_id": context["analysis"].pk,
        "requested_by_id": context["sales"].pk,
        "workflow_stage": "ready",
    }


def _compiled():
    from apps.sales.services.solution_review_workflow import build_solution_review_graph

    return build_solution_review_graph(InMemorySaver())


def _config(thread_id=None):
    return {"configurable": {"thread_id": thread_id or str(uuid4())}}


def _interrupt_value(result):
    assert "__interrupt__" in result
    return result["__interrupt__"][0].value


def _test_database_conninfo():
    params = connection.get_connection_params()
    return make_conninfo(
        **{
            key: params[key]
            for key in ("dbname", "user", "password", "host", "port")
            if params.get(key) not in (None, "")
        }
    )


def test_explicit_analysis_reaches_generation_and_pending_review_precedes_interrupt(
    workflow_context,
):
    graph = _compiled()
    state = _initial(workflow_context)

    result = graph.invoke(state, _config())

    call = workflow_context["generation_calls"][0]
    assert call["analysis_id"] == workflow_context["analysis"].pk
    assert call["idempotency_key"] == UUID(state["workflow_run_id"])
    solution = SolutionDraftRecord.objects.get(pk=result["solution_draft_id"])
    review = SolutionReview.objects.get(pk=result["solution_review_id"])
    assert solution.requirement_analysis_id == workflow_context["analysis"].pk
    assert solution.review_status == SolutionReviewStatus.PENDING_REVIEW
    assert review.status == SolutionReviewDecisionStatus.PENDING
    assert result["workflow_outcome"] == "waiting_for_review"


def test_interrupt_payload_contains_only_minimal_non_sensitive_ids(workflow_context):
    result = _compiled().invoke(_initial(workflow_context), _config())

    payload = _interrupt_value(result)

    assert set(payload) == {
        "solution_draft_id",
        "solution_review_id",
        "reviewer_id",
        "allowed_actions",
    }
    assert payload["allowed_actions"] == ["approve", "request_revision"]
    serialized = repr(payload).lower()
    assert "draft_payload" not in serialized
    assert "api_key" not in serialized
    assert "evidence" not in serialized


def test_approve_resume_calls_service_and_finishes(workflow_context):
    graph = _compiled()
    config = _config()
    graph.invoke(_initial(workflow_context), config)

    result = graph.invoke(
        Command(
            resume={
                "actor_id": workflow_context["presales"].pk,
                "action": "approve",
            }
        ),
        config,
    )

    solution = SolutionDraftRecord.objects.get(pk=result["solution_draft_id"])
    review = SolutionReview.objects.get(pk=result["solution_review_id"])
    assert result["workflow_outcome"] == "approved"
    assert solution.review_status == SolutionReviewStatus.APPROVED
    assert review.status == SolutionReviewDecisionStatus.APPROVED


@pytest.mark.parametrize(
    ("reason", "expected_outcome"),
    [
        (SolutionReturnReason.CUSTOMER_INFO_REQUIRED, "customer_info_required"),
        (SolutionReturnReason.TECHNICAL_REVISION_REQUIRED, "technical_revision_required"),
    ],
)
def test_revision_resume_routes_both_terminal_reasons(
    workflow_context,
    reason,
    expected_outcome,
):
    graph = _compiled()
    config = _config()
    graph.invoke(_initial(workflow_context), config)

    result = graph.invoke(
        Command(
            resume={
                "actor_id": workflow_context["presales"].pk,
                "action": "request_revision",
                "return_reason": reason,
                "comment": "Please revise the persisted version.",
            }
        ),
        config,
    )

    review = SolutionReview.objects.get(pk=result["solution_review_id"])
    assert result["workflow_outcome"] == expected_outcome
    assert review.status == SolutionReviewDecisionStatus.RETURNED
    assert review.return_reason == reason


def test_committed_approve_before_checkpoint_replay_recovers_terminal_state(
    workflow_context,
):
    graph = _compiled()
    config = _config()
    interrupted = graph.invoke(_initial(workflow_context), config)
    solution = SolutionDraftRecord.objects.get(pk=interrupted["solution_draft_id"])
    approve_solution_draft(solution, actor=workflow_context["presales"])

    result = graph.invoke(
        Command(resume={"actor_id": workflow_context["presales"].pk, "action": "approve"}),
        config,
    )

    assert result["workflow_outcome"] == "approved"
    assert SolutionReview.objects.filter(solution_draft=solution).count() == 1


def test_committed_return_before_checkpoint_replay_recovers_exact_decision(
    workflow_context,
):
    graph = _compiled()
    config = _config()
    interrupted = graph.invoke(_initial(workflow_context), config)
    solution = SolutionDraftRecord.objects.get(pk=interrupted["solution_draft_id"])
    reason = SolutionReturnReason.CUSTOMER_INFO_REQUIRED
    comment = "Need the customer database version."
    request_solution_draft_revision(
        solution,
        actor=workflow_context["presales"],
        return_reason=reason,
        comment=comment,
    )

    result = graph.invoke(
        Command(
            resume={
                "actor_id": workflow_context["presales"].pk,
                "action": "request_revision",
                "return_reason": reason,
                "comment": comment,
            }
        ),
        config,
    )

    assert result["workflow_outcome"] == "customer_info_required"
    assert SolutionReview.objects.filter(solution_draft=solution).count() == 1


def test_conflicting_replay_decision_fails_closed_without_rewriting_history(
    workflow_context,
):
    graph = _compiled()
    config = _config()
    interrupted = graph.invoke(_initial(workflow_context), config)
    solution = SolutionDraftRecord.objects.get(pk=interrupted["solution_draft_id"])
    approve_solution_draft(solution, actor=workflow_context["presales"])

    result = graph.invoke(
        Command(
            resume={
                "actor_id": workflow_context["presales"].pk,
                "action": "request_revision",
                "return_reason": SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
                "comment": "Conflicting replay must not win.",
            }
        ),
        config,
    )

    solution.refresh_from_db()
    review = SolutionReview.objects.get(solution_draft=solution)
    assert result["workflow_outcome"] == "conflict"
    assert solution.review_status == SolutionReviewStatus.APPROVED
    assert review.status == SolutionReviewDecisionStatus.APPROVED


def test_graph_never_mutates_solution_payload(workflow_context):
    graph = _compiled()
    config = _config()
    interrupted = graph.invoke(_initial(workflow_context), config)
    solution = SolutionDraftRecord.objects.get(pk=interrupted["solution_draft_id"])
    original = deepcopy(solution.draft_payload)

    graph.invoke(
        Command(resume={"actor_id": workflow_context["presales"].pk, "action": "approve"}),
        config,
    )

    solution.refresh_from_db()
    assert solution.draft_payload == original


def test_graph_reuses_opportunity_visibility_instead_of_reimplementing_permission(
    workflow_context,
):
    state = _initial(workflow_context)
    state["requested_by_id"] = workflow_context["unrelated_sales"].pk

    result = _compiled().invoke(state, _config())

    assert result["workflow_outcome"] == "failed"
    assert workflow_context["generation_calls"] == []
    assert SolutionDraftRecord.objects.count() == 0


def test_presales_authored_workflow_delegates_independent_reviewer_selection(
    workflow_context,
):
    state = _initial(workflow_context)
    state["requested_by_id"] = workflow_context["presales"].pk
    state["reviewer_id"] = workflow_context["other_presales"].pk

    result = _compiled().invoke(state, _config())

    review = SolutionReview.objects.get(pk=result["solution_review_id"])
    assert review.reviewer_id == workflow_context["other_presales"].pk
    assert result["workflow_outcome"] == "waiting_for_review"


def test_presales_authored_workflow_self_review_is_blocked_by_existing_service(
    workflow_context,
):
    state = _initial(workflow_context)
    state["requested_by_id"] = workflow_context["presales"].pk
    state["reviewer_id"] = workflow_context["presales"].pk

    result = _compiled().invoke(state, _config())

    assert result["workflow_outcome"] == "blocked"
    assert not SolutionReview.objects.exists()


def test_stale_submit_is_blocked_by_existing_review_service(
    workflow_context,
    monkeypatch,
):
    from apps.sales.services import solution_review_workflow

    generate = solution_review_workflow.generate_and_persist_solution_draft

    def generate_then_supersede(*args, **kwargs):
        record = generate(*args, **kwargs)
        analysis = workflow_context["analysis"]
        OpportunityRequirementAnalysis.objects.create(
            opportunity=analysis.opportunity,
            created_by=analysis.created_by,
            summary="Newer workflow analysis",
            requirements=analysis.requirements,
            conflicts=analysis.conflicts,
            clarifying_questions=analysis.clarifying_questions,
            source_raw_requirement=analysis.source_raw_requirement,
            source_context=analysis.source_context,
            analysis_version="v2",
            llm_provider="fake",
            llm_model="fake-model",
        )
        return record

    monkeypatch.setattr(
        solution_review_workflow,
        "generate_and_persist_solution_draft",
        generate_then_supersede,
    )

    result = _compiled().invoke(_initial(workflow_context), _config())

    solution = SolutionDraftRecord.objects.get(pk=result["solution_draft_id"])
    from apps.sales.services.solution_persistence import evaluate_solution_draft_stale_reasons

    assert result["workflow_outcome"] == "blocked"
    assert "newer_requirement_analysis" in evaluate_solution_draft_stale_reasons(solution)
    assert not SolutionReview.objects.exists()


def test_generation_service_failure_becomes_typed_failed_outcome_without_review(
    workflow_context,
    monkeypatch,
):
    from apps.sales.services import solution_review_workflow
    from apps.sales.services.solution_persistence import SolutionPersistenceError

    def fail(*args, **kwargs):
        raise SolutionPersistenceError()

    monkeypatch.setattr(
        solution_review_workflow,
        "generate_and_persist_solution_draft",
        fail,
    )

    result = _compiled().invoke(_initial(workflow_context), _config())

    assert result["workflow_outcome"] == "failed"
    assert result["error_code"] == "solution_generation_failed"
    assert not SolutionDraftRecord.objects.exists()
    assert not SolutionReview.objects.exists()


def test_postgres_checkpoint_survives_graph_and_connection_reconstruction(
    workflow_context,
):
    from apps.sales.services.solution_review_workflow import build_solution_review_graph
    from apps.sales.services.solution_workflow_checkpoint import (
        open_solution_workflow_checkpointer,
        setup_solution_workflow_checkpoint_schema,
    )

    conninfo = _test_database_conninfo()
    setup_solution_workflow_checkpoint_schema(conninfo)
    config = _config()
    initial = _initial(workflow_context)

    with open_solution_workflow_checkpointer(conninfo) as first_checkpointer:
        first_graph = build_solution_review_graph(first_checkpointer)
        interrupted = first_graph.invoke(initial, config)
        _interrupt_value(interrupted)

    with open_solution_workflow_checkpointer(conninfo) as reconstructed_checkpointer:
        reconstructed_graph = build_solution_review_graph(reconstructed_checkpointer)
        result = reconstructed_graph.invoke(
            Command(
                resume={
                    "actor_id": workflow_context["presales"].pk,
                    "action": "approve",
                }
            ),
            config,
        )

    assert result["workflow_outcome"] == "approved"
    assert SolutionReview.objects.get(pk=result["solution_review_id"]).status == "approved"


def test_postgres_checkpoint_reconstruction_routes_revision_from_database_state(
    workflow_context,
):
    from apps.sales.services.solution_review_workflow import build_solution_review_graph
    from apps.sales.services.solution_workflow_checkpoint import (
        open_solution_workflow_checkpointer,
        setup_solution_workflow_checkpoint_schema,
    )

    conninfo = _test_database_conninfo()
    setup_solution_workflow_checkpoint_schema(conninfo)
    config = _config()
    reason = SolutionReturnReason.TECHNICAL_REVISION_REQUIRED

    with open_solution_workflow_checkpointer(conninfo) as first_checkpointer:
        interrupted = build_solution_review_graph(first_checkpointer).invoke(
            _initial(workflow_context),
            config,
        )
        persisted_review_id = interrupted["solution_review_id"]
        _interrupt_value(interrupted)

    with open_solution_workflow_checkpointer(conninfo) as reconstructed_checkpointer:
        result = build_solution_review_graph(reconstructed_checkpointer).invoke(
            Command(
                resume={
                    "actor_id": workflow_context["presales"].pk,
                    "action": "request_revision",
                    "return_reason": reason,
                    "comment": "Revise the technical design.",
                }
            ),
            config,
        )

    review = SolutionReview.objects.get(pk=persisted_review_id)
    assert result["workflow_outcome"] == "technical_revision_required"
    assert review.status == SolutionReviewDecisionStatus.RETURNED
    assert review.return_reason == reason


def test_checkpoint_configuration_is_explicit_and_test_settings_hold_no_secret():
    from django.conf import settings
    from apps.sales.services.solution_workflow_checkpoint import (
        SolutionWorkflowCheckpointConfigurationError,
        open_solution_workflow_checkpointer,
    )

    assert settings.LANGGRAPH_CHECKPOINT_DATABASE_URL == ""
    with pytest.raises(SolutionWorkflowCheckpointConfigurationError):
        with open_solution_workflow_checkpointer():
            pass
