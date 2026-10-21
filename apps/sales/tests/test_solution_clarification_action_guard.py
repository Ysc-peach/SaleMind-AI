"""Scoped clarification candidates still require all existing safety gates."""

from dataclasses import replace

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.sales.services.requirement_analysis import RequirementDimension, RequirementFieldAnalysis, RequirementStatus
from apps.sales.services.solution_grounding import SolutionDraftGroundingError, _asserts_unresolved_as_confirmed
from apps.sales.services.solution_prompt_v2 import (
    AtomicSolutionProposalSetV2, SolutionV2Section, SolutionV2ContainerKind, SolutionV2PlacementField,
)
from apps.sales.tests.test_solution_proposal_admissibility_v2 import (
    _AdmissibilityVerifier, _proposal, _verify, _sent_proposal_packets,
)
from apps.sales.tests.test_solution_v2_pipeline import analysis_fixture


SCOPES = [
    (SolutionV2Section.IMPLEMENTATION_PLAN, SolutionV2ContainerKind.IMPLEMENTATION_PHASE, SolutionV2PlacementField.TASKS),
    (SolutionV2Section.RISKS, SolutionV2ContainerKind.RISK, SolutionV2PlacementField.MITIGATION),
    (SolutionV2Section.IMPLEMENTATION_PLAN, SolutionV2ContainerKind.IMPLEMENTATION_PHASE, SolutionV2PlacementField.OBJECTIVE),
]


def partial_analysis(status=RequirementStatus.UNCLEAR):
    original = analysis_fixture()
    return replace(original, requirements=replace(original.requirements,
        deployment_requirement=RequirementFieldAnalysis(status, None, "服务器资源尚未核验。")))


def action(text, scope, *, citations=("S1",)):
    section, container, field = scope
    return _proposal(text, section=section, container_kind=container, field=field, citations=citations)


def deployment_status(packet):
    return next(item["analysis"]["status"]
                for item in packet["customer_context"]["requirements"]
                if item["field"] == "deployment_requirement")


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", [
    "实施前核对可用服务器资源。", "评估服务器容量是否满足本期部署需求。",
    "开展容量评估。", "核验部署条件，并记录核验结果。", "核对服务器资源，评估部署条件。",
])
def test_clear_clarification_actions_continue_to_semantic_review_without_state_change(scope, text):
    analysis = partial_analysis()
    before = analysis.requirements
    provider = _AdmissibilityVerifier()
    proposals = action(text, scope)
    assert _verify(proposals, provider, analysis=analysis) is proposals
    assert len(provider.calls) == 1
    assert deployment_status(_sent_proposal_packets(provider)[0]) == "unclear"
    assert analysis.requirements == before


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", [
    "确认本期试点在现有环境中的实施边界与环境可用性。",
    "核验本期试点的部署条件。",
    "评估本阶段项目在目标环境中的资源容量。",
    "确认本期试点的实施边界，并记录核验结果。",
    "确认本期试点实施所依赖的现有环境与部署边界。",
    "核验项目实施所依赖的现有环境。",
    "评估本阶段项目实施所依赖的部署边界。",
])
def test_scoped_inquiry_goals_with_project_context_continue_to_semantic_review(scope, text):
    provider = _AdmissibilityVerifier()
    proposals = action(text, scope)
    assert _verify(proposals, provider, analysis=partial_analysis()) is proposals
    assert len(provider.calls) == 1
    assert deployment_status(_sent_proposal_packets(provider)[0]) == "unclear"


