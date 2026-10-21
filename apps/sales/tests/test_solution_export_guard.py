"""Missing authority, drift, or citation rows must never authorize downloads."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, NotFound

from apps.accounts.models import UserRole
from apps.knowledge.models import KnowledgeChunk
from apps.sales.models import SolutionDraftRecord, SolutionDraftProvenance, SolutionReview, OpportunityRequirementAnalysis
from apps.sales.tests.export_fixtures import (
    make_export_case, persistence_context, generated_artifact, business_state,
)

pytestmark = pytest.mark.django_db(transaction=True)


def load(case, actor=None):
    from apps.sales.services.solution_export_guard import load_export_snapshot
    return load_export_snapshot(actor_id=(actor or case.owner).pk,
        solution_id=case.solution.pk, exported_at=timezone.now())


def error(case, code):
    from apps.sales.services.solution_export_guard import SolutionExportError
    with pytest.raises(SolutionExportError) as caught:
        load(case)
    assert caught.value.code == code


def test_export_requires_completed_approval(make_export_case):
    case = make_export_case()
    SolutionReview.objects.filter(pk=case.approved_review.pk).delete()
    error(case, 'solution_export_not_approved')


@pytest.mark.parametrize('schema_version', [1, 2])
def test_approved_snapshot_is_read_only_and_has_no_provider_calls(make_export_case, monkeypatch, schema_version):
    case = make_export_case(schema_version)
    def forbidden(*args, **kwargs):
        pytest.fail('Export must not generate or refresh business data')
    monkeypatch.setattr('apps.sales.services.solution_persistence.generate_grounded_solution_draft', forbidden)
    monkeypatch.setattr('apps.sales.services.solution_persistence.refresh_solution_draft_staleness', forbidden)
    before = business_state()
    snap = load(case)
    assert (snap.solution_id, snap.version, snap.schema_version) == (case.solution.pk, 1, schema_version)
    assert snap.approval_id == case.approved_review.pk
    assert business_state() == before


def test_export_does_not_authorize_staff_flags(make_export_case, make_user):
    case = make_export_case()
    other = make_user(UserRole.SALES)
    other.is_staff = other.is_superuser = True
    other.save()
    with pytest.raises(NotFound):
        load(case, other)
    case.owner.is_active = False
    case.owner.is_staff = case.owner.is_superuser = True
    case.owner.save()
    with pytest.raises(PermissionDenied):
        load(case)


def test_independent_version_reviewer_can_export_only_assigned_version(make_export_case, make_user):
    case = make_export_case()
    assert case.opportunity.presales_owner_id is None
    assert load(case, case.reviewer).solution_id == case.solution.pk
    with pytest.raises(NotFound):
        load(case, make_user(UserRole.PRESALES))


def test_raw_requirement_drift_rejects_export(make_export_case):
    case = make_export_case()
    case.opportunity.raw_requirement += '新需求'
    case.opportunity.save(update_fields=['raw_requirement'])
    error(case, 'solution_export_requirement_changed')


def test_strip_equivalent_requirement_is_accepted(make_export_case):
    case = make_export_case()
    case.opportunity.raw_requirement = '  ' + case.opportunity.raw_requirement + '\n'
    case.opportunity.save(update_fields=['raw_requirement'])
    assert load(case).solution_id == case.solution.pk


@pytest.mark.parametrize('status', ['draft', 'pending_review', 'needs_revision'])
def test_nonapproved_state_cannot_export(make_export_case, status):
    case = make_export_case()
    SolutionDraftRecord.objects.filter(pk=case.solution.pk).update(review_status=status)
    error(case, 'solution_export_not_approved')


@pytest.mark.parametrize('schema_version', [1, 2])
@pytest.mark.parametrize('mutation', ['missing', 'extra', 'wrong_path'])
def test_missing_and_extra_provenance_fail_closed(make_export_case, schema_version, mutation):
    case = make_export_case(schema_version)
    entries = SolutionDraftProvenance.objects.filter(solution_draft=case.solution)
    if mutation == 'missing':
        entries.filter(pk=case.provenance.pk).delete()
    elif mutation == 'extra':
        entries.filter(pk=case.provenance.pk).update(citation_label='S999')
    else:
        entries.filter(pk=case.provenance.pk).update(statement_path='claims.INVALID')
    error(case, 'solution_export_invalid_payload')


@pytest.mark.parametrize('mutation', ['fact', 'index', 'chunk', 'stored', 'new_analysis'])
def test_new_analysis_revoked_fact_changed_index_and_chunk_reject(make_export_case, mutation):
    from uuid import uuid4
    case = make_export_case()
    if mutation == 'fact':
        type(case.fact).objects.filter(pk=case.fact.pk).update(approval_status='rejected', approved_by=None, approved_at=None)
    elif mutation == 'index':
        type(case.document).objects.filter(pk=case.document.pk).update(last_index_run_id=uuid4())
    elif mutation == 'chunk':
        KnowledgeChunk.objects.filter(pk=case.fact.source_chunk_id).update(content='changed')
    elif mutation == 'stored':
        SolutionDraftRecord.objects.filter(pk=case.solution.pk).update(is_stale=True, stale_at=timezone.now(), stale_reasons=['grounding_fact_invalid'])
    else:
        values = {f.name: getattr(case.analysis, f.name) for f in case.analysis._meta.fields
            if f.name not in {'id', 'created_at'}}
        OpportunityRequirementAnalysis.objects.create(**values)
    error(case, 'solution_export_stale')


def test_old_valid_approved_version_is_not_rejected_only_by_version_number(make_export_case):
    case = make_export_case()
    values = {f.name: getattr(case.solution, f.name) for f in case.solution._meta.fields
        if f.name not in {'id', 'created_at', 'generation_idempotency_key'}}
    values['version'] = 2
    SolutionDraftRecord.objects.create(**values)
    assert load(case).version == 1


def test_revalidation_includes_document_title_and_actor_context(make_export_case):
    from apps.sales.services.solution_export_guard import revalidate_export_snapshot, SolutionExportError
    case = make_export_case()
    snap = load(case)
    revalidate_export_snapshot(snap, actor_id=case.owner.pk)
    type(case.document).objects.filter(pk=case.document.pk).update(title='changed title')
    with pytest.raises(SolutionExportError) as caught:
        revalidate_export_snapshot(snap, actor_id=case.owner.pk)
    assert caught.value.code == 'solution_export_changed'
