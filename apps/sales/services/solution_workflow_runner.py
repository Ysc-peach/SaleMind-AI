"""Run one Solution workflow step without importing request/response objects.

The worker that executes queued generation and the HTTP view that starts a
workflow must share exactly one implementation: the LangGraph invocation, the
capacity slot and the public projection. Everything here is HTTP-agnostic, so a
background process can reuse it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from apps.sales.models import (
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)
from apps.sales.services.solution_generation_capacity import generation_slot
from apps.sales.services.solution_review_workflow import (
    SolutionWorkflowOutcome,
    SolutionWorkflowStage,
    build_solution_review_graph,
    can_recover_terminal_review_submission,
)
from apps.sales.services.solution_workflow_checkpoint import (
    open_solution_workflow_checkpointer,
)
from apps.sales.services.visibility import (
    visible_opportunities_for,
    visible_solution_drafts_for,
)


_FAILED_OUTCOMES = {
    SolutionWorkflowOutcome.BLOCKED.value,
    SolutionWorkflowOutcome.CONFLICT.value,
    SolutionWorkflowOutcome.FAILED.value,
}


class WorkflowStateNotFound(Exception):
    """The thread has no state, or the actor may not see the object it points at."""


class WorkflowFailedOutcome(Exception):
    """The graph finished in a terminal failure outcome."""

    def __init__(self, outcome: str, error_code: str):
        self.outcome = outcome
        self.error_code = error_code
        super().__init__(outcome)


@dataclass(frozen=True)
class WorkflowStartResult:
    projection: dict
    created: bool
    outcome: str = ""
    error_code: str = ""


def failed_outcome(result: dict) -> tuple[str, str] | None:
    """Return ``(outcome, error_code)`` when a graph result is a terminal failure."""

    outcome = str(result.get("workflow_outcome") or "")
    if outcome not in _FAILED_OUTCOMES:
        return None
    return outcome, str(result.get("error_code") or "")


def graph_config(workflow_id: UUID) -> dict:
    return {"configurable": {"thread_id": str(workflow_id)}}


def project_workflow(graph, config, workflow_id: UUID, actor) -> dict:
    snapshot = graph.get_state(config)
    state = dict(snapshot.values)
    if not state:
        raise WorkflowStateNotFound()
    draft = None
    draft_id = state.get("solution_draft_id")
    if draft_id is not None:
        draft = visible_solution_drafts_for(actor).filter(pk=draft_id).first()
        if draft is None:
            raise WorkflowStateNotFound()
    else:
        opportunity_id = state.get("opportunity_id")
        if not visible_opportunities_for(actor).filter(pk=opportunity_id).exists():
            raise WorkflowStateNotFound()
    return business_projection(workflow_id, state, draft, actor=actor)


def business_projection(workflow_id: UUID, state: dict, draft, *, actor=None) -> dict:
    review = None
    if draft is not None:
        review = draft.reviews.order_by("-submitted_at", "-id").first()
    if draft is not None and draft.review_status == SolutionReviewStatus.APPROVED:
        public_status = "APPROVED"
        allowed_actions = []
    elif draft is not None and draft.review_status == SolutionReviewStatus.NEEDS_REVISION:
        public_status = (
            review.return_reason.upper()
            if review is not None and review.return_reason
            else "BLOCKED"
        )
        allowed_actions = []
    elif draft is not None and draft.review_status == SolutionReviewStatus.PENDING_REVIEW:
        public_status = "WAITING_FOR_PRESALES_REVIEW"
        allowed_actions = ["APPROVE", "REQUEST_REVISION"]
        pending = draft.reviews.filter(
            status=SolutionReviewDecisionStatus.PENDING
        ).first()
        if pending is not None:
            review = pending
    elif draft is not None and draft.review_status == SolutionReviewStatus.DRAFT:
        terminal_outcome = str(state.get("workflow_outcome", "")).lower()
        if (
            state.get("workflow_stage") == SolutionWorkflowStage.TERMINAL.value
            and terminal_outcome in _FAILED_OUTCOMES
        ):
            if actor is not None and can_recover_terminal_review_submission(
                state, draft, actor, workflow_id=workflow_id,
            ):
                public_status = "WAITING_FOR_SALES_CONFIRMATION"
                allowed_actions = ["SUBMIT_FOR_REVIEW"]
            else:
                public_status = terminal_outcome.upper()
                allowed_actions = []
        else:
            public_status = "WAITING_FOR_SALES_CONFIRMATION"
            allowed_actions = ["SUBMIT_FOR_REVIEW"]
    else:
        public_status = str(state.get("workflow_outcome", "FAILED")).upper()
        allowed_actions = []
    return {
        "workflow_id": str(workflow_id),
        "status": public_status,
        "solution_draft_id": draft.pk if draft is not None else state.get("solution_draft_id"),
        "solution_version": draft.version if draft is not None else state.get("solution_version"),
        "solution_review_id": review.pk if review is not None else state.get("solution_review_id"),
        "reviewer_id": review.reviewer_id if review is not None else state.get("reviewer_id"),
        "allowed_actions": allowed_actions,
        "error_code": state.get("error_code", ""),
    }


def start_workflow(*, workflow_id: UUID, opportunity, analysis, actor) -> WorkflowStartResult:
    """Start generation for one thread, or replay an existing one.

    Raises ``GenerationCapacityReached`` when every slot is busy; the caller
    decides how to surface that (429 over HTTP, retry later in the worker).
    """

    config = graph_config(workflow_id)
    with open_solution_workflow_checkpointer() as checkpointer:
        graph = build_solution_review_graph(checkpointer)
        if checkpointer.get_tuple(config) is not None:
            projection = project_workflow(graph, config, workflow_id, actor)
            return WorkflowStartResult(
                projection=projection,
                created=False,
                outcome=projection["status"].lower(),
                error_code=projection["error_code"],
            )
        with generation_slot():
            result = graph.invoke(
                {
                    "workflow_run_id": str(workflow_id),
                    "opportunity_id": opportunity.pk,
                    "requirement_analysis_id": analysis.pk,
                    "requested_by_id": actor.pk,
                    "workflow_stage": "ready",
                },
                config,
            )
        outcome = str(result.get("workflow_outcome") or "")
        error_code = str(result.get("error_code") or "")
        projection = project_workflow(graph, config, workflow_id, actor)
    if outcome in _FAILED_OUTCOMES:
        raise WorkflowFailedOutcome(outcome, error_code)
    return WorkflowStartResult(
        projection=projection,
        created=True,
        outcome=outcome,
        error_code=error_code,
    )
