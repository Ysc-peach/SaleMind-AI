"""Thin HTTP transport around the durable Solution review workflow."""

from __future__ import annotations

from uuid import UUID, uuid5

from django.core.exceptions import ObjectDoesNotExist
from langgraph.types import Command
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from django.conf import settings

from apps.sales.models import (
    OpportunityRequirementAnalysis,
    SolutionDraftRecord,
    SolutionGenerationJob,
    SolutionGenerationJobStatus,
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
)
from apps.sales.services.solution_workflow_runner import (
    WorkflowFailedOutcome,
    WorkflowStateNotFound,
    failed_outcome,
    graph_config,
    project_workflow,
    start_workflow,
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
        if settings.SOLUTION_GENERATION_ASYNC:
            job, created = SolutionGenerationJob.objects.get_or_create(
                workflow_id=workflow_id,
                defaults={
                    "opportunity": opportunity,
                    "requirement_analysis": analysis,
                    "requested_by": request.user,
                },
            )
            if (
                job.opportunity_id != opportunity.pk
                or job.requirement_analysis_id != analysis.pk
                or job.requested_by_id != request.user.pk
            ):
                raise SolutionWorkflowConflict("workflow_input_mismatch")
            if job.status in _ACTIVE_JOB_STATUSES or (
                job.status == SolutionGenerationJobStatus.FAILED
            ):
                return Response(
                    _job_projection(job),
                    status=(
                        status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
                    ),
                )
            # A succeeded job falls through: the draft exists, so the normal
            # projection answers with the real version and review state.
        try:
            result = start_workflow(
                workflow_id=workflow_id,
                opportunity=opportunity,
                analysis=analysis,
                actor=request.user,
            )
        except GenerationCapacityReached:
            raise SolutionWorkflowCapacity() from None
        except WorkflowStateNotFound:
            raise NotFound() from None
        except WorkflowFailedOutcome as error:
            if error.outcome == "failed":
                raise SolutionWorkflowFailed(
                    error.error_code or "workflow_failed"
                ) from None
            raise SolutionWorkflowConflict(
                error.error_code or "workflow_blocked"
            ) from None
        return Response(
            result.projection,
            status=(
                status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
            ),
        )


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
        if settings.SOLUTION_GENERATION_ASYNC:
            job = SolutionGenerationJob.objects.filter(
                workflow_id=workflow_id
            ).first()
            if job is not None and (
                job.status != SolutionGenerationJobStatus.SUCCEEDED
            ):
                # The worker has not produced a draft yet, so there is no
                # checkpoint to project. Visibility follows the opportunity.
                if not visible_opportunities_for(request.user).filter(
                    pk=job.opportunity_id
                ).exists():
                    raise NotFound()
                return Response(_job_projection(job))
        with open_solution_workflow_checkpointer() as checkpointer:
            graph = build_solution_review_graph(checkpointer)
            projection = _projection(
                graph,
                graph_config(workflow_id),
                workflow_id,
                request.user,
            )
        return Response(projection)

    def resume(self, request, *args, **kwargs):
        serializer = SolutionWorkflowResumeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workflow_id = kwargs["workflow_id"]
        config = graph_config(workflow_id)
        with open_solution_workflow_checkpointer() as checkpointer:
            graph = build_solution_review_graph(checkpointer)
            current = _projection(
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
                    _projection(
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
            projection = _projection(
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


def _projection(graph, config, workflow_id: UUID, actor) -> dict:
    """Translate the domain "not visible" signal into an HTTP 404."""

    try:
        return project_workflow(graph, config, workflow_id, actor)
    except WorkflowStateNotFound:
        raise NotFound() from None


_ACTIVE_JOB_STATUSES = frozenset({
    SolutionGenerationJobStatus.QUEUED,
    SolutionGenerationJobStatus.RUNNING,
})


def _job_projection(job) -> dict:
    """Public shape while the worker still owns the run.

    It mirrors the synchronous projection so a client can poll the same endpoint
    and only has to watch for ``solution_draft_id`` becoming present.
    """

    return {
        "workflow_id": str(job.workflow_id),
        "status": str(job.status).upper(),
        "solution_draft_id": None,
        "solution_version": None,
        "solution_review_id": None,
        "reviewer_id": None,
        "allowed_actions": [],
        "error_code": job.error_code,
    }


def _raise_failed_outcome(result: dict) -> None:
    """Translate a terminal graph outcome into the matching HTTP error."""

    failure = failed_outcome(result)
    if failure is None:
        return
    outcome, error_code = failure
    if outcome == "failed":
        raise SolutionWorkflowFailed(error_code or "workflow_failed")
    raise SolutionWorkflowConflict(error_code or "workflow_blocked")


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