@pytest.mark.parametrize("status", (RequirementStatus.UNKNOWN, RequirementStatus.UNCLEAR, RequirementStatus.CONFLICT))
def test_observed_objective_preserves_known_background_and_unresolved_deployment(status):
    analysis = partial_analysis(status)
    before = analysis.requirements
    provider = _AdmissibilityVerifier()
    proposals = _proposal(
        "确认本期试点在现有环境中的实施边界与环境可用性。",
        section=SolutionV2Section.IMPLEMENTATION_PLAN,
        container_kind=SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        field=SolutionV2PlacementField.OBJECTIVE,
        related=(RequirementDimension.EXISTING_ENVIRONMENT, RequirementDimension.DEPLOYMENT_REQUIREMENT),
    )
    assert _verify(proposals, provider, analysis=analysis) is proposals
    assert len(provider.calls) == 1
    packet = _sent_proposal_packets(provider)[0]
    statuses = {item["field"]: item["analysis"]["status"]
                for item in packet["customer_context"]["requirements"]}
    assert statuses["existing_environment"] == "known"
    assert statuses["deployment_requirement"] == status.value
    assert analysis.requirements == before


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", [
    "确认本期试点在现有环境中的实施边界与环境可用性，并保证按期上线。",
    "确认本期试点在现有环境中的服务器容量已满足需求。",
    "本期试点在现有环境中的资源足够。",
    "已确认本期试点在现有环境中的环境可用性。",
    "确认本期试点实施所依赖的现有环境与部署边界，并保证按期上线。",
    "本期试点实施所依赖的现有环境已经足够。",
    "确认本期试点实施所依赖的现有环境已满足部署需求。",
])
def test_project_context_cannot_disguise_assertions_or_promises(scope, text):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(action(text, scope), provider, analysis=partial_analysis())
    assert provider.calls == []


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("status", (RequirementStatus.UNKNOWN, RequirementStatus.UNCLEAR, RequirementStatus.CONFLICT))
def test_clarification_does_not_promote_any_nonknown_requirement_status(scope, status):
    analysis = partial_analysis(status)
    provider = _AdmissibilityVerifier()
    proposals = action("核对服务器容量。", scope)
    assert _verify(proposals, provider, analysis=analysis) is proposals
    assert deployment_status(_sent_proposal_packets(provider)[0]) == status.value


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", [
    "核对服务器资源，现有容量已经足够。",
    "核对服务器资源并保证按期上线。",
    "确认服务器容量已满足需求。",
    "无需核对服务器资源，直接部署。",
    "若客户同意，现有容量已满足部署需求。",
    "若客户同意，保证按期交付。",
    "若客户确认资源，再安排部署。现有容量已经足够。",
    "先核对服务器资源，再视为部署要求已确认。",
    "若资源足够，则无需确认就直接上线。",
    "若客户同意，现有容量满足部署需求。",
    "若客户同意，现有环境具备部署能力。",
    "确认后，现有资源支持全部部署需求。",
    "若客户同意，则核对服务器容量并保证按期上线。",
    "待客户确认部署条件后，则现有容量满足部署需求。",
])
def test_mixed_assertions_and_false_conditional_prefixes_are_rejected_before_verifier(scope, text):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError) as exc:
        _verify(action(text, scope), provider, analysis=partial_analysis())
    assert exc.value.code in {"solution_draft_unconfirmed_assertion", "solution_draft_expression_unclassified"}
    assert provider.calls == []


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", [
    "若服务器容量足够，则安排部署。",
    "经核验确认部署条件满足后安排部署。",
    "若客户提供资源，核对服务器容量是否足够。",
    "若客户提供资源，评估服务器容量是否满足本期部署需求。",
    "待客户确认服务器容量足够后安排部署。",
    "若客户同意，则评估服务器容量是否足够。",
    "若客户同意，那么评估服务器容量是否足够。",
    "若客户同意，就评估服务器容量是否足够。",
    "若客户同意，再评估服务器容量是否足够。",
    "待客户确认部署条件后，则评估服务器容量是否足够。",
    "待客户确认部署条件后，那么评估服务器容量是否足够。",
    "待客户确认部署条件后，就评估服务器容量是否足够。",
    "待客户确认部署条件后，再评估服务器容量是否足够。",
])
def test_genuine_conditional_arrangements_still_continue_to_review(scope, text):
    provider = _AdmissibilityVerifier()
    proposals = action(text, scope)
    assert _verify(proposals, provider, analysis=partial_analysis()) is proposals
    assert len(provider.calls) == 1


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", [
    "核对服务器资源，并保证3天上线。",
    "若客户确认，配置2台服务器。",
    "若客户确认，保证10000 QPS。",
])
def test_clarification_or_condition_cannot_authorize_unsupported_precision(scope, text):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(action(text, scope), provider, analysis=partial_analysis())
    assert provider.calls == []


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("text", ("", "。；！？"))
def test_empty_scoped_actions_fail_closed_even_without_parser(scope, text):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(action(text, scope), provider, analysis=partial_analysis())
    assert provider.calls == []


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("citations", ((), ("S9",), ("S1", "S1")))
def test_action_recognition_never_bypasses_citation_admission(scope, citations):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(action("核对服务器容量。", scope, citations=citations), provider, analysis=partial_analysis())
    assert provider.calls == []


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("decision,atomicity", (("INADMISSIBLE", "ATOMIC"), ("ADMISSIBLE", "COMPOUND")))
def test_recognized_action_still_obeys_admissibility_and_atomicity_veto(scope, decision, atomicity):
    provider = _AdmissibilityVerifier(decision=decision, atomicity=atomicity)
    with pytest.raises(SolutionDraftGroundingError):
        _verify(action("核对服务器容量。", scope), provider, analysis=partial_analysis())
    assert len(provider.calls) == 1


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("mode", ("provider_error", "malformed", "empty_results"))
def test_recognized_action_cannot_substitute_for_a_valid_verifier_result(scope, mode):
    class FailingVerifier(_AdmissibilityVerifier):
        def generate(self, messages, *, max_output_tokens=None):
            super().generate(messages, max_output_tokens=max_output_tokens)
            if mode == "provider_error":
                raise LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)
            return LLMGeneration("invalid" if mode == "malformed" else '{"results": []}')

    analysis = partial_analysis()
    before = analysis.requirements
    provider = FailingVerifier()
    with pytest.raises((SolutionDraftGroundingError, LLMProviderError)):
        _verify(action("核对服务器容量。", scope), provider, analysis=analysis)
    assert len(provider.calls) == 1
    assert analysis.requirements == before


