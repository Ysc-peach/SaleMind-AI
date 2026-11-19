"""Competitors, and the public statements that may be quoted about them.

Two rules shape this module:

* an entity is created freely so nobody is blocked in front of a customer, but
  every *claim* needs a human approval and a source link;
* a negative claim about a third party is refused outright. "X does not support
  Y" ages badly, cannot be defended without the vendor's own words, and is the
  fastest way to lose trust in a review meeting.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from urllib.parse import urlparse

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import (
    Competitor,
    CompetitorDimension,
    CompetitorStatement,
    CompetitorStatementStatus,
)

NAME_MAX_LENGTH = 120
ALIAS_MAX_LENGTH = 240
STATEMENT_MAX_LENGTH = 2000

_WRITERS = (UserRole.ADMIN, UserRole.PRESALES)
# Deliberately blunt: these phrasings assert something about a third party that
# the customer can check against the vendor's own material.
_NEGATIVE_PATTERNS = (
    "不支持",
    "尚未支持",
    "未提供",
    "无法",
    "缺少",
    "不具备",
    "尚未具备",
    "not support",
    "does not support",
    "no support for",
    "is unable to",
    "lacks ",
)
_NEGATIVE_RE = re.compile("|".join(re.escape(p) for p in _NEGATIVE_PATTERNS))


class CompetitorErrorCode(StrEnum):
    INVALID_INPUT = "competitor_invalid_input"
    FORBIDDEN = "competitor_forbidden"
    DUPLICATE_NAME = "competitor_duplicate_name"
    NEGATIVE_CLAIM = "competitor_negative_claim"
    INVALID_STATE = "competitor_statement_invalid_state"


class CompetitorError(Exception):
    def __init__(self, code: CompetitorErrorCode):
        super().__init__(code.value)
        self.code = code


def _require_writer(actor) -> None:
    if actor is None or actor.role not in _WRITERS:
        raise CompetitorError(CompetitorErrorCode.FORBIDDEN)


def _require_admin(actor) -> None:
    if actor is None or actor.role != UserRole.ADMIN:
        raise CompetitorError(CompetitorErrorCode.FORBIDDEN)


def _clean(value: str, *, limit: int) -> str:
    return " ".join((value or "").split())[:limit].strip()


def create_competitor(*, actor, name: str, aliases: str = "") -> Competitor:
    _require_writer(actor)
    cleaned = _clean(name, limit=NAME_MAX_LENGTH)
    if not cleaned:
        raise CompetitorError(CompetitorErrorCode.INVALID_INPUT)
    try:
        with transaction.atomic():
            return Competitor.objects.create(
                name=cleaned,
                aliases=_clean(aliases, limit=ALIAS_MAX_LENGTH),
                created_by=actor,
            )
    except IntegrityError:
        raise CompetitorError(CompetitorErrorCode.DUPLICATE_NAME) from None


def update_competitor(
    competitor: Competitor, *, actor, name: str | None = None, aliases: str | None = None
) -> Competitor:
    _require_writer(actor)
    if name is not None:
        cleaned = _clean(name, limit=NAME_MAX_LENGTH)
        if not cleaned:
            raise CompetitorError(CompetitorErrorCode.INVALID_INPUT)
        competitor.name = cleaned
    if aliases is not None:
        competitor.aliases = _clean(aliases, limit=ALIAS_MAX_LENGTH)
    try:
        with transaction.atomic():
            competitor.save()
    except IntegrityError:
        raise CompetitorError(CompetitorErrorCode.DUPLICATE_NAME) from None
    return competitor


def set_competitor_active(
    competitor: Competitor, *, actor, active: bool
) -> Competitor:
    _require_writer(actor)
    if competitor.is_active != active:
        competitor.is_active = active
        competitor.save(update_fields=["is_active", "updated_at"])
    return competitor


def _validated_source(source_url: str) -> str:
    url = (source_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CompetitorError(CompetitorErrorCode.INVALID_INPUT)
    return url


def create_statement(
    *,
    actor,
    competitor: Competitor,
    dimension: str,
    statement: str,
    source_url: str,
    published_on: date | None = None,
    captured_on: date | None = None,
) -> CompetitorStatement:
    _require_writer(actor)
    if dimension not in CompetitorDimension.values:
        raise CompetitorError(CompetitorErrorCode.INVALID_INPUT)
    text = " ".join((statement or "").split())
    if not text or len(text) > STATEMENT_MAX_LENGTH:
        raise CompetitorError(CompetitorErrorCode.INVALID_INPUT)
    if _NEGATIVE_RE.search(text.lower()):
        raise CompetitorError(CompetitorErrorCode.NEGATIVE_CLAIM)
    with transaction.atomic():
        return CompetitorStatement.objects.create(
            competitor=competitor,
            dimension=dimension,
            statement=text,
            source_url=_validated_source(source_url),
            published_on=published_on,
            captured_on=captured_on or timezone.localdate(),
            created_by=actor,
        )


def _decide(
    statement: CompetitorStatement,
    *,
    actor,
    status: CompetitorStatementStatus,
) -> CompetitorStatement:
    _require_admin(actor)
    if statement.status == status:
        return statement
    with transaction.atomic():
        CompetitorStatement.objects.filter(pk=statement.pk).update(
            status=status,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
            updated_at=timezone.now(),
        )
    statement.refresh_from_db()
    return statement


def approve_statement(statement: CompetitorStatement, *, actor) -> CompetitorStatement:
    return _decide(statement, actor=actor, status=CompetitorStatementStatus.APPROVED)


def reject_statement(statement: CompetitorStatement, *, actor) -> CompetitorStatement:
    return _decide(statement, actor=actor, status=CompetitorStatementStatus.REJECTED)


def list_statements(*, competitor=None, dimension: str = "", status: str = ""):
    queryset = CompetitorStatement.objects.select_related("competitor")
    if competitor is not None:
        queryset = queryset.filter(competitor=competitor)
    if dimension:
        queryset = queryset.filter(dimension=dimension)
    if status:
        queryset = queryset.filter(status=status)
    return queryset
