"""Schema-aware persistence and exact claim provenance for Solution V2."""

from dataclasses import replace
from uuid import uuid4

import pytest

from apps.sales.tests.test_solution_persistence_service import (
    generated_artifact,
    persistence_context,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _v2_result(v1_result, *, with_duplicate_text_proposal=False):
    from apps.sales.services.requirement_analysis_history import analysis_record_to_domain
    from apps.sales.services.solution_prompt_v2 import (
        AtomicSolutionProposalSetV2,
        AtomicSolutionProposalV2,
        SolutionV2ContainerKind,
        SolutionV2Placement,
        SolutionV2PlacementField,
        SolutionV2Section,
    )
    from apps.sales.services.solution_schema_v2 import (
        assemble_solution_draft_v2,
        build_v2_deterministic_items,
    )

    analysis = analysis_record_to_domain(_analysis_record(v1_result))
    proposals = ()
    if with_duplicate_text_proposal:
        enterprise_text = v1_result.admission.enterprise_provenance[0].claim.text
        proposals = (AtomicSolutionProposalV2(
            placement=SolutionV2Placement(
                SolutionV2Section.PROPOSED_SOLUTION,
                SolutionV2ContainerKind.ROOT,
                None,
                SolutionV2PlacementField.OVERVIEW,
            ),
            text=enterprise_text,
            citations=("S1",),
        ),)
    assembly = assemble_solution_draft_v2(
        build_v2_deterministic_items(analysis, v1_result.admission),
        AtomicSolutionProposalSetV2(proposals),
    )
    return replace(
        v1_result,
        draft=assembly.draft,
        schema_version=2,
        v2_provenance_bindings=assembly.provenance_bindings,
    )


def _analysis_record(result):
    from apps.sales.models import OpportunityRequirementAnalysis

    return OpportunityRequirementAnalysis.objects.get(pk=result.analysis_id)


def _patch(monkeypatch, result):
    from apps.sales.services import solution_persistence

    calls = []

    def generate(analysis, **kwargs):
        calls.append(kwargs)
        return replace(result, analysis_id=analysis.pk)

    monkeypatch.setattr(solution_persistence, "generate_grounded_solution_draft", generate)
    return calls


def test_v2_persistence_uses_schema_mapper_and_exact_claim_ids(
    monkeypatch, persistence_context, generated_artifact
):
    from apps.sales.models import SolutionDraftProvenance
    from apps.sales.services.solution_payloads import deserialize_solution_payload
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    owner, _, opportunity, analysis, _ = persistence_context
    result = _v2_result(generated_artifact[0], with_duplicate_text_proposal=True)
    calls = _patch(monkeypatch, result)

    record = generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, schema_version=2
    )

    restored = deserialize_solution_payload(record.schema_version, record.draft_payload)
    assert record.schema_version == 2
    assert restored == result.draft
    assert calls[0]["schema_version"] == 2
    entries = tuple(SolutionDraftProvenance.objects.filter(solution_draft=record))
    expected = {
        (binding.claim_id, binding.citation_label, binding.fact_id)
        for binding in result.v2_provenance_bindings
    }
    assert {
        (entry.claim_id, entry.citation_label, entry.enterprise_grounding_fact_id)
        for entry in entries
    } == expected
    assert all(entry.statement_path == f"claims.{entry.claim_id}" for entry in entries)
    same_text_ids = {
        claim.claim_id
        for claim in result.draft.claims
        if claim.text == result.draft.claims[-1].text
    }
    assert len(same_text_ids) == 2
    assert same_text_ids <= {entry.claim_id for entry in entries}


def test_explicit_v1_persistence_remains_readable(
    monkeypatch, persistence_context, generated_artifact
):
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    owner, _, opportunity, analysis, _ = persistence_context
    _patch(monkeypatch, generated_artifact[0])

    record = generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, schema_version=1
    )

    assert record.schema_version == 1
    assert record.provenance_entries.filter(claim_id__isnull=True).exists()


def test_same_idempotency_key_cannot_change_schema_before_provider(
    monkeypatch, persistence_context, generated_artifact
):
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    calls = _patch(monkeypatch, generated_artifact[0])
    key = uuid4()
    solution_persistence.generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, schema_version=1, idempotency_key=key
    )

    with pytest.raises(solution_persistence.SolutionPersistenceError):
        solution_persistence.generate_and_persist_solution_draft(
            opportunity, analysis, created_by=owner, schema_version=2, idempotency_key=key
        )

    assert len(calls) == 1


def test_missing_v2_claim_binding_rolls_back_record_and_provenance(
    monkeypatch, persistence_context, generated_artifact
):
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    result = replace(_v2_result(generated_artifact[0]), v2_provenance_bindings=())
    _patch(monkeypatch, result)

    with pytest.raises(solution_persistence.SolutionPersistenceError):
        solution_persistence.generate_and_persist_solution_draft(
            opportunity, analysis, created_by=owner, schema_version=2
        )

    assert SolutionDraftRecord.objects.count() == 0
    assert SolutionDraftProvenance.objects.count() == 0
