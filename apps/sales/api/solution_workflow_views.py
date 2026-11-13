"""Thin HTTP transport around the durable Solution review workflow."""

from __future__ import annotations

from uuid import UUID, uuid5

from django.core.exceptions import ObjectDoesNotExist
from langgraph.types import Command
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.sales.models import (
    OpportunityRequirementAnalysis,
    SolutionDraftRecord,
    SolutionReview,
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)
from apps.sales.services.solution_review import (
    SolutionReviewPermissionError,
    SolutionReviewStateError,
    recover_completed_solution_review,
    recover_pending_solution_review,
)
from apps.sales.services.solution_generation_capacity import (
    GenerationCapacityReached,
    generation_slot,
)
from apps.sales.services.solution_review_workflow import (
    SolutionWorkflowOutcome,
    SolutionWorkflowStage,
    build_solution_review_graph,
    can_recover_terminal_review_submission,
)
from apps.sales.services.solution_workflow_checkpoint import (
    open_solution_workflow_checkpointer,
)

from config.throttling import ScopedActionThrottleMixin
from apps.sales.services.visibility import (
    visible_opportunities_for,
    visible_solution_drafts_for,
)
from .permissions import SolutionDraftPermission
from .solution_workflow_serializers import (
    SolutionWorkflowResumeSerializer,
    SolutionWorkflowStartSerializer,
)


_WORKFLOW_NAMESPACE = UUID("0fdcb6d5-95b1-4d5e-b2ce-3a08e2b183cc")
_HTTP_TO_GRAPH_ACTION = {
    "SUBMIT_FOR_REVIEW": "submit_for_review",
    "APPROVE": "approve",
    "REQUEST_REVISION": "request_revision",
}


class SolutionWorkflowConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "workflow_conflict"
    default_detail = "The workflow state has changed. Refresh and try again."

    def __init__(self, code="workflow_conflict", message=None):
        super().__init__(
            {
                "code": code,
                "message": message or "The workflow state has changed. Refresh and try again.",
            }
        )