@pytest.mark.parametrize("scope", SCOPES)
def test_action_still_requires_linked_requirement_context(scope):
    analysis = partial_analysis()
    analysis = replace(analysis, requirements=replace(analysis.requirements,
        deployment_requirement=RequirementFieldAnalysis(RequirementStatus.UNCLEAR, None, None)),
        conflicts=(), clarifying_questions=())
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(action("核对服务器容量。", scope), provider, analysis=analysis)
    assert provider.calls == []


@pytest.mark.parametrize("scope", [
    (SolutionV2Section.ARCHITECTURE, SolutionV2ContainerKind.ARCHITECTURE_COMPONENT, SolutionV2PlacementField.RATIONALE),
    (SolutionV2Section.IMPLEMENTATION_PLAN, SolutionV2ContainerKind.IMPLEMENTATION_PHASE, SolutionV2PlacementField.DELIVERABLES),
    (SolutionV2Section.RISKS, SolutionV2ContainerKind.RISK, SolutionV2PlacementField.CONDITION),
])
def test_action_exception_does_not_expand_to_other_placements_or_legacy_guard(scope):
    analysis = partial_analysis()
    assert _asserts_unresolved_as_confirmed(analysis, (RequirementDimension.DEPLOYMENT_REQUIREMENT,), "核对服务器容量。")
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(action("核对服务器容量。", scope), provider, analysis=analysis)
    assert provider.calls == []


def test_mitigation_keeps_only_its_matching_untrusted_risk_context():
    mitigation = action("核对服务器容量。", SCOPES[1]).proposals[0]
    condition = replace(mitigation, text="若资源核验发现容量缺口，则可能影响试点。",
                        placement=replace(mitigation.placement, field=SolutionV2PlacementField.CONDITION))
    impact = replace(condition, text="若缺口未解决，试点可能无法按约定范围开展。",
                     placement=replace(condition.placement, field=SolutionV2PlacementField.IMPACT))
    provider = _AdmissibilityVerifier()
    proposals = AtomicSolutionProposalSetV2((mitigation, condition, impact))
    assert _verify(proposals, provider, analysis=partial_analysis()) is proposals
    packet = next(p for p in _sent_proposal_packets(provider) if p["text"] == mitigation.text)
    assert packet["risk_condition"] == [condition.text]
    assert packet["risk_impact"] == [impact.text]
    assert deployment_status(packet) == "unclear"
