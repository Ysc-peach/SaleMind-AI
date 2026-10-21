"""Formal integration: candidates retain precision/provenance/semantic vetoes."""

import pytest
from apps.sales.services.requirement_analysis import RequirementDimension
from apps.sales.services.solution_grounding import SolutionDraftGroundingError
from apps.sales.services.solution_prompt_v2 import SolutionV2Section, SolutionV2ContainerKind, SolutionV2PlacementField
from apps.sales.services.verifier_diagnostics import VerifierEvaluationDiagnostics
from apps.sales.tests.test_solution_unresolved_policy import TARGETS
from apps.sales.tests.test_solution_clarification_action_guard import partial_analysis
from apps.sales.tests.test_solution_proposal_admissibility_v2 import _proposal, _verify, _AdmissibilityVerifier, _sent_proposal_packets


def proposals_for(placement, text, **kwargs):
    section, kind, field = placement
    return _proposal(text, section=SolutionV2Section(section), container_kind=SolutionV2ContainerKind(kind), field=SolutionV2PlacementField(field), **kwargs)


@pytest.mark.parametrize("placement,text", TARGETS)
def test_new_purpose_reaches_semantic_packet_unchanged(placement, text):
    provider = _AdmissibilityVerifier()
    proposals = proposals_for(placement, text)
    assert _verify(proposals, provider, analysis=partial_analysis()) is proposals
    assert _sent_proposal_packets(provider)[0]["text"] == text


@pytest.mark.parametrize("placement,text", TARGETS)
@pytest.mark.parametrize("decision,atomicity", [("INADMISSIBLE", "ATOMIC"), ("ADMISSIBLE", "COMPOUND")])
def test_every_planning_purpose_still_has_independent_semantic_veto(placement, text, decision, atomicity):
    provider = _AdmissibilityVerifier(decision=decision, atomicity=atomicity)
    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposals_for(placement, text), provider, analysis=partial_analysis())
    assert len(provider.calls) == 1


@pytest.mark.parametrize("text,code", [
    ("在环境与容量核验完成后开展建设。", "solution_draft_unqualified_precondition"),
    ("现有服务器容量已经足够。", "solution_draft_unconfirmed_assertion"),
    ("处理任意未列明事项。", "solution_draft_expression_unclassified"),
])
def test_failed_policy_has_typed_safe_error_without_verifier(text, code):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError) as error:
        _verify(proposals_for(TARGETS[3][0], text), provider, analysis=partial_analysis())
    assert error.value.code == code
    assert text not in error.value.safe_message
    assert provider.calls == []


def test_genuinely_satisfied_condition_still_rejects_unsupported_precision():
    provider = _AdmissibilityVerifier()
    diagnostics = VerifierEvaluationDiagnostics()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposals_for(TARGETS[1][0], "若经核验部署条件满足，则配置2台服务器"), provider, analysis=partial_analysis(), diagnostics=diagnostics)
    assert diagnostics.deterministic_rejections[0].reason_code == "unsupported_precision"
    assert diagnostics.precision_rejections[0].matched_value == "2台"
    assert provider.calls == []


@pytest.mark.parametrize("related", [(), (RequirementDimension.BUSINESS_GOAL,)])
@pytest.mark.parametrize("text", [
    "服务器容量已经足够，但还需评估其它事项",
    "核验部署条件。服务器容量已经足够，但还需评估其它事项",
])
def test_unparsed_tail_cannot_remove_explicit_unresolved_dependency(text, related):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError) as error:
        _verify(proposals_for(TARGETS[3][0], text, related=related), provider, analysis=partial_analysis())
    assert error.value.code == "invalid_solution_grounding_input"
    assert provider.calls == []


@pytest.mark.parametrize("object_name", ["预算", "用户规模", "权限配置", "数据库版本"])
def test_unrelated_satisfied_object_cannot_release_deployment_dependency(object_name):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError) as error:
        _verify(proposals_for(TARGETS[3][0], f"经核验确认{object_name}满足后开展部署"), provider, analysis=partial_analysis())
    assert error.value.code == "solution_draft_unqualified_precondition"
    assert provider.calls == []


def test_consequence_server_object_cannot_impersonate_satisfied_prerequisite():
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError) as error:
        _verify(proposals_for(TARGETS[3][0], "若预算足够，则配置2台服务器"), provider, analysis=partial_analysis())
    assert error.value.code == "solution_draft_unqualified_precondition"
    assert provider.calls == []