class SolutionWorkflowFailed(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "workflow_failed"
    default_detail = "The Solution workflow could not be completed."

    def __init__(self, code="workflow_failed"):
        super().__init__(
            {
                "code": code,
                "message": "The Solution workflow could not be completed.",
            }
        )


class SolutionWorkflowCapacity(APIException):
    """Every generation slot is busy; retrying later is the only safe action."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "workflow_capacity_reached"

    def __init__(self):
        super().__init__(
            {
                "code": "workflow_capacity_reached",
                "message": (
                    "Another generation is already running. Retry in a minute."
                ),
            }
        )


class SolutionWorkflowCollectionViewSet(
    ScopedActionThrottleMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    http_method_names = ["post", "head", "options"]
    scoped_throttle_actions = {"start": "solution_generation"}

    def start(self, request, *args, **kwargs):
        serializer = SolutionWorkflowStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        opportunity = visible_opportunities_for(request.user).filter(
            pk=kwargs["opportunity_id"]
        ).first()
        if opportunity is None:
            raise NotFound()
        analysis = OpportunityRequirementAnalysis.objects.filter(
            pk=serializer.validated_data["analysis_id"],
            opportunity=opportunity,
        ).first()
        if analysis is None:
            raise ValidationError(
                {"analysis_id": "The analysis does not belong to this opportunity."}
            )
        workflow_id = _workflow_id_for_request(
            request,
            opportunity_id=opportunity.pk,
            analysis_id=analysis.pk,
        )
        config = _graph_config(workflow_id)
        with open_solution_workflow_checkpointer() as checkpointer:
            graph = build_solution_review_graph(checkpointer)
            existing = checkpointer.get_tuple(config)
            if existing is not None:
                projection = _project_workflow(
                    graph,
                    config,
                    workflow_id,
                    request.user,
                )
                return Response(projection)
            try:
                with generation_slot():
                    result = graph.invoke(
                        {
                            "workflow_run_id": str(workflow_id),
                            "opportunity_id": opportunity.pk,
                            "requirement_analysis_id": analysis.pk,
                            "requested_by_id": request.user.pk,
                            "workflow_stage": "ready",
                        },
                        config,
                    )
            except GenerationCapacityReached:
                raise SolutionWorkflowCapacity() from None
            _raise_failed_outcome(result)
            projection = _project_workflow(
                graph,
                config,
                workflow_id,
                request.user,
            )
        return Response(projection, status=status.HTTP_201_CREATED)


class SolutionWorkflowDetailViewSet(
    ScopedActionThrottleMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    http_method_names = ["get", "post", "head", "options"]
    scoped_throttle_actions = {"resume": "solution_generation"}

    def retrieve_workflow(self, request, *args, **kwargs):
        workflow_id = kwargs["workflow_id"]
        with open_solution_workflow_checkpointer() as checkpointer:
            graph = build_solution_review_graph(checkpointer)
            projection = _project_workflow(
                graph,
                _graph_config(workflow_id),
                workflow_id,
                request.user,
            )
        return Response(projection)

    def resume(self, request, *args, **kwargs):
        serializer = SolutionWorkflowResumeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workflow_id = kwargs["workflow_id"]
        config = _graph_config(workflow_id)
        with open_solution_workflow_checkpointer() as checkpointer:
            graph = build_solution_review_graph(checkpointer)
            current = _project_workflow(
                graph,
                config,
                workflow_id,
                request.user,
            )
            action = serializer.validated_data["action"]
            recovered = _recover_committed_http_replay(
                current,
                action=action,
                actor=request.user,
                return_reason=serializer.validated_data.get("return_reason", ""),
                comment=serializer.validated_data.get("comment", ""),
            )
            if recovered:
                return Response(
                    _project_workflow(
                        graph,
                        config,
                        workflow_id,
                        request.user,
                    )
                )
            if action not in current["allowed_actions"]:
                raise SolutionWorkflowConflict("workflow_decision_conflict")
            resume = {
                "actor_id": request.user.pk,
                "action": _HTTP_TO_GRAPH_ACTION[action],
            }
            if action == "REQUEST_REVISION":
                resume["return_reason"] = serializer.validated_data["return_reason"]
                resume["comment"] = serializer.validated_data["comment"]
            state = dict(graph.get_state(config).values)
            draft = SolutionDraftRecord.objects.filter(pk=current["solution_draft_id"]).first()
            if (
                action == "SUBMIT_FOR_REVIEW" and draft is not None
                and can_recover_terminal_review_submission(
                    state, draft, request.user, workflow_id=workflow_id,
                )
            ):
                # Append an explicit human submit to the existing thread. Never
                # restart generation, delete the failed checkpoint or fake review.
                resumed_config = graph.update_state(config, {
                    "actor_id": request.user.pk, "human_action": "submit_for_review",
                    "workflow_stage": SolutionWorkflowStage.WAITING_FOR_SALES_CONFIRMATION.value,
                    "workflow_outcome": SolutionWorkflowOutcome.WAITING_FOR_SALES_CONFIRMATION.value,
                    "error_code": "", "submission_error_code": "",
                }, as_node="wait_for_sales_confirmation")
                result = graph.invoke(None, resumed_config)
            else:
                result = graph.invoke(Command(resume=resume), config)
            _raise_failed_outcome(result)
            projection = _project_workflow(
                graph,
                config,
                workflow_id,
                request.user,
            )
        return Response(projection)


def _workflow_id_for_request(request, *, opportunity_id: int, analysis_id: int) -> UUID:
    raw_key = request.headers.get("Idempotency-Key")
    if raw_key is None or not raw_key.strip():
        # A server-generated key would make every replay a new paid generation.
        raise ValidationError(
            {"idempotency_key": "Idempotency-Key is required."}
        )
    try:
        key = UUID(raw_key)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(
            {"idempotency_key": "Idempotency-Key must be a UUID."}
        ) from exc
    return uuid5(
        _WORKFLOW_NAMESPACE,
        f"{request.user.pk}:{opportunity_id}:{analysis_id}:{key}",
    )


def _graph_config(workflow_id: UUID) -> dict:
    return {"configurable": {"thread_id": str(workflow_id)}}


def _project_workflow(graph, config, workflow_id: UUID, actor) -> dict:
    snapshot = graph.get_state(config)
    state = dict(snapshot.values)
    if not state:
        raise NotFound()
    draft = None
    draft_id = state.get("solution_draft_id")
    if draft_id is not None:
        draft = visible_solution_drafts_for(actor).filter(pk=draft_id).first()
        if draft is None:
            raise NotFound()
    else:
        opportunity_id = state.get("opportunity_id")
        if not visible_opportunities_for(actor).filter(pk=opportunity_id).exists():
            raise NotFound()
    return _business_projection(workflow_id, state, draft, actor=actor)


def _business_projection(workflow_id: UUID, state: dict, draft, *, actor=None) -> dict:
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
            and terminal_outcome
            in {
                SolutionWorkflowOutcome.BLOCKED.value,
                SolutionWorkflowOutcome.CONFLICT.value,
                SolutionWorkflowOutcome.FAILED.value,
            }
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


def _recover_committed_http_replay(
    current: dict,
    *,
    action: str,
    actor,
    return_reason: str,
    comment: str,
) -> bool:
    try:
        solution = SolutionDraftRecord.objects.get(pk=current["solution_draft_id"])
        if (
            current["status"] == "WAITING_FOR_PRESALES_REVIEW"
            and action == "SUBMIT_FOR_REVIEW"
        ):
            recover_pending_solution_review(solution, actor=actor)
            return True
        if current["status"] == "APPROVED" and action == "APPROVE":
            review = SolutionReview.objects.get(pk=current["solution_review_id"])
            recover_completed_solution_review(
                solution,
                review,
                actor=actor,
                expected_status=SolutionReviewDecisionStatus.APPROVED,
            )
            return True
        if (
            current["status"]
            in {"CUSTOMER_INFO_REQUIRED", "TECHNICAL_REVISION_REQUIRED"}
            and action == "REQUEST_REVISION"
        ):
            review = SolutionReview.objects.get(pk=current["solution_review_id"])
            recover_completed_solution_review(
                solution,
                review,
                actor=actor,
                expected_status=SolutionReviewDecisionStatus.RETURNED,
                return_reason=return_reason,
                comment=comment,
            )
            return True
    except SolutionReviewPermissionError as exc:
        error = APIException(
            {"code": exc.code, "message": exc.safe_message},
            code=exc.code,
        )
        error.status_code = status.HTTP_403_FORBIDDEN
        raise error from exc
    except (ObjectDoesNotExist, SolutionReviewStateError) as exc:
        raise SolutionWorkflowConflict("workflow_decision_conflict") from exc
    return False


def _raise_failed_outcome(result: dict) -> None:
    outcome = result.get("workflow_outcome")
    if outcome == "blocked":
        raise SolutionWorkflowConflict(result.get("error_code") or "workflow_blocked")
    if outcome == "conflict":
        raise SolutionWorkflowConflict(result.get("error_code") or "workflow_conflict")
    if outcome == "failed":
        raise SolutionWorkflowFailed(result.get("error_code") or "workflow_failed")
