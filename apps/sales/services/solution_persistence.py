"""Application boundary for durable, immutable Solution Draft versions."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import NoReturn

from django.contrib.auth import get_user_model
from django.db import connection, models, transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus,
    EnterpriseGroundingFactStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
)
from apps.llm.base import LLMProvider
from apps.sales.models import (
    Opportunity,
    OpportunityRequirementAnalysis,
    SolutionDraftProvenance,
    SolutionDraftRecord,
    SolutionStaleReason,
)
from apps.sales.services.requirement_analysis_history import analysis_record_to_domain
from apps.sales.services.solution_admission import GroundingAdmission, build_solution_admission
from apps.sales.services.solution_draft import (
    GroundedSolutionDraftResult,
    SolutionGenerationStatus,
    generate_grounded_solution_draft,
)
from apps.sales.services.requirement_analysis import RequirementDimension
from apps.sales.services.solution_schema import (
    SECTION_DEFINITIONS,
    SolutionAssumption,
    SolutionDraft,
    SolutionSection,
    SolutionStatement,
    SolutionStatementType,
)


class SolutionPersistenceError(Exception):
    """Fail-closed persistence-boundary error without business payloads."""

    def __init__(self, message: str = "The Solution Draft could not be persisted."):
        self.safe_message = message
        super().__init__(message)


def solution_draft_to_payload(draft: SolutionDraft) -> dict:
    """Map the frozen domain value to a stable JSON-compatible structure."""

    if not isinstance(draft, SolutionDraft):
        _invalid_payload()
    payload = {
        "title": draft.title,
        "executive_summary": [_statement_to_payload(item) for item in draft.executive_summary],
        "solution_sections": [
            {
                "key": section.key,
                "title": section.title,
                "statements": [_statement_to_payload(item) for item in section.statements],
            }
            for section in draft.solution_sections
        ],
        "assumptions": [
            {
                "text": item.text,
                "related_fields": [field.value for field in item.related_fields],
            }
            for item in draft.assumptions
        ],
    }
    if solution_draft_from_payload(payload) != draft:
        _invalid_payload()
    return payload


def solution_draft_from_payload(payload: object) -> SolutionDraft:
    """Recreate a domain value only from the canonical persistence schema."""

    _object(payload, {"title", "executive_summary", "solution_sections", "assumptions"})
    title = _text(payload["title"])
    summary = _statements(payload["executive_summary"], maximum=8)
    sections_payload = payload["solution_sections"]
    if not isinstance(sections_payload, list) or len(sections_payload) != len(SECTION_DEFINITIONS):
        _invalid_payload()
    sections = []
    for value, (expected_key, expected_title) in zip(
        sections_payload, SECTION_DEFINITIONS, strict=True
    ):
        _object(value, {"key", "title", "statements"})
        if value["key"] != expected_key or value["title"] != expected_title:
            _invalid_payload()
        sections.append(
            SolutionSection(
                key=expected_key,
                title=expected_title,
                statements=_statements(value["statements"], maximum=12),
            )
        )
    assumptions_payload = payload["assumptions"]
    if not isinstance(assumptions_payload, list) or len(assumptions_payload) > 10:
        _invalid_payload()
    assumptions = []
    for value in assumptions_payload:
        _object(value, {"text", "related_fields"})
        fields = value["related_fields"]
        if (
            not isinstance(fields, list)
            or not fields
            or len(fields) != len(set(fields))
            or any(
                not isinstance(field, str)
                or field not in RequirementDimension._value2member_map_
                for field in fields
            )
        ):
            _invalid_payload()
        assumptions.append(
            SolutionAssumption(
                text=_text(value["text"]),
                related_fields=tuple(RequirementDimension(field) for field in fields),
            )
        )
    return SolutionDraft(
        title=title,
        executive_summary=summary,
        solution_sections=tuple(sections),
        assumptions=tuple(assumptions),
    )


def generate_and_persist_solution_draft(
    opportunity: Opportunity,
    analysis: OpportunityRequirementAnalysis,
    *,
    created_by,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
    verifier_provider: LLMProvider | None = None,
) -> SolutionDraftRecord:
    """Generate outside a transaction, then atomically append one version."""

    if connection.in_atomic_block or not connection.get_autocommit():
        raise TransactionManagementError(
            "Solution generation must run outside an existing transaction."
        )
    opportunity_id = _saved_pk(opportunity, Opportunity)
    analysis_id = _saved_pk(analysis, OpportunityRequirementAnalysis)
    created_by_id = _saved_pk(created_by, get_user_model())
    if analysis.opportunity_id != opportunity_id:
        raise SolutionPersistenceError("The selected analysis does not belong to this opportunity.")

    result = generate_grounded_solution_draft(
        analysis,
        embedding_provider=embedding_provider,
        llm_provider=llm_provider,
        verifier_provider=verifier_provider,
    )
    if (
        not isinstance(result, GroundedSolutionDraftResult)
        or result.analysis_id != analysis_id
        or result.generation_status is not SolutionGenerationStatus.GENERATED
        or result.draft is None
        or result.admission is None
    ):
        raise SolutionPersistenceError("No validated Solution Draft was generated.")

    with transaction.atomic():
        locked_opportunity = Opportunity.objects.select_for_update().get(pk=opportunity_id)
        locked_analysis = OpportunityRequirementAnalysis.objects.select_for_update().get(
            pk=analysis_id,
            opportunity_id=opportunity_id,
        )
        _lock_admission_rows(result.admission)
        current_admission = build_solution_admission(
            analysis_record_to_domain(locked_analysis),
            result.sources,
        )
        if current_admission != result.admission:
            raise SolutionPersistenceError("Grounding provenance changed before persistence.")

        current_version = (
            SolutionDraftRecord.objects.filter(opportunity=locked_opportunity)
            .aggregate(maximum=models.Max("version"))["maximum"]
            or 0
        )
        stale_reasons = []
        if _has_newer_analysis(locked_analysis):
            stale_reasons.append(SolutionStaleReason.NEWER_REQUIREMENT_ANALYSIS)
        stale = bool(stale_reasons)
        record = SolutionDraftRecord.objects.create(
            opportunity=locked_opportunity,
            requirement_analysis=locked_analysis,
            version=current_version + 1,
            title=result.draft.title,
            draft_payload=solution_draft_to_payload(result.draft),
            generation_metadata={
                "generation_status": result.generation_status.value,
                "source_count": len(result.sources),
            },
            is_stale=stale,
            stale_at=timezone.now() if stale else None,
            stale_reasons=[reason.value for reason in stale_reasons],
            created_by_id=created_by_id,
        )
        entries = _build_provenance_entries(record, result)
        SolutionDraftProvenance.objects.bulk_create(entries)
        return record


def evaluate_solution_draft_stale_reasons(
    record: SolutionDraftRecord,
) -> tuple[SolutionStaleReason, ...]:
    """Evaluate current state deterministically without mutating review lifecycle."""

    record_id = _saved_pk(record, SolutionDraftRecord)
    current = SolutionDraftRecord.objects.select_related("requirement_analysis").get(pk=record_id)
    reasons = []
    if _has_newer_analysis(current.requirement_analysis):
        reasons.append(SolutionStaleReason.NEWER_REQUIREMENT_ANALYSIS)
    entries = tuple(
        current.provenance_entries.select_related(
            "enterprise_grounding_fact",
            "enterprise_grounding_fact__source_document",
            "source_document",
        )
    )
    fact_invalid = False
    provenance_invalid = False
    chunks = {
        chunk.pk: chunk
        for chunk in KnowledgeChunk.objects.filter(
            pk__in={entry.source_chunk_id for entry in entries}
        ).only("id", "document_id", "content")
    }
    for entry in entries:
        fact = entry.enterprise_grounding_fact
        if (
            fact.approval_status != EnterpriseGroundingFactApprovalStatus.APPROVED
            or fact.is_stale
            or fact.status
            not in {
                EnterpriseGroundingFactStatus.CONFIRMED_SUPPORTED,
                EnterpriseGroundingFactStatus.CONFIRMED_UNSUPPORTED,
            }
        ):
            fact_invalid = True
        chunk = chunks.get(entry.source_chunk_id)
        document = entry.source_document
        if (
            entry.source_document_id != fact.source_document_id
            or entry.source_chunk_id != fact.source_chunk_id
            or entry.source_index_run_id != fact.source_index_run_id
            or entry.source_content_hash != fact.source_content_hash
            or entry.source_excerpt != fact.source_excerpt
            or document.status != KnowledgeDocumentStatus.READY
            or document.last_index_run_id != entry.source_index_run_id
            or chunk is None
            or chunk.document_id != document.pk
            or hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            != entry.source_content_hash
        ):
            provenance_invalid = True
    if fact_invalid:
        reasons.append(SolutionStaleReason.GROUNDING_FACT_INVALID)
    if provenance_invalid:
        reasons.append(SolutionStaleReason.GROUNDING_PROVENANCE_INVALID)
    return tuple(reasons)


def refresh_solution_draft_staleness(record: SolutionDraftRecord) -> SolutionDraftRecord:
    """Persist only derived stale metadata; content and review status stay unchanged."""

    reasons = evaluate_solution_draft_stale_reasons(record)
    is_stale = bool(reasons)
    record.is_stale = is_stale
    record.stale_at = record.stale_at or timezone.now() if is_stale else None
    record.stale_reasons = [reason.value for reason in reasons]
    record.save(update_fields=["is_stale", "stale_at", "stale_reasons"])
    return record


def _lock_admission_rows(admission: GroundingAdmission) -> None:
    fact_ids = {item.fact_id for item in admission.enterprise_provenance}
    facts = tuple(
        EnterpriseGroundingFact.objects.select_for_update()
        .select_related("source_document")
        .filter(pk__in=fact_ids)
    )
    if {fact.pk for fact in facts} != fact_ids:
        raise SolutionPersistenceError("Grounding Fact provenance is incomplete.")
    document_ids = {fact.source_document_id for fact in facts}
    documents = tuple(
        KnowledgeDocument.objects.select_for_update().filter(pk__in=document_ids)
    )
    if {document.pk for document in documents} != document_ids:
        raise SolutionPersistenceError("Knowledge document provenance is incomplete.")


def _build_provenance_entries(
    record: SolutionDraftRecord,
    result: GroundedSolutionDraftResult,
) -> list[SolutionDraftProvenance]:
    admission = result.admission
    draft = result.draft
    if admission is None or draft is None:
        raise SolutionPersistenceError()
    provenance_by_claim = defaultdict(list)
    provenance_by_label = defaultdict(list)
    fact_ids = {item.fact_id for item in admission.enterprise_provenance}
    facts = {
        fact.pk: fact
        for fact in EnterpriseGroundingFact.objects.select_related("source_document")
        .filter(pk__in=fact_ids)
    }
    for item in admission.enterprise_provenance:
        fact = facts.get(item.fact_id)
        if fact is None:
            raise SolutionPersistenceError("Grounding Fact provenance is incomplete.")
        provenance_by_claim[item.claim].append(fact)
        for label in item.claim.citations:
            provenance_by_label[label].append(fact)

    entries = []
    for path, section_key, statement in _iter_cited_statements(draft):
        if statement.type is SolutionStatementType.ENTERPRISE_FACT:
            claim_key = next(
                (
                    claim
                    for claim in provenance_by_claim
                    if claim.section.value == section_key
                    and claim.statement_type is statement.type
                    and claim.text == statement.text
                    and claim.citations == statement.citations
                ),
                None,
            )
            matching = provenance_by_claim.get(claim_key, ())
        else:
            matching = ()
        for label in statement.citations:
            candidates = (
                matching
                if statement.type is SolutionStatementType.ENTERPRISE_FACT
                else provenance_by_label.get(label, ())
            )
            label_fact_ids = {fact.pk for fact in provenance_by_label.get(label, ())}
            label_facts = tuple(
                sorted(
                    {fact.pk: fact for fact in candidates if fact.pk in label_fact_ids}.values(),
                    key=lambda fact: fact.pk,
                )
            )
            if not label_facts:
                raise SolutionPersistenceError("A citation has no admitted Fact provenance.")
            for fact in label_facts:
                entries.append(
                    SolutionDraftProvenance(
                        solution_draft=record,
                        statement_path=path,
                        citation_label=label,
                        enterprise_grounding_fact=fact,
                        source_document_id=fact.source_document_id,
                        source_chunk_id=fact.source_chunk_id,
                        source_index_run_id=fact.source_index_run_id,
                        source_content_hash=fact.source_content_hash,
                        source_excerpt=fact.source_excerpt,
                    )
                )
    return entries


def _iter_cited_statements(draft: SolutionDraft):
    # Executive-summary statements are deterministic aliases of section claims.
    for index, statement in enumerate(draft.executive_summary):
        if statement.citations:
            section_key = next(
                (
                    section.key
                    for section in draft.solution_sections
                    if statement in section.statements
                ),
                "overall_approach",
            )
            yield f"executive_summary[{index}]", section_key, statement
    for section in draft.solution_sections:
        for index, statement in enumerate(section.statements):
            if statement.citations:
                yield (
                    f"solution_sections.{section.key}.statements[{index}]",
                    section.key,
                    statement,
                )


def _has_newer_analysis(analysis: OpportunityRequirementAnalysis) -> bool:
    return OpportunityRequirementAnalysis.objects.filter(
        opportunity_id=analysis.opportunity_id,
    ).filter(
        models.Q(created_at__gt=analysis.created_at)
        | models.Q(created_at=analysis.created_at, pk__gt=analysis.pk)
    ).exists()


def _saved_pk(instance, model) -> int:
    if not isinstance(instance, model) or instance.pk is None or instance._state.adding:
        raise SolutionPersistenceError("A saved persistence input is required.")
    return instance.pk


def _statement_to_payload(statement: SolutionStatement) -> dict:
    if not isinstance(statement, SolutionStatement):
        _invalid_payload()
    return {
        "type": statement.type.value,
        "text": statement.text,
        "citations": list(statement.citations),
    }


def _statements(value: object, *, maximum: int) -> tuple[SolutionStatement, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        _invalid_payload()
    statements = []
    for item in value:
        _object(item, {"type", "text", "citations"})
        kind = item["type"]
        citations = item["citations"]
        if (
            not isinstance(kind, str)
            or kind not in SolutionStatementType._value2member_map_
            or not isinstance(citations, list)
            or len(citations) != len(set(citations))
            or any(
                not isinstance(label, str)
                or re.fullmatch(r"S[1-9][0-9]*", label) is None
                for label in citations
            )
        ):
            _invalid_payload()
        statement_type = SolutionStatementType(kind)
        if (
            statement_type is SolutionStatementType.CUSTOMER_FACT
            and citations
            or statement_type
            in {SolutionStatementType.ENTERPRISE_FACT, SolutionStatementType.PROPOSAL}
            and not citations
        ):
            _invalid_payload()
        statements.append(
            SolutionStatement(
                type=statement_type,
                text=_text(item["text"]),
                citations=tuple(citations),
            )
        )
    return tuple(statements)


def _object(value: object, expected_keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected_keys:
        _invalid_payload()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _invalid_payload()
    return value


def _invalid_payload() -> NoReturn:
    raise SolutionPersistenceError("The Solution Draft payload is invalid.")
