"""Evaluation diagnostics come from the rejecting production guard branch."""

from dataclasses import replace

import pytest

from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
from apps.sales.services.requirement_analysis import (
    RequirementDimension,
    RequirementFieldAnalysis,
    RequirementStatus,
)
from apps.sales.services.solution_grounding import SolutionDraftGroundingError
from apps.sales.services.verifier_diagnostics import VerifierEvaluationDiagnostics
from apps.sales.tests.test_solution_proposal_admissibility_v2 import (
    _AdmissibilityVerifier,
    _proposal,
    _verify,
)
from apps.sales.tests.test_solution_v2_pipeline import analysis_fixture
from apps.sales.services.solution_prompt_v2 import AtomicSolutionProposalSetV2


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("proposals", "analysis", "expected_reason", "expected_error"),
    [
        (
            _proposal("客户将使用 OIDC 完成身份集成。", related=(RequirementDimension.INTEGRATION_REQUIREMENT,)),
            None,
            "unresolved_as_confirmed",
            "solution_draft_not_grounded",
        ),
        (
            _proposal("建议按 10000 QPS 配置容量。"),
            None,
            "unsupported_precision",
            "solution_draft_not_grounded",
        ),
        (
            _proposal("建议采用私有化部署。", citations=("S2",)),
            None,
            "invalid_grounding_reference",
            "invalid_solution_grounding_input",
        ),
    ],
)
def test_rejecting_guard_emits_safe_reason_without_persistence(
    proposals, analysis, expected_reason, expected_error,
):
    provider = _AdmissibilityVerifier()
    diagnostics = VerifierEvaluationDiagnostics()
    with pytest.raises(SolutionDraftGroundingError) as exc:
        _verify(proposals, provider, analysis=analysis, diagnostics=diagnostics)

    assert exc.value.code == expected_error
    assert provider.calls == []
    assert len(diagnostics.deterministic_rejections) == 1
    item = diagnostics.deterministic_rejections[0]
    assert item.proposal_index == 0
    assert item.placement == {
        "section": "architecture",
        "container_kind": "architecture_component",
        "container_key": "application_boundary",
        "field": "rationale",
    }
    assert item.claim_type == "proposal"
    assert item.reason_code.value == expected_reason
    assert item.guard_name in {
        "_asserts_unresolved_as_confirmed",
        "_unsupported_precision_match",
        "verify_atomic_solution_v2_proposals.citation_validation",
    }
    assert item.related_requirement_fields
    assert item.citation_count == len(proposals.proposals[0].citations)
    assert item.grounding_present is (expected_reason != "invalid_grounding_reference")
    assert len(item.proposal_excerpt) <= 160
    assert SolutionDraftRecord.objects.count() == 0
    assert SolutionDraftProvenance.objects.count() == 0
    assert not ({"api_key", "prompt", "raw_response", "source_content"} & item.safe_dict().keys())


@pytest.mark.django_db
def test_invalid_requirement_context_has_distinct_reason():
    analysis = analysis_fixture()
    analysis = replace(
        analysis,
        requirements=replace(
            analysis.requirements,
            business_goal=RequirementFieldAnalysis(RequirementStatus.UNKNOWN, None, None),
        ),
    )
    diagnostics = VerifierEvaluationDiagnostics()
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError) as exc:
        _verify(
            _proposal("建议采用私有化部署。", related=(RequirementDimension.BUSINESS_GOAL,)),
            provider,
            analysis=analysis,
            diagnostics=diagnostics,
        )
    assert exc.value.code == "invalid_solution_grounding_input"
    assert diagnostics.deterministic_rejections[0].reason_code.value == "invalid_requirement_linkage"
    assert provider.calls == []


def test_valid_proposal_emits_no_deterministic_rejection():
    diagnostics = VerifierEvaluationDiagnostics()
    _verify(_proposal("建议采用私有化部署。"), _AdmissibilityVerifier(), diagnostics=diagnostics)
    assert diagnostics.deterministic_rejections == ()


def test_rejection_retains_nonzero_proposal_index_and_truncates_excerpt():
    first = _proposal("建议采用私有化部署。").proposals[0]
    second = _proposal("建议按 10000 QPS 配置容量。" + "不输出的客户资料" * 40).proposals[0]
    diagnostics = VerifierEvaluationDiagnostics()
    provider = _AdmissibilityVerifier()

    with pytest.raises(SolutionDraftGroundingError):
        _verify(
            AtomicSolutionProposalSetV2((first, second)),
            provider,
            diagnostics=diagnostics,
        )

    item = diagnostics.deterministic_rejections[0]
    assert item.proposal_index == 1
    assert item.claim_id == "proposals[1]"
    assert item.matched_category == "unsupported_capacity_precision"
    assert item.matched_value == "10000 QPS"
    assert len(item.proposal_excerpt) == 160
    assert "不输出的客户资料" * 30 not in item.proposal_excerpt
    assert provider.calls == []
