"""Audited human disposition of proposed enterprise grounding facts."""

from collections.abc import Iterable

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus,
)


def actor_can_review_grounding_facts(actor) -> bool:
    """Require both Django Admin access and the project's business-admin role."""

    user_model = get_user_model()
    return bool(
        isinstance(actor, user_model)
        and actor.pk is not None
        and actor.is_active
        and actor.is_staff
        and actor.role == UserRole.ADMIN
    )


def approve_grounding_facts(fact_ids: Iterable[int], *, actor) -> int:
    """Approve current proposals as one short, audited database operation."""

    ids = _validated_ids(fact_ids)
    _require_reviewer(actor)
    with transaction.atomic():
        facts = list(
            EnterpriseGroundingFact.objects.select_for_update()
            .filter(pk__in=ids)
            .order_by("pk")
        )
        _require_exact_set(facts, ids)
        if any(
            fact.is_stale
            or fact.approval_status
            != EnterpriseGroundingFactApprovalStatus.PROPOSED
            for fact in facts
        ):
            raise ValueError("Only current proposed facts can be approved.")
        approved_at = timezone.now()
        for fact in facts:
            fact.approval_status = EnterpriseGroundingFactApprovalStatus.APPROVED
            fact.approved_by = actor
            fact.approved_at = approved_at
        EnterpriseGroundingFact.objects.bulk_update(
            facts,
            ["approval_status", "approved_by", "approved_at"],
        )
    return len(facts)


def reject_grounding_facts(fact_ids: Iterable[int], *, actor) -> int:
    """Reject current proposals without retaining approval metadata."""

    ids = _validated_ids(fact_ids)
    _require_reviewer(actor)
    with transaction.atomic():
        facts = list(
            EnterpriseGroundingFact.objects.select_for_update()
            .filter(pk__in=ids)
            .order_by("pk")
        )
        _require_exact_set(facts, ids)
        if any(
            fact.approval_status
            != EnterpriseGroundingFactApprovalStatus.PROPOSED
            for fact in facts
        ):
            raise ValueError("Only proposed facts can be rejected.")
        for fact in facts:
            fact.approval_status = EnterpriseGroundingFactApprovalStatus.REJECTED
            fact.approved_by = None
            fact.approved_at = None
        EnterpriseGroundingFact.objects.bulk_update(
            facts,
            ["approval_status", "approved_by", "approved_at"],
        )
    return len(facts)


def _require_reviewer(actor) -> None:
    if not actor_can_review_grounding_facts(actor):
        raise PermissionError("Grounding fact review requires an active business admin.")


def _validated_ids(fact_ids: Iterable[int]) -> tuple[int, ...]:
    try:
        ids = tuple(fact_ids)
    except TypeError:
        raise ValueError("Fact identifiers are invalid.") from None
    if (
        not ids
        or len(ids) != len(set(ids))
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in ids
        )
    ):
        raise ValueError("Fact identifiers are invalid.")
    return ids


def _require_exact_set(facts, ids: tuple[int, ...]) -> None:
    if {fact.pk for fact in facts} != set(ids):
        raise ValueError("One or more grounding facts do not exist.")
