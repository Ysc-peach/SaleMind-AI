"""Create and read immutable requirement-analysis history; no HTTP concerns."""

import json
from dataclasses import asdict

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.transaction import TransactionManagementError

from apps.llm.base import LLMProvider
from apps.sales.models import (
    Opportunity,
    OpportunityRequirementAnalysis as AnalysisRecord,
)
from apps.sales.services.requirement_analysis import (
    OpportunityRequirementAnalysis as DomainAnalysis,
    RequirementAnalysisError,
    RequirementAnalysisErrorCode,
    _execute_requirement_analysis,
    _parse_analysis,
)


def create_opportunity_requirement_analysis(
    opportunity: Opportunity,
    *,
    created_by,
    llm_provider: LLMProvider | None = None,
) -> AnalysisRecord:
    """Analyze once, then append one history row in a short transaction.

    Callers supply authorized, saved business objects and must not wrap this
    operation in an outer transaction. Provider/domain/database failures retain
    their types; none are retried here. Business facts are never updated.
    """

    if connection.in_atomic_block or not connection.get_autocommit():
        raise TransactionManagementError(
            "Requirement analysis must run outside an existing transaction."
        )
    opportunity_id = _saved_pk(opportunity, Opportunity)
    created_by_id = _saved_pk(created_by, get_user_model())
    execution = _execute_requirement_analysis(opportunity, llm_provider=llm_provider)
    payload = _storage_payload(execution.analysis)
    with transaction.atomic():
        return AnalysisRecord.objects.create(
            opportunity_id=opportunity_id,
            created_by_id=created_by_id,
            **payload,
            source_raw_requirement=execution.source_raw_requirement,
            source_context=execution.source_context,
            analysis_version=execution.analysis_version,
            llm_provider=execution.llm_provider,
            llm_model=execution.llm_model,
        )


def list_opportunity_requirement_analyses(opportunity: Opportunity) -> tuple[AnalysisRecord, ...]:
    """Return this opportunity's history in stable newest-first order."""

    return tuple(AnalysisRecord.objects.filter(opportunity_id=_saved_pk(opportunity, Opportunity)))


def get_latest_opportunity_requirement_analysis(opportunity: Opportunity) -> AnalysisRecord | None:
    """Use model ordering (-created_at, -id); no cached latest pointer."""

    return AnalysisRecord.objects.filter(opportunity_id=_saved_pk(opportunity, Opportunity)).first()


def analysis_record_to_domain(record: AnalysisRecord) -> DomainAnalysis:
    """Validate stored result fields through the original strict schema parser."""

    return _parse_analysis(json.dumps({
        "summary": record.summary,
        "requirements": record.requirements,
        "conflicts": record.conflicts,
        "clarifying_questions": record.clarifying_questions,
    }, ensure_ascii=False))


def _storage_payload(analysis: DomainAnalysis) -> dict:
    """One deterministic dataclass -> JSON boundary; no schema rewriting."""

    return json.loads(json.dumps(asdict(analysis), ensure_ascii=False))


def _saved_pk(instance, model) -> int:
    if not isinstance(instance, model) or instance.pk is None or instance._state.adding:
        raise RequirementAnalysisError(RequirementAnalysisErrorCode.INVALID_INPUT)
    return instance.pk
