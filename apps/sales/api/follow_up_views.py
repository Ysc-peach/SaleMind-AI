"""Follow-up task endpoints.

Collection reads are nested under the opportunity so the visibility rule is the
same one every other opportunity endpoint uses; mutations address a task by its
own id and re-derive the opportunity from it.
"""

from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.throttling import ScopedActionThrottleMixin

from apps.sales.models import FollowUpTask
from apps.sales.services import follow_ups as service
from apps.sales.services.follow_ups import FollowUpError, FollowUpErrorCode
from apps.sales.services.visibility import visible_opportunities_for

from .follow_up_serializers import (
    FollowUpTaskCreateSerializer,
    FollowUpTaskSerializer,
    FollowUpTaskUpdateSerializer,
)
from .opportunity_access import OpportunityVisibilityMixin
from .pagination import DefaultPageNumberPagination
from .permissions import SolutionDraftPermission
from .record_state import RecordInactive


def _translate(error: FollowUpError):
    """One place that turns a service refusal into the matching HTTP shape."""

    if error.code == FollowUpErrorCode.FORBIDDEN:
        raise PermissionDenied("只有该商机的负责人可以处理这条跟进。")
    if error.code == FollowUpErrorCode.INACTIVE_OPPORTUNITY:
        raise RecordInactive()
    raise ValidationError({"title": "请填写 1-200 个字符的事项。"})


class OpportunityFollowUpViewSet(
    ScopedActionThrottleMixin,
    OpportunityVisibilityMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    pagination_class = DefaultPageNumberPagination
    lookup_url_kwarg = "opportunity_id"
    http_method_names = ["get", "post", "head", "options"]

    def list_tasks(self, request, *args, **kwargs):
        opportunity = self.get_object()
        tasks = opportunity.follow_up_tasks.select_related("owner").all()
        wanted = (request.query_params.get("status") or "open").strip().lower()
        if wanted in {"open", "done"}:
            tasks = tasks.filter(status=wanted)
        elif wanted != "all":
            raise ValidationError({"status": "Expected open, done or all."})
        page = self.paginate_queryset(tasks)
        serializer = FollowUpTaskSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def create_task(self, request, *args, **kwargs):
        opportunity = self.get_object()
        serializer = FollowUpTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            task = service.create_task(
                opportunity=opportunity,
                actor=request.user,
                title=serializer.validated_data["title"],
                due_on=serializer.validated_data["due_on"],
                owner=serializer.validated_data.get("owner"),
            )
        except FollowUpError as error:
            _translate(error)
        return Response(
            FollowUpTaskSerializer(task).data, status=status.HTTP_201_CREATED
        )


class FollowUpTaskViewSet(
    ScopedActionThrottleMixin, viewsets.GenericViewSet
):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    http_method_names = ["patch", "post", "head", "options"]

    def _task(self):
        task = (
            FollowUpTask.objects.select_related("opportunity", "owner")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if task is None or not visible_opportunities_for(
            self.request.user
        ).filter(pk=task.opportunity_id).exists():
            # Same answer for "does not exist" and "not yours": an id probe must
            # not reveal which opportunities someone else has.
            raise NotFound()
        return task

    def partial_update(self, request, *args, **kwargs):
        task = self._task()
        serializer = FollowUpTaskUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            task = service.update_task(
                task, actor=request.user, **serializer.validated_data
            )
        except FollowUpError as error:
            _translate(error)
        return Response(FollowUpTaskSerializer(task).data)

    def complete(self, request, *args, **kwargs):
        task = self._task()
        try:
            task = service.complete_task(task, actor=request.user)
        except FollowUpError as error:
            _translate(error)
        return Response(FollowUpTaskSerializer(task).data)

    def reopen(self, request, *args, **kwargs):
        task = self._task()
        try:
            task = service.reopen_task(task, actor=request.user)
        except FollowUpError as error:
            _translate(error)
        return Response(FollowUpTaskSerializer(task).data)


class MyFollowUpAPIView(APIView):
    """What this person owes now, split by urgency.

    Presales has no workspace endpoint of its own, so this one answers for every
    business role instead of living under the sales dashboard.
    """

    permission_classes = (SolutionDraftPermission,)
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        buckets = service.follow_up_buckets(request.user)
        serializer = FollowUpTaskSerializer
        return Response(
            {
                "today": buckets["today"],
                "overdue": serializer(buckets["overdue"], many=True).data,
                "due_soon": serializer(buckets["due_soon"], many=True).data,
                "counts": {
                    "overdue": len(buckets["overdue"]),
                    "due_soon": len(buckets["due_soon"]),
                },
            }
        )
