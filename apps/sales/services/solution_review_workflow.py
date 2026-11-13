"""LangGraph orchestration for one persisted Solution review attempt.

Business permissions, state transitions, persistence, and stale checks remain in
the existing Django services. This module stores only workflow routing state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict
from uuid import UUID
import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import OperationalError

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from apps.accounts.models import UserRole
from apps.knowledge.exceptions import KnowledgeDocumentError
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.sales.services.visibility import visible_opportunities_for
from apps.sales.models import (
    Opportunity,
    OpportunityRequirementAnalysis,
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewDecisionStatus,
)
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode
from apps.sales.services.solution_grounding import SolutionDraftGroundingError
from apps.sales.services.solution_log_context import solution_log_scope
from apps.sales.services.solution_persistence import (
    SolutionPersistenceError,
    SolutionReadinessBlockedError,
    generate_and_persist_solution_draft,
)
from apps.sales.services.solution_review import (
    SolutionReviewError,
    SolutionReviewErrorCode,
    approve_solution_draft,
    recover_completed_solution_review,
    recover_pending_solution_review,
    request_solution_draft_revision,
    submit_solution_draft_for_review,
    validate_solution_review_submission,
)


logger = logging.getLogger(__name__)
_REPAIRABLE_REVIEWER_ERRORS = {
    SolutionReviewErrorCode.MISSING_REVIEWER.value,
    SolutionReviewErrorCode.INVALID_REVIEWER.value,
}


class SolutionWorkflowStage(StrEnum):
    READY = "ready"
    GENERATED = "generated"
    WAITING_FOR_SALES_CONFIRMATION = "waiting_for_sales_confirmation"
    WAITING_FOR_PRESALES_REVIEW = "waiting_for_presales_review"
    DECIDING = "deciding"
    TERMINAL = "terminal"


class SolutionWorkflowOutcome(StrEnum):
    GENERATED = "generated"
    WAITING_FOR_SALES_CONFIRMATION = "waiting_for_sales_confirmation"
    WAITING_FOR_PRESALES_REVIEW = "waiting_for_presales_review"
    APPROVED = "approved"
    CUSTOMER_INFO_REQUIRED = "customer_info_required"
    TECHNICAL_REVISION_REQUIRED = "technical_revision_required"
    BLOCKED = "blocked"
    CONFLICT = "conflict"
    FAILED = "failed"


class SolutionHumanAction(StrEnum):
    SUBMIT_FOR_REVIEW = "submit_for_review"
    APPROVE = "approve"
    REQUEST_REVISION = "request_revision"


class SolutionReviewWorkflowState(TypedDict, total=False):
    workflow_run_id: str
    opportunity_id: int
    requirement_analysis_id: int
    requested_by_id: int
    solution_draft_id: int
    solution_version: int
    solution_review_id: int
    reviewer_id: int
    workflow_stage: str
    workflow_outcome: str
    human_action: str
    actor_id: int
    return_reason: str
    comment: str
    error_code: str
    submission_error_code: str


def build_solution_review_graph(checkpointer):
    """Compile the bounded workflow with an explicitly supplied checkpointer."""

    if checkpointer is None:
        raise ValueError("A persistent workflow checkpointer is required.")
    builder = StateGraph(SolutionReviewWorkflowState)
    builder.add_node("generate_solution", _generate_solution_node)
    builder.add_node(
        "wait_for_sales_confirmation",
        _wait_for_sales_confirmation_node,
    )
    builder.add_node("submit_review", _submit_review_node)
    builder.add_node("wait_for_presales_review", _wait_for_presales_review_node)
    builder.add_node("approve", _approve_node)
    builder.add_node("request_revision", _request_revision_node)
    builder.add_edge(START, "generate_solution")
    builder.add_conditional_edges(
        "generate_solution",
        _route_after_generation,
        {"wait": "wait_for_sales_confirmation", "end": END},
    )
    builder.add_conditional_edges(
        "wait_for_sales_confirmation",
        _route_sales_confirmation,
        {
            SolutionHumanAction.SUBMIT_FOR_REVIEW.value: "submit_review",
            "end": END,
        },
    )
    builder.add_conditional_edges(
        "submit_review",
        _route_after_submit,
        {"wait": "wait_for_presales_review", "retry": "wait_for_sales_confirmation", "end": END},
    )
    builder.add_conditional_edges(
        "wait_for_presales_review",
        _route_presales_action,
        {
            SolutionHumanAction.APPROVE.value: "approve",
            SolutionHumanAction.REQUEST_REVISION.value: "request_revision",
            "end": END,
        },
    )
    builder.add_edge("approve", END)
    builder.add_edge("request_revision", END)
    return builder.compile(checkpointer=checkpointer)


def _generate_solution_node(state: SolutionReviewWorkflowState) -> dict:
    try:
        workflow_key = UUID(state["workflow_run_id"])
        requested_by = get_user_model().objects.get(pk=state["requested_by_id"], is_active=True)
        opportunity = visible_opportunities_for(requested_by).get(
            pk=state["opportunity_id"]
        )
        analysis = OpportunityRequirementAnalysis.objects.get(
            pk=state["requirement_analysis_id"],
            opportunity_id=opportunity.pk,
        )
        with solution_log_scope(workflow_key):
            record = generate_and_persist_solution_draft(
                opportunity,
                analysis,
                created_by=requested_by,
                idempotency_key=workflow_key,
                schema_version=2,
            )
    except (
        KeyError,
        ValueError,
        ObjectDoesNotExist,
        OperationalError,
        KnowledgeDocumentError,
        LLMProviderError,
        SolutionDraftError,
        SolutionDraftGroundingError,
        SolutionPersistenceError,
    ) as error:
        # Preserve the public failure/checkpoint contract; log no payload, cause,
        # exception message or traceback, even when an SDK exception has a body.
        diagnostic = {
            "opportunity_id": opportunity.pk if "opportunity" in locals() else None,
            "analysis_id": analysis.pk if "analysis" in locals() else None,
            "exception_class": type(error).__name__,
            "code": getattr(error, "code", "workflow_generation_error"),
            "category": "workflow_generation_error",
            "http_status": None,
        }
        if "workflow_key" in locals():
            diagnostic["workflow_id"] = str(workflow_key)
        if isinstance(error, LLMProviderError):
            diagnostic["category"] = error.failure_kind.value if error.failure_kind else "unknown_provider_error"
            diagnostic["http_status"] = error.http_status
        elif isinstance(error, SolutionDraftGroundingError):
            diagnostic["category"] = "grounding_rejection"
        elif isinstance(error, SolutionReadinessBlockedError):
            diagnostic["category"] = "requirement_readiness"
        logger.warning("Solution workflow generation failed: %s", diagnostic,
                       extra={"solution_workflow_failure": diagnostic})
        if isinstance(error, SolutionDraftGroundingError):
            return _failure(SolutionWorkflowOutcome.FAILED, error.code)
        if isinstance(error, SolutionReadinessBlockedError):
            return _failure(SolutionWorkflowOutcome.FAILED, error.code)
        if isinstance(error, LLMProviderError) and error.code in {item.value for item in LLMErrorCode}:
            return _failure(SolutionWorkflowOutcome.FAILED, error.code)
        if (
            isinstance(error, SolutionDraftError)
            and error.code in {
                SolutionDraftErrorCode.INSUFFICIENT_APPROVED_EVIDENCE.value,
                SolutionDraftErrorCode.INVALID_RESPONSE.value,
                SolutionDraftErrorCode.NO_PROPOSALS.value,
            }
        ):
            return _failure(SolutionWorkflowOutcome.FAILED, error.code)
        return _failure(SolutionWorkflowOutcome.FAILED, "solution_generation_failed")
    return {
        "solution_draft_id": record.pk,
        "solution_version": record.version,
        "workflow_stage": (
            SolutionWorkflowStage.WAITING_FOR_SALES_CONFIRMATION.value
        ),
        "workflow_outcome": (
            SolutionWorkflowOutcome.WAITING_FOR_SALES_CONFIRMATION.value
        ),
        "error_code": "",
    }


def _wait_for_sales_confirmation_node(state: SolutionReviewWorkflowState) -> dict:
    decision = interrupt(
        {
            "solution_draft_id": state["solution_draft_id"],
            "solution_version": state["solution_version"],
            "allowed_actions": [SolutionHumanAction.SUBMIT_FOR_REVIEW.value],
        }
    )
    if not isinstance(decision, dict):
        return _failure(SolutionWorkflowOutcome.CONFLICT, "invalid_sales_confirmation")
    action = decision.get("action")
    actor_id = decision.get("actor_id")
    if (
        action != SolutionHumanAction.SUBMIT_FOR_REVIEW
        or not isinstance(actor_id, int)
    ):
        return _failure(SolutionWorkflowOutcome.CONFLICT, "invalid_sales_confirmation")
    return {
        "human_action": action,
        "actor_id": actor_id,
        "error_code": "",
    }


def _submit_review_node(state: SolutionReviewWorkflowState) -> dict:
    try:
        solution = SolutionDraftRecord.objects.get(pk=state["solution_draft_id"])
        actor = get_user_model().objects.get(pk=state["actor_id"])
        reviewer = None
        if state.get("reviewer_id") is not None:
            reviewer = get_user_model().objects.get(pk=state["reviewer_id"])
        try:
            review = submit_solution_draft_for_review(
                solution,
                actor=actor,
                reviewer=reviewer,
            )
        except SolutionReviewError as submit_error:
            try:
                review = recover_pending_solution_review(
                    solution,
                    actor=actor,
                    expected_reviewer=reviewer,
                )
            except SolutionReviewError:
                raise submit_error
    except SolutionReviewError as error:
        diagnostic = {
            "solution_id": state.get("solution_draft_id"),
            "actor_id": state.get("actor_id"),
            "exception_class": type(error).__name__, "code": error.code,
        }
        logger.warning("Solution review submission rejected: %s", diagnostic,
                       extra={"solution_review_submission_failure": diagnostic})
        if actor.role == UserRole.SALES and error.code in _REPAIRABLE_REVIEWER_ERRORS:
            return {
                "workflow_stage": SolutionWorkflowStage.WAITING_FOR_SALES_CONFIRMATION.value,
                "workflow_outcome": SolutionWorkflowOutcome.BLOCKED.value,
                "error_code": error.code, "submission_error_code": error.code,
                "human_action": "",
            }
        return {**_failure(SolutionWorkflowOutcome.BLOCKED, "solution_review_submit_blocked"),
                "submission_error_code": error.code}
    except (KeyError, ObjectDoesNotExist):
        return _failure(SolutionWorkflowOutcome.BLOCKED, "solution_review_submit_blocked")
    return {
        "solution_review_id": review.pk,
        "reviewer_id": review.reviewer_id,
        "workflow_stage": SolutionWorkflowStage.WAITING_FOR_PRESALES_REVIEW.value,
        "workflow_outcome": SolutionWorkflowOutcome.WAITING_FOR_PRESALES_REVIEW.value,
        "human_action": "",
        "error_code": "",
        "submission_error_code": "",
    }


def can_recover_terminal_review_submission(state, solution, actor, *, workflow_id) -> bool:
    """Recognize only a failed submit for this exact, currently eligible version.

    Legacy checkpoints did not retain the underlying review error. They may be
    offered recovery only after the same business checks as a new submission.
    This function does not alter business data or checkpoint history.
    """
    if (
        state.get("workflow_stage") != SolutionWorkflowStage.TERMINAL.value
        or state.get("workflow_outcome") != SolutionWorkflowOutcome.BLOCKED.value
        or state.get("error_code") != "solution_review_submit_blocked"
        or state.get("submission_error_code", "") not in {"", *_REPAIRABLE_REVIEWER_ERRORS}
        or str(workflow_id) != str(solution.generation_idempotency_key)
        or state.get("workflow_run_id") != str(solution.generation_idempotency_key)
        or state.get("solution_draft_id") != solution.pk
        or state.get("solution_version") != solution.version
        or state.get("opportunity_id") != solution.opportunity_id
        or state.get("requirement_analysis_id") != solution.requirement_analysis_id
        or solution.reviews.exists()
    ):
        return False
    try:
        reviewer = None
        if state.get("reviewer_id") is not None:
            reviewer = get_user_model().objects.get(pk=state["reviewer_id"])
        validate_solution_review_submission(solution, actor=actor, reviewer=reviewer)
    except (ObjectDoesNotExist, SolutionReviewError):
        return False
    return True


def _wait_for_presales_review_node(state: SolutionReviewWorkflowState) -> dict:
    decision = interrupt(
        {
            "solution_draft_id": state["solution_draft_id"],
            "solution_review_id": state["solution_review_id"],
            "reviewer_id": state["reviewer_id"],
            "allowed_actions": [
                SolutionHumanAction.APPROVE.value,
                SolutionHumanAction.REQUEST_REVISION.value,
            ],
        }
    )
    if not isinstance(decision, dict):
        return _failure(SolutionWorkflowOutcome.CONFLICT, "invalid_human_decision")
    action = decision.get("action")
    actor_id = decision.get("actor_id")
    if action not in SolutionHumanAction._value2member_map_ or not isinstance(actor_id, int):
        return _failure(SolutionWorkflowOutcome.CONFLICT, "invalid_human_decision")
    update = {
        "human_action": action,
        "actor_id": actor_id,
        "workflow_stage": SolutionWorkflowStage.DECIDING.value,
        "error_code": "",
    }
    if action == SolutionHumanAction.REQUEST_REVISION:
        update["return_reason"] = decision.get("return_reason", "")
        update["comment"] = decision.get("comment", "")
    return update


def _approve_node(state: SolutionReviewWorkflowState) -> dict:
    try:
        solution, review, actor = _decision_objects(state)
        if review.status == SolutionReviewDecisionStatus.APPROVED:
            recover_completed_solution_review(
                solution,
                review,
                actor=actor,
                expected_status=SolutionReviewDecisionStatus.APPROVED,
            )
        elif review.status == SolutionReviewDecisionStatus.PENDING:
            approve_solution_draft(solution, actor=actor)
        else:
            return _failure(SolutionWorkflowOutcome.CONFLICT, "review_decision_conflict")
    except (KeyError, ObjectDoesNotExist, SolutionReviewError):
        return _failure(SolutionWorkflowOutcome.BLOCKED, "solution_review_approve_blocked")
    return _terminal(SolutionWorkflowOutcome.APPROVED)


def _request_revision_node(state: SolutionReviewWorkflowState) -> dict:
    reason = state.get("return_reason", "")
    comment = state.get("comment", "")
    if reason not in SolutionReturnReason.values or not isinstance(comment, str) or not comment.strip():
        return _failure(SolutionWorkflowOutcome.BLOCKED, "solution_review_revision_blocked")
    try:
        solution, review, actor = _decision_objects(state)
    except (KeyError, ObjectDoesNotExist):
        return _failure(SolutionWorkflowOutcome.BLOCKED, "solution_review_revision_blocked")
    if review.status == SolutionReviewDecisionStatus.RETURNED:
        try:
            recover_completed_solution_review(
                solution,
                review,
                actor=actor,
                expected_status=SolutionReviewDecisionStatus.RETURNED,
                return_reason=reason,
                comment=comment,
            )
        except SolutionReviewError:
            return _failure(SolutionWorkflowOutcome.CONFLICT, "review_decision_conflict")
    elif review.status == SolutionReviewDecisionStatus.PENDING:
        try:
            request_solution_draft_revision(
                solution,
                actor=actor,
                return_reason=reason,
                comment=comment,
            )
        except SolutionReviewError:
            return _failure(
                SolutionWorkflowOutcome.BLOCKED,
                "solution_review_revision_blocked",
            )
    else:
        return _failure(SolutionWorkflowOutcome.CONFLICT, "review_decision_conflict")
    outcome = (
        SolutionWorkflowOutcome.CUSTOMER_INFO_REQUIRED
        if reason == SolutionReturnReason.CUSTOMER_INFO_REQUIRED
        else SolutionWorkflowOutcome.TECHNICAL_REVISION_REQUIRED
    )
    return _terminal(outcome)


def _decision_objects(state: SolutionReviewWorkflowState):
    solution = SolutionDraftRecord.objects.get(pk=state["solution_draft_id"])
    review = SolutionReview.objects.get(
        pk=state["solution_review_id"],
        solution_draft_id=solution.pk,
    )
    actor = get_user_model().objects.get(pk=state["actor_id"])
    return solution, review, actor


def _route_after_generation(state: SolutionReviewWorkflowState) -> str:
    return (
        "wait"
        if state.get("workflow_outcome")
        == SolutionWorkflowOutcome.WAITING_FOR_SALES_CONFIRMATION
        else "end"
    )


def _route_sales_confirmation(state: SolutionReviewWorkflowState) -> str:
    action = state.get("human_action", "")
    return action if action == SolutionHumanAction.SUBMIT_FOR_REVIEW else "end"


def _route_after_submit(state: SolutionReviewWorkflowState) -> str:
    if (
        state.get("workflow_stage") == SolutionWorkflowStage.WAITING_FOR_SALES_CONFIRMATION
        and state.get("workflow_outcome") == SolutionWorkflowOutcome.BLOCKED
        and state.get("error_code") in _REPAIRABLE_REVIEWER_ERRORS
    ):
        return "retry"
    return (
        "wait"
        if state.get("workflow_outcome")
        == SolutionWorkflowOutcome.WAITING_FOR_PRESALES_REVIEW
        else "end"
    )


def _route_presales_action(state: SolutionReviewWorkflowState) -> str:
    action = state.get("human_action", "")
    return (
        action
        if action
        in {
            SolutionHumanAction.APPROVE.value,
            SolutionHumanAction.REQUEST_REVISION.value,
        }
        else "end"
    )


def _terminal(outcome: SolutionWorkflowOutcome) -> dict:
    return {
        "workflow_stage": SolutionWorkflowStage.TERMINAL.value,
        "workflow_outcome": outcome.value,
        "error_code": "",
    }


def _failure(outcome: SolutionWorkflowOutcome, error_code: str) -> dict:
    return {
        "workflow_stage": SolutionWorkflowStage.TERMINAL.value,
        "workflow_outcome": outcome.value,
        "error_code": error_code,
    }
