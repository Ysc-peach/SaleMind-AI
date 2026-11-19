"""Dated follow-up actions on an opportunity.

Everything else in this domain records what already happened. A follow-up is the
only object about the future, so it carries the two things a to-do needs to be
useful: who owes it and when it is due.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import FollowUpTask, FollowUpTaskStatus
from apps.sales.services.visibility import visible_opportunities_for

TITLE_MAX_LENGTH = 200
DUE_SOON_DAYS = 7

_BUSINESS_ROLES = (UserRole.SALES, UserRole.PRESALES, UserRole.ADMIN)


class FollowUpErrorCode(StrEnum):
    INVALID_INPUT = "follow_up_invalid_input"
    FORBIDDEN = "follow_up_forbidden"
    INACTIVE_OPPORTUNITY = "follow_up_opportunity_inactive"


class FollowUpError(Exception):
    def __init__(self, code: FollowUpErrorCode):
        super().__init__(code.value)
        self.code = code


def _runs_the_opportunity(opportunity, actor) -> bool:
    """The two owners and an administrator may act on an opportunity."""

    if actor.role == UserRole.ADMIN:
        return True
    return actor.pk in {
        opportunity.sales_owner_id,
        opportunity.presales_owner_id,
    }


def _may_manage(task: FollowUpTask, actor) -> bool:
    return task.owner_id == actor.pk or _runs_the_opportunity(
        task.opportunity, actor
    )


def create_task(
    *,
    opportunity,
    actor,
    title: str,
    due_on: date,
    owner=None,
) -> FollowUpTask:
    cleaned = " ".join((title or "").split())
    if not cleaned or len(cleaned) > TITLE_MAX_LENGTH or due_on is None:
        raise FollowUpError(FollowUpErrorCode.INVALID_INPUT)
    # Same rule as generation: an archived opportunity takes no new work.
    if not opportunity.is_active:
        raise FollowUpError(FollowUpErrorCode.INACTIVE_OPPORTUNITY)
    if not _runs_the_opportunity(opportunity, actor):
        raise FollowUpError(FollowUpErrorCode.FORBIDDEN)
    assignee = owner or actor
    if assignee.role not in _BUSINESS_ROLES or not assignee.is_active:
        raise FollowUpError(FollowUpErrorCode.INVALID_INPUT)
    with transaction.atomic():
        return FollowUpTask.objects.create(
            opportunity=opportunity,
            title=cleaned,
            due_on=due_on,
            owner=assignee,
            created_by=actor,
        )


def complete_task(task: FollowUpTask, *, actor) -> FollowUpTask:
    """Mark done; repeating the call is a no-op rather than an error."""

    if not _may_manage(task, actor):
        raise FollowUpError(FollowUpErrorCode.FORBIDDEN)
    if task.status == FollowUpTaskStatus.DONE:
        return task
    with transaction.atomic():
        FollowUpTask.objects.filter(pk=task.pk, status=FollowUpTaskStatus.OPEN).update(
            status=FollowUpTaskStatus.DONE,
            completed_at=timezone.now(),
            updated_at=timezone.now(),
        )
    task.refresh_from_db()
    return task


def reopen_task(task: FollowUpTask, *, actor) -> FollowUpTask:
    if not _may_manage(task, actor):
        raise FollowUpError(FollowUpErrorCode.FORBIDDEN)
    if task.status == FollowUpTaskStatus.OPEN:
        return task
    with transaction.atomic():
        FollowUpTask.objects.filter(pk=task.pk).update(
            status=FollowUpTaskStatus.OPEN,
            completed_at=None,
            updated_at=timezone.now(),
        )
    task.refresh_from_db()
    return task


def update_task(task: FollowUpTask, *, actor, **changes) -> FollowUpTask:
    """Edit the title, the date or the assignee, validating the same rules."""

    if not _may_manage(task, actor):
        raise FollowUpError(FollowUpErrorCode.FORBIDDEN)
    values = {}
    if "title" in changes:
        cleaned = " ".join((changes["title"] or "").split())
        if not cleaned or len(cleaned) > TITLE_MAX_LENGTH:
            raise FollowUpError(FollowUpErrorCode.INVALID_INPUT)
        values["title"] = cleaned
    if "due_on" in changes:
        if changes["due_on"] is None:
            raise FollowUpError(FollowUpErrorCode.INVALID_INPUT)
        values["due_on"] = changes["due_on"]
    if "owner" in changes:
        assignee = changes["owner"]
        if assignee.role not in _BUSINESS_ROLES or not assignee.is_active:
            raise FollowUpError(FollowUpErrorCode.INVALID_INPUT)
        values["owner"] = assignee
    if not values:
        return task
    with transaction.atomic():
        FollowUpTask.objects.filter(pk=task.pk).update(
            updated_at=timezone.now(), **values
        )
    task.refresh_from_db()
    return task


def open_tasks_for(user, *, today: date | None = None):
    """Open tasks on the opportunities this user can already see."""

    return (
        FollowUpTask.objects.filter(
            status=FollowUpTaskStatus.OPEN,
            opportunity__in=visible_opportunities_for(user),
        )
        .select_related("opportunity", "owner")
        .order_by("due_on", "id")
    )


def follow_up_buckets(user, *, today: date | None = None) -> dict:
    """Two lists, because "late" and "this week" call for different reactions."""

    today = today or timezone.localdate()
    queryset = open_tasks_for(user, today=today)
    return {
        "today": today.isoformat(),
        "overdue": list(queryset.filter(due_on__lt=today)),
        "due_soon": list(
            queryset.filter(
                due_on__gte=today,
                due_on__lte=today + timedelta(days=DUE_SOON_DAYS),
            )
        ),
    }


def overdue_tasks(*, today: date | None = None):
    """Every overdue open task, for the scheduled check."""

    today = today or timezone.localdate()
    return (
        FollowUpTask.objects.filter(
            status=FollowUpTaskStatus.OPEN, due_on__lt=today
        )
        .select_related("opportunity", "owner")
        .order_by("due_on", "id")
    )
