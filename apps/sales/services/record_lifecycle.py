"""Archiving and restoring, with the decision recorded next to the flag.

The flag alone answers "is this still worked on". The audit answers "who decided
that, and when", which is a different question and the one people ask later.
Keeping both writes in one function means a future endpoint cannot flip the flag
and forget the trail.
"""

from __future__ import annotations

from django.db import transaction

from apps.sales.models import RecordStateChange

CUSTOMER = RecordStateChange.Kind.CUSTOMER
OPPORTUNITY = RecordStateChange.Kind.OPPORTUNITY


def set_record_active(
    record, *, actor, active: bool, kind: str, name: str
):
    """Move a record between active and archived, recording who did it."""

    if record.is_active == active:
        # No change, no event: re-archiving an archived record is not a decision.
        return record
    with transaction.atomic():
        record.is_active = active
        record.save(update_fields=["is_active", "updated_at"])
        RecordStateChange.objects.create(
            kind=kind,
            record_id=record.pk,
            record_name=name[:200],
            is_active=active,
            actor=actor,
        )
    return record
