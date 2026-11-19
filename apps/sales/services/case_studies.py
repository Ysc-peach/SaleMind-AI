"""Case library: material presales reuses instead of rewriting per deal.

Writing is limited to presales and administrators. A seller reading a case is
normal; a seller inventing one is how a library fills with claims nobody can
defend in front of the customer.
"""

from __future__ import annotations

from enum import StrEnum

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When

from apps.accounts.models import UserRole
from apps.sales.models import CaseStudy, CaseStudySizeBand

TITLE_MAX_LENGTH = 200
INDUSTRY_MAX_LENGTH = 64
TEXT_MAX_LENGTH = 4000
DEFAULT_MATCH_LIMIT = 5

_WRITERS = (UserRole.ADMIN, UserRole.PRESALES)
_TEXT_FIELDS = ("pain_points", "approach", "results")


class CaseStudyErrorCode(StrEnum):
    INVALID_INPUT = "case_study_invalid_input"
    FORBIDDEN = "case_study_forbidden"


class CaseStudyError(Exception):
    def __init__(self, code: CaseStudyErrorCode):
        super().__init__(code.value)
        self.code = code


def _clean_text(value: str, *, limit: int) -> str:
    return " ".join((value or "").split())[:limit].strip()


def _validated(fields: dict) -> dict:
    title = _clean_text(fields.get("title", ""), limit=TITLE_MAX_LENGTH)
    industry = _clean_text(fields.get("industry", ""), limit=INDUSTRY_MAX_LENGTH)
    size_band = fields.get("size_band", "")
    if not title or not industry or size_band not in CaseStudySizeBand.values:
        raise CaseStudyError(CaseStudyErrorCode.INVALID_INPUT)
    values = {
        "title": title,
        "industry": industry,
        "size_band": size_band,
        "customer_name": _clean_text(
            fields.get("customer_name", ""), limit=120
        ),
        "referenceable": bool(fields.get("referenceable", False)),
    }
    for name in _TEXT_FIELDS:
        text = (fields.get(name) or "").strip()
        if len(text) > TEXT_MAX_LENGTH:
            raise CaseStudyError(CaseStudyErrorCode.INVALID_INPUT)
        values[name] = text
    return values


def _require_writer(actor) -> None:
    if actor is None or actor.role not in _WRITERS:
        raise CaseStudyError(CaseStudyErrorCode.FORBIDDEN)


def create_case(*, actor, **fields) -> CaseStudy:
    _require_writer(actor)
    values = _validated(fields)
    with transaction.atomic():
        return CaseStudy.objects.create(created_by=actor, **values)


def update_case(case: CaseStudy, *, actor, **fields) -> CaseStudy:
    _require_writer(actor)
    merged = {
        "title": case.title,
        "industry": case.industry,
        "size_band": case.size_band,
        "customer_name": case.customer_name,
        "referenceable": case.referenceable,
        **{name: getattr(case, name) for name in _TEXT_FIELDS},
        **fields,
    }
    values = _validated(merged)
    with transaction.atomic():
        for name, value in values.items():
            setattr(case, name, value)
        case.save()
    return case


def set_case_active(case: CaseStudy, *, actor, active: bool) -> CaseStudy:
    _require_writer(actor)
    if case.is_active != active:
        case.is_active = active
        case.save(update_fields=["is_active", "updated_at"])
    return case


def list_cases(
    *,
    industry: str = "",
    size_band: str = "",
    referenceable: bool | None = None,
    search: str = "",
    include_inactive: bool = False,
):
    queryset = CaseStudy.objects.all()
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    if industry:
        queryset = queryset.filter(industry__iexact=industry)
    if size_band:
        queryset = queryset.filter(size_band=size_band)
    if referenceable is not None:
        queryset = queryset.filter(referenceable=referenceable)
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(customer_name__icontains=search)
            | Q(pain_points__icontains=search)
        )
    return queryset


def match_cases(*, industry: str = "", size_band: str = "", limit: int | None = None):
    """Cases closest to this shape first: same industry, then same size.

    Ranked rather than filtered, because a strict filter usually returns nothing
    and a presales then writes the section from memory.
    """

    queryset = CaseStudy.objects.filter(is_active=True)
    ordering: list[str] = []
    if industry:
        queryset = queryset.annotate(
            _industry_hit=Case(
                When(industry__iexact=industry, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        ordering.append("_industry_hit")
    if size_band:
        queryset = queryset.annotate(
            _size_hit=Case(
                When(size_band=size_band, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        ordering.append("_size_hit")
    ordering += ["-referenceable", "-updated_at", "-id"]
    return list(queryset.order_by(*ordering)[: limit or DEFAULT_MATCH_LIMIT])
