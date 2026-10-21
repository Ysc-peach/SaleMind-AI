"""Read-only, fail-closed authorization for immutable approved-version exports."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from django.contrib.auth import get_user_model
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import UserRole
from apps.sales.api.opportunity_access import visible_solution_drafts_for
from apps.sales.models import SolutionReviewDecisionStatus, SolutionReviewStatus
from apps.sales.services.solution_payloads import deserialize_solution_payload, SolutionPayloadError
from apps.sales.services.solution_persistence import evaluate_solution_draft_stale_reasons, _iter_cited_statements
from apps.sales.services.solution_schema import SolutionDraft
from apps.sales.services.solution_schema_v2 import SolutionDraftV2

_STATUSES = {
    'solution_export_unsupported_format': 400, 'solution_export_not_approved': 409,
    'solution_export_stale': 409, 'solution_export_requirement_changed': 409,
    'solution_export_changed': 409, 'solution_export_invalid_payload': 422,
    'solution_export_too_large': 422, 'solution_export_unavailable': 503,
}


class SolutionExportError(Exception):
    def __init__(self, code: str):
        self.code, self.status = code, _STATUSES[code]
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ExportProvenance:
    statement_path: str
    claim_id: str | None
    citation_label: str
    fact_id: int
    document_id: int
    document_title: str
    chunk_id: int
    index_run_id: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class ExportSnapshot:
    solution_id: int
    version: int
    schema_version: int
    analysis_id: int
    created_by_id: int
    created_at: datetime
    approval_id: int
    reviewer_id: int
    approved_at: datetime
    exported_at: datetime
    title: str
    domain: SolutionDraft | SolutionDraftV2
    sources: tuple[ExportProvenance, ...]
    fingerprint: str


def load_export_snapshot(*, actor_id: int, solution_id: int, exported_at: datetime) -> ExportSnapshot:
    actor = get_user_model().objects.filter(pk=actor_id).first()
    if not actor or not actor.is_active or actor.role not in {UserRole.SALES,UserRole.PRESALES,UserRole.ADMIN}:
        raise PermissionDenied()
    record = visible_solution_drafts_for(actor).select_related('opportunity','requirement_analysis').filter(pk=solution_id).first()
    if record is None:
        raise NotFound()
    approval = record.reviews.order_by('-submitted_at','-id').first()
    if (record.review_status != SolutionReviewStatus.APPROVED or approval is None
            or approval.status != SolutionReviewDecisionStatus.APPROVED or approval.decided_at is None):
        raise SolutionExportError('solution_export_not_approved')
    if record.is_stale or evaluate_solution_draft_stale_reasons(record):
        raise SolutionExportError('solution_export_stale')
    if record.opportunity.raw_requirement.strip() != record.requirement_analysis.source_raw_requirement.strip():
        raise SolutionExportError('solution_export_requirement_changed')
    try:
        domain = deserialize_solution_payload(record.schema_version,record.draft_payload)
    except SolutionPayloadError:
        raise SolutionExportError('solution_export_invalid_payload') from None
    entries = tuple(record.provenance_entries.select_related('source_document','enterprise_grounding_fact')
        .order_by('statement_path','citation_label','enterprise_grounding_fact_id','id'))
    if isinstance(domain,SolutionDraftV2):
        expected = {(f'claims.{c.claim_id}',label) for c in domain.claims for label in c.citations}
        malformed = any(e.statement_path != f'claims.{e.claim_id}' for e in entries)
    else:
        expected = {(path,label) for path,_,s in _iter_cited_statements(domain) for label in s.citations}
        malformed = any(e.claim_id is not None for e in entries)
    actual = {(e.statement_path,e.citation_label) for e in entries}
    unique = {(e.statement_path,e.citation_label,e.enterprise_grounding_fact_id) for e in entries}
    if malformed or actual != expected or len(unique) != len(entries):
        raise SolutionExportError('solution_export_invalid_payload')
    sources = tuple(ExportProvenance(e.statement_path,e.claim_id,e.citation_label,e.enterprise_grounding_fact_id,
        e.source_document_id,e.source_document.title if record.schema_version==2 else '',
        e.source_chunk_id,str(e.source_index_run_id),e.source_content_hash) for e in entries)
    # Consumed context is hashed locally, never serialized as document content or logged.
    context = {
        'actor': [actor.pk,actor.role,actor.is_active],
        'visibility': [record.opportunity.sales_owner_id,record.opportunity.presales_owner_id,
            list(record.reviews.order_by('id').values_list('id','reviewer_id'))],
        'version': [record.pk,record.version,record.schema_version,record.title,record.draft_payload,
            record.created_by_id,record.created_at.isoformat(),record.review_status,record.is_stale],
        'analysis': [record.requirement_analysis_id,record.requirement_analysis.source_raw_requirement.strip()],
        'approval': [approval.pk,approval.reviewer_id,approval.decided_at.isoformat()],
        'sources': [[e.statement_path,e.claim_id,e.citation_label,e.enterprise_grounding_fact_id,
            e.source_document_id,e.source_document.title,e.source_chunk_id,str(e.source_index_run_id),
            e.source_content_hash,e.source_excerpt,e.enterprise_grounding_fact.statement,
            e.enterprise_grounding_fact.status,e.enterprise_grounding_fact.approval_status,
            e.enterprise_grounding_fact.is_stale] for e in entries],
    }
    fingerprint = hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return ExportSnapshot(record.pk,record.version,record.schema_version,record.requirement_analysis_id,
        record.created_by_id,record.created_at,approval.pk,approval.reviewer_id,approval.decided_at,
        exported_at,record.title,domain,sources,fingerprint)


def revalidate_export_snapshot(snapshot: ExportSnapshot, *, actor_id: int) -> None:
    current = load_export_snapshot(actor_id=actor_id,solution_id=snapshot.solution_id,exported_at=snapshot.exported_at)
    if current.fingerprint != snapshot.fingerprint:
        raise SolutionExportError('solution_export_changed')
