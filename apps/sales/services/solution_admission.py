"""Deterministic claim admission from approved, current provenance facts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from collections.abc import Iterable

from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus as Approval,
    EnterpriseGroundingFactStatus as FactStatus,
    KnowledgeDocumentStatus,
)
from apps.knowledge.services.grounding_facts import GROUNDING_SUBJECT_REGISTRY
from apps.sales.services.requirement_analysis import (
    OpportunityRequirementAnalysis,
    RequirementDimension,
    RequirementStatus,
)
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import (
    AtomicSolutionClaim,
    AtomicSolutionClaimSet,
    SolutionSectionKey,
    SolutionStatementType,
    build_solution_unresolved_items,
)


_SUBJECT_SECTIONS = {
    "enterprise_knowledge_query": SolutionSectionKey.OVERALL_APPROACH,
    "private_deployment": SolutionSectionKey.DEPLOYMENT,
    "intranet_data_residency": SolutionSectionKey.DATA_SECURITY,
    "public_network_transfer": SolutionSectionKey.DATA_SECURITY,
    "postgresql": SolutionSectionKey.DEPLOYMENT,
    "pgvector": SolutionSectionKey.DEPLOYMENT,
    "server_compatibility": SolutionSectionKey.DEPLOYMENT,
    "oa_integration": SolutionSectionKey.INTEGRATION,
    "sso_integration": SolutionSectionKey.INTEGRATION,
    "kubernetes_deployment": SolutionSectionKey.DEPLOYMENT,
    "oracle_compatibility": SolutionSectionKey.INTEGRATION,
    "contract_generation": SolutionSectionKey.OVERALL_APPROACH,
    "csv_bulk_export": SolutionSectionKey.INTEGRATION,
    "scanned_pdf_ocr": SolutionSectionKey.OVERALL_APPROACH,
    "jwt_authentication": SolutionSectionKey.DATA_SECURITY,
}

_FIELD_LABELS = {
    RequirementDimension.BUSINESS_GOAL: "业务目标",
    RequirementDimension.USE_SCENARIO: "使用场景",
    RequirementDimension.USER_SCALE: "使用人数",
    RequirementDimension.DEPLOYMENT_REQUIREMENT: "部署要求",
    RequirementDimension.DATA_SECURITY_REQUIREMENT: "数据安全要求",
    RequirementDimension.EXISTING_ENVIRONMENT: "现有环境",
    RequirementDimension.INTEGRATION_REQUIREMENT: "集成要求",
    RequirementDimension.TIMELINE: "时间要求",
    RequirementDimension.BUDGET: "预算",
    RequirementDimension.TECHNICAL_CONSTRAINTS: "技术约束",
}

_FIELD_SECTIONS = {
    RequirementDimension.BUSINESS_GOAL: SolutionSectionKey.OVERALL_APPROACH,
    RequirementDimension.USE_SCENARIO: SolutionSectionKey.OVERALL_APPROACH,
    RequirementDimension.USER_SCALE: SolutionSectionKey.OVERALL_APPROACH,
    RequirementDimension.DEPLOYMENT_REQUIREMENT: SolutionSectionKey.DEPLOYMENT,
    RequirementDimension.DATA_SECURITY_REQUIREMENT: SolutionSectionKey.DATA_SECURITY,
    RequirementDimension.EXISTING_ENVIRONMENT: SolutionSectionKey.DEPLOYMENT,
    RequirementDimension.INTEGRATION_REQUIREMENT: SolutionSectionKey.INTEGRATION,
    RequirementDimension.TIMELINE: SolutionSectionKey.IMPLEMENTATION,
    RequirementDimension.BUDGET: SolutionSectionKey.IMPLEMENTATION,
    RequirementDimension.TECHNICAL_CONSTRAINTS: SolutionSectionKey.DEPLOYMENT,
}


@dataclass(frozen=True, slots=True)
class EnterpriseAdmissionDecision:
    subject_key: str
    status: FactStatus
    enterprise_fact_ids: tuple[int, ...]
    needs_attention: bool


@dataclass(frozen=True, slots=True)
class EnterpriseClaimProvenance:
    claim: AtomicSolutionClaim
    subject_key: str
    fact_id: int


@dataclass(frozen=True, slots=True)
class GroundingAdmission:
    claims: AtomicSolutionClaimSet
    enterprise_decisions: tuple[EnterpriseAdmissionDecision, ...]
    enterprise_provenance: tuple[EnterpriseClaimProvenance, ...]
    allowed_proposal_source_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EligibleFact:
    fact: EnterpriseGroundingFact
    source_label: str


def resolve_enterprise_subject(
    subject_key: str,
    eligible_facts: Iterable[_EligibleFact | EnterpriseGroundingFact],
) -> EnterpriseAdmissionDecision:
    """Resolve one controlled subject; absence always means UNCONFIRMED."""

    if subject_key not in GROUNDING_SUBJECT_REGISTRY:
        raise ValueError("Unknown grounding subject.")
    facts = tuple(
        item.fact if isinstance(item, _EligibleFact) else item
        for item in eligible_facts
    )
    statuses = {FactStatus(fact.status) for fact in facts}
    confirmed_ids = tuple(
        fact.pk
        for fact in facts
        if FactStatus(fact.status) in {
            FactStatus.CONFIRMED_SUPPORTED,
            FactStatus.CONFIRMED_UNSUPPORTED,
        }
    )
    is_conflict = (
        FactStatus.CONFLICT in statuses
        or {
            FactStatus.CONFIRMED_SUPPORTED,
            FactStatus.CONFIRMED_UNSUPPORTED,
        }.issubset(statuses)
    )
    if is_conflict:
        return EnterpriseAdmissionDecision(subject_key, FactStatus.CONFLICT, (), True)
    if FactStatus.CONFIRMED_SUPPORTED in statuses:
        status = FactStatus.CONFIRMED_SUPPORTED
    elif FactStatus.CONFIRMED_UNSUPPORTED in statuses:
        status = FactStatus.CONFIRMED_UNSUPPORTED
    else:
        status = FactStatus.UNCONFIRMED
        confirmed_ids = ()
    return EnterpriseAdmissionDecision(subject_key, status, confirmed_ids, False)


def build_solution_admission(
    analysis: OpportunityRequirementAnalysis,
    sources: tuple[SolutionSource, ...],
) -> GroundingAdmission:
    """Build all non-proposal claims without consulting any probabilistic component."""

    if not isinstance(analysis, OpportunityRequirementAnalysis):
        raise ValueError("Invalid requirement analysis.")
    if (
        not isinstance(sources, tuple)
        or not sources
        or any(not isinstance(source, SolutionSource) for source in sources)
        or tuple(source.label for source in sources)
        != tuple(f"S{i}" for i in range(1, len(sources) + 1))
    ):
        raise ValueError("Invalid solution sources.")

    candidates = tuple(
        EnterpriseGroundingFact.objects.select_related("source_document")
        .filter(
            source_document_id__in={source.document_id for source in sources},
            source_chunk_id__in={source.chunk_id for source in sources},
        )
        .order_by("subject_key", "pk")
    )
    source_by_identity = {
        (source.document_id, source.chunk_id): source for source in sources
    }
    eligible: dict[str, list[_EligibleFact]] = {}
    candidate_subjects = {
        fact.subject_key
        for fact in candidates
        if fact.subject_key in GROUNDING_SUBJECT_REGISTRY
    }
    for fact in candidates:
        source = source_by_identity.get(
            (fact.source_document_id, fact.source_chunk_id)
        )
        if source is None or not _is_active_approved_fact(fact, source):
            continue
        eligible.setdefault(fact.subject_key, []).append(
            _EligibleFact(fact, source.label)
        )

    claims = list(_build_customer_claims(analysis))
    decisions = []
    provenance = []
    proposal_labels = []
    for subject_key in sorted(candidate_subjects):
        subject_facts = tuple(eligible.get(subject_key, ()))
        decision = resolve_enterprise_subject(subject_key, subject_facts)
        decisions.append(decision)
        if decision.status is FactStatus.CONFLICT:
            claims.append(_enterprise_unresolved_claim(subject_key, conflict=True))
            continue
        if decision.status is FactStatus.UNCONFIRMED:
            claims.append(_enterprise_unresolved_claim(subject_key, conflict=False))
            continue
        allowed_ids = frozenset(decision.enterprise_fact_ids)
        for item in subject_facts:
            if item.fact.pk not in allowed_ids:
                continue
            claim = AtomicSolutionClaim(
                section=_SUBJECT_SECTIONS[subject_key],
                statement_type=SolutionStatementType.ENTERPRISE_FACT,
                text=item.fact.statement,
                citations=(item.source_label,),
            )
            claims.append(claim)
            provenance.append(
                EnterpriseClaimProvenance(claim, subject_key, item.fact.pk)
            )
            if decision.status is FactStatus.CONFIRMED_SUPPORTED:
                proposal_labels.append(item.source_label)

    ordered_labels = tuple(
        source.label
        for source in sources
        if source.label in frozenset(proposal_labels)
    )
    return GroundingAdmission(
        claims=AtomicSolutionClaimSet(tuple(claims)),
        enterprise_decisions=tuple(decisions),
        enterprise_provenance=tuple(provenance),
        allowed_proposal_source_labels=ordered_labels,
    )


def _is_active_approved_fact(
    fact: EnterpriseGroundingFact,
    source: SolutionSource,
) -> bool:
    document = fact.source_document
    return bool(
        fact.approval_status == Approval.APPROVED
        and not fact.is_stale
        and document.status == KnowledgeDocumentStatus.READY
        and document.last_index_run_id is not None
        and fact.source_index_run_id == document.last_index_run_id
        and fact.source_content_hash
        == hashlib.sha256(source.content.encode("utf-8")).hexdigest()
    )


def _build_customer_claims(
    analysis: OpportunityRequirementAnalysis,
) -> tuple[AtomicSolutionClaim, ...]:
    claims = []
    for field in RequirementDimension:
        item = getattr(analysis.requirements, field.value)
        if item.status is not RequirementStatus.KNOWN:
            continue
        claims.append(
            AtomicSolutionClaim(
                section=_FIELD_SECTIONS[field],
                statement_type=SolutionStatementType.CUSTOMER_FACT,
                text=f"{_FIELD_LABELS[field]}：{item.value}。",
                citations=(),
            )
        )
    for item in build_solution_unresolved_items(analysis):
        claims.append(
            AtomicSolutionClaim(
                section=_FIELD_SECTIONS[item.field],
                statement_type=SolutionStatementType.UNRESOLVED,
                text=item.text,
                citations=(),
            )
        )
    return tuple(claims)


def _enterprise_unresolved_claim(
    subject_key: str,
    *,
    conflict: bool,
) -> AtomicSolutionClaim:
    label = GROUNDING_SUBJECT_REGISTRY[subject_key]
    text = (
        f"当前企业资料对{label}存在冲突，需要人工或售前确认。"
        if conflict
        else f"当前企业资料未确认{label}，需要进一步确认。"
    )
    return AtomicSolutionClaim(
        section=_SUBJECT_SECTIONS[subject_key],
        statement_type=SolutionStatementType.UNRESOLVED,
        text=text,
        citations=(),
    )
