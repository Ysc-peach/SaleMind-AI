"""Read-only comparison matrix: what we can say, what they said, what is missing.

This is deliberately not a generator. It answers "can this row be written at
all", so the comparison section that follows can refuse to invent a side that
has no evidence behind it.
"""

from __future__ import annotations

from collections import defaultdict

from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus,
)
from apps.sales.models import (
    CompetitorDimension,
    CompetitorStatement,
    CompetitorStatementStatus,
)

#: Each axis is a second view of subjects the evidence chain already governs.
DIMENSION_SUBJECTS: dict[str, tuple[str, ...]] = {
    CompetitorDimension.DEPLOYMENT: (
        "private_deployment",
        "kubernetes_deployment",
    ),
    CompetitorDimension.DATA_RESIDENCY: (
        "intranet_data_residency",
        "public_network_transfer",
    ),
    CompetitorDimension.IDENTITY_INTEGRATION: (
        "sso_integration",
        "oa_integration",
        "jwt_authentication",
    ),
    CompetitorDimension.DATA_STORAGE: (
        "postgresql",
        "pgvector",
        "oracle_compatibility",
    ),
    CompetitorDimension.DOCUMENT_PROCESSING: ("scanned_pdf_ocr",),
    CompetitorDimension.DELIVERABLES: (
        "contract_generation",
        "csv_bulk_export",
    ),
    CompetitorDimension.SERVER_COMPATIBILITY: ("server_compatibility",),
    CompetitorDimension.KNOWLEDGE_RETRIEVAL: ("enterprise_knowledge_query",),
}

GAP_MISSING_BOTH = "missing_both"
GAP_MISSING_STATEMENT = "missing_competitor_statement"
GAP_MISSING_FACT = "missing_own_fact"

DEFAULT_EVIDENCE_LIMIT = 3


def _approved_facts_by_subject(*, limit: int) -> dict[str, list]:
    """One query, grouped, so a matrix costs two queries rather than sixteen."""

    subjects = {key for keys in DIMENSION_SUBJECTS.values() for key in keys}
    facts = (
        EnterpriseGroundingFact.objects.filter(
            approval_status=EnterpriseGroundingFactApprovalStatus.APPROVED,
            is_stale=False,
            subject_key__in=subjects,
        )
        .order_by("-approved_at", "-id")
    )
    grouped: dict[str, list] = defaultdict(list)
    for fact in facts:
        if len(grouped[fact.subject_key]) < limit:
            grouped[fact.subject_key].append(fact)
    return grouped


def _approved_statements(competitors, *, limit: int) -> dict[tuple, list]:
    statements = CompetitorStatement.objects.filter(
        competitor__in=competitors,
        status=CompetitorStatementStatus.APPROVED,
    ).order_by("-reviewed_at", "-id")
    grouped: dict[tuple, list] = defaultdict(list)
    for statement in statements:
        key = (statement.competitor_id, statement.dimension)
        if len(grouped[key]) < limit:
            grouped[key].append(statement)
    return grouped


def _fact_row(fact) -> dict:
    return {
        "id": fact.pk,
        "subject_key": fact.subject_key,
        "statement": fact.statement,
        "approved_at": fact.approved_at.isoformat() if fact.approved_at else None,
    }


def _statement_row(statement) -> dict:
    return {
        "id": statement.pk,
        "statement": statement.statement,
        "source_url": statement.source_url,
        "published_on": (
            statement.published_on.isoformat() if statement.published_on else None
        ),
        "captured_on": statement.captured_on.isoformat(),
    }


def build_matrix(*, competitors, limit: int = DEFAULT_EVIDENCE_LIMIT) -> dict:
    """One row per (dimension, competitor), with the sides that exist."""

    if limit < 1:
        limit = 1
    facts_by_subject = _approved_facts_by_subject(limit=limit)
    statements_by_key = _approved_statements(competitors, limit=limit)

    dimensions = []
    formable = 0
    total = 0
    for dimension, subjects in DIMENSION_SUBJECTS.items():
        own_facts = []
        for subject in subjects:
            for fact in facts_by_subject.get(subject, []):
                if len(own_facts) < limit:
                    own_facts.append(fact)

        competitor_rows = []
        for competitor in competitors:
            statements = statements_by_key.get(
                (competitor.pk, dimension), []
            )[:limit]
            if own_facts and statements:
                gap = ""
            elif not own_facts and not statements:
                gap = GAP_MISSING_BOTH
            elif not statements:
                gap = GAP_MISSING_STATEMENT
            else:
                gap = GAP_MISSING_FACT
            total += 1
            if not gap:
                formable += 1
            competitor_rows.append(
                {
                    "competitor_id": competitor.pk,
                    "competitor_name": competitor.name,
                    "own_facts": [_fact_row(fact) for fact in own_facts],
                    # Only approved statements may ever be quoted; a proposed
                    # one would leave the row looking written when it is not.
                    "statements": [
                        _statement_row(statement) for statement in statements
                    ],
                    "can_form": not gap,
                    "gap": gap,
                }
            )
        dimensions.append(
            {
                "dimension": dimension,
                "label": CompetitorDimension(dimension).label,
                "competitors": competitor_rows,
            }
        )

    return {
        "dimensions": dimensions,
        "formable_rows": formable,
        "total_rows": total,
    }
