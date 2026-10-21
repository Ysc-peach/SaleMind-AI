"""A qualified inquiry list is a candidate, never an admitted fact or result."""

from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from apps.sales.services.requirement_analysis import RequirementDimension, RequirementFieldAnalysis, RequirementStatus
from apps.sales.services.solution_grounding import SolutionDraftGroundingError, _asserts_unresolved_as_confirmed
from apps.sales.services.solution_prompt_v2 import SolutionV2Section, SolutionV2ContainerKind, SolutionV2PlacementField
from apps.sales.services.verifier_diagnostics import VerifierEvaluationDiagnostics
from apps.sales.tests.test_solution_clarification_action_guard import SCOPES, partial_analysis, deployment_status
from apps.sales.tests.test_solution_proposal_admissibility_v2 import _AdmissibilityVerifier, _proposal, _verify, _sent_proposal_packets


OBSERVED_INQUIRY = "核验现有SalesMind AI环境的部署条件、网络访问边界与服务器容量是否满足本期部署需求。"
OBSERVED_SECOND_OBJECT = "核验本期部署条件与现有SalesMind AI环境的可用服务器容量。"
RELATED = (RequirementDimension.DEPLOYMENT_REQUIREMENT, RequirementDimension.EXISTING_ENVIRONMENT)


def qualified_inquiry(text, scope, *, citations=("S1",)):
    section, kind, field = scope
    return _proposal(text, section=section, container_kind=kind, field=field,
                     related=RELATED, citations=citations)


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("status", (RequirementStatus.UNKNOWN, RequirementStatus.UNCLEAR, RequirementStatus.CONFLICT))
@pytest.mark.parametrize("text", [
    OBSERVED_INQUIRY,
    "核验部署条件、网络访问边界与服务器容量是否满足本期部署需求。",
    "核验现有环境的部署条件与服务器容量是否满足本期部署需求。",
    "评估当前Knowledge Portal环境的部署条件。",
    "核验目标DocHub环境的网络访问边界，并记录核验结果。",
    OBSERVED_SECOND_OBJECT,
    "核验部署条件、当前Knowledge Portal环境的网络访问边界与服务器容量。",
    "评估现有DocHub环境的部署条件与目标Knowledge Portal环境的服务器容量是否足够。",
])
def test_qualified_inquiry_list_reaches_verifier_unchanged_without_confirming_results(scope, status, text):
    analysis = partial_analysis(status)
    before = deepcopy(asdict(analysis))
    proposals = qualified_inquiry(text, scope)
    provider = _AdmissibilityVerifier()
    assert _verify(proposals, provider, analysis=analysis) is proposals
    assert len(provider.calls) == 1
    packet = _sent_proposal_packets(provider)[0]
    assert packet["text"] == text
    assert deployment_status(packet) == status.value
    assert packet["related_requirement_fields"] == [field.value for field in RELATED]
    assert asdict(analysis) == before


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", [
    "现有SalesMind AI环境的部署条件与服务器容量已满足需求。",
    "核验现有SalesMind AI环境的部署条件与服务器容量满足本期部署需求。",
    "已核验现有SalesMind AI环境的部署条件、网络访问边界与服务器容量。",
    "无需核验现有SalesMind AI环境的部署条件，直接部署。",
    "核验现有SalesMind AI环境的部署条件、网络访问边界与服务器容量，并保证按期交付。",
    "核验现有SalesMind AI环境的部署条件。现有服务器容量已经足够。",
    "核验现有SalesMind AI环境的部署条件、已足够的服务器容量是否满足本期部署需求。",
    "核验现有SalesMind AI环境的部署条件与所有未列明能力。",
    "核验现有SalesMind AI环境的部署条件与服务器容量是否满足本期部署需求并确保上线。",
    "核验现有容量已足够环境的部署条件。",
    "核验现有SalesMind AI环境已可用的部署条件。",
    "若客户同意，核验现有SalesMind AI环境的部署条件并保证交付。",
    "核验本期部署条件与现有服务器容量已足够。",
    "核验部署条件与现有容量已足够环境的服务器容量。",
    "核验部署条件、现有SalesMind AI环境的服务器容量已满足需求。",
])
def test_qualified_object_list_cannot_hide_assertions_promises_or_unknown_objects(scope, text):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(qualified_inquiry(text, scope), provider, analysis=partial_analysis())
    assert provider.calls == []


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("decision,atomicity", (("INADMISSIBLE", "ATOMIC"), ("ADMISSIBLE", "COMPOUND")))
@pytest.mark.parametrize("text", (OBSERVED_INQUIRY, OBSERVED_SECOND_OBJECT))
def test_combined_inquiry_still_requires_admissibility_and_coherent_work_package(scope, decision, atomicity, text):
    provider = _AdmissibilityVerifier(decision=decision, atomicity=atomicity)
    with pytest.raises(SolutionDraftGroundingError):
        _verify(qualified_inquiry(text, scope), provider, analysis=partial_analysis())
    assert len(provider.calls) == 1
    assert _sent_proposal_packets(provider)[0]["text"] == text


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("citations", ((), ("S9",), ("S1", "S1")))
def test_combined_inquiry_cannot_bypass_citation_admission(scope, citations):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(qualified_inquiry(OBSERVED_INQUIRY, scope, citations=citations), provider, analysis=partial_analysis())
    assert provider.calls == []


@pytest.mark.parametrize("scope", SCOPES)
def test_combined_inquiry_cannot_bypass_linked_requirement_context(scope):
    analysis = partial_analysis()
    analysis = replace(analysis, requirements=replace(analysis.requirements,
        deployment_requirement=RequirementFieldAnalysis(RequirementStatus.UNCLEAR, None, None)),
        conflicts=(), clarifying_questions=())
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(qualified_inquiry(OBSERVED_INQUIRY, scope), provider, analysis=analysis)
    assert provider.calls == []


@pytest.mark.parametrize("scope", SCOPES)
def test_recognized_inquiry_does_not_authorize_following_unsupported_capacity_precision(scope):
    text = "核验现有SalesMind AI环境的部署条件。若经核验部署条件满足，则配置2台服务器。"
    provider = _AdmissibilityVerifier()
    diagnostics = VerifierEvaluationDiagnostics()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(qualified_inquiry(text, scope), provider,
                analysis=partial_analysis(), diagnostics=diagnostics)
    assert diagnostics.deterministic_rejections[0].reason_code == "unsupported_precision"
    assert diagnostics.precision_rejections[0].matched_value == "2台"
    assert provider.calls == []


@pytest.mark.parametrize("scope", [
    (SolutionV2Section.ARCHITECTURE, SolutionV2ContainerKind.ARCHITECTURE_COMPONENT, SolutionV2PlacementField.RATIONALE),
    (SolutionV2Section.IMPLEMENTATION_PLAN, SolutionV2ContainerKind.IMPLEMENTATION_PHASE, SolutionV2PlacementField.DELIVERABLES),
    (SolutionV2Section.RISKS, SolutionV2ContainerKind.RISK, SolutionV2PlacementField.CONDITION),
])
def test_combined_inquiry_does_not_change_other_placements_or_legacy_guard(scope):
    analysis = partial_analysis()
    assert _asserts_unresolved_as_confirmed(analysis, RELATED, OBSERVED_INQUIRY)
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(qualified_inquiry(OBSERVED_INQUIRY, scope), provider, analysis=analysis)
    assert provider.calls == []
