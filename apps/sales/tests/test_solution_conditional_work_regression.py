"""Observed conditional work remains a candidate, never fact admission."""

from dataclasses import asdict, replace
import re

import pytest

from apps.sales.services.requirement_analysis import (
    RequirementDimension as D, RequirementFieldAnalysis, RequirementStatus as S,
)
from apps.sales.services.solution_grounding import SolutionDraftGroundingError
from apps.sales.services.solution_plan_expressions import parse_plan_expression
from apps.sales.services.solution_unresolved_policy import evaluate_unresolved_v2_policy
from apps.sales.services.verifier_diagnostics import VerifierEvaluationDiagnostics
from apps.sales.tests.test_solution_clarification_action_guard import partial_analysis
from apps.sales.tests.test_solution_proposal_admissibility_v2 import (
    _AdmissibilityVerifier, _verify, _sent_proposal_packets,
)
from apps.sales.tests.test_solution_requirement_design_scope import messages_for
from apps.sales.tests.test_solution_unresolved_policy_integration import proposals_for


OBSERVED_TEXT = "在核验确认部署条件满足后，按已验证方案完成检索入口、上传索引与检索服务的落地接入。"
OBJECTIVE = ("implementation_plan", "implementation_phase", "objective")
ORIGINAL_LINKS = (D.EXISTING_ENVIRONMENT, D.INTEGRATION_REQUIREMENT)
COMPLETE_LINKS = ORIGINAL_LINKS + (D.DEPLOYMENT_REQUIREMENT,)


def observed_analysis(status=S.UNCLEAR):
    # Snapshot 297 has known environment/integration and non-known deployment.
    # The generic partial_analysis fixture instead has unclear integration.
    analysis = partial_analysis(status)
    return replace(analysis, requirements=replace(analysis.requirements,
        integration_requirement=RequirementFieldAnalysis(
            S.KNOWN, "一期沿用现有账号登录。", "一期沿用现有账号登录。",
        )))


def policy(text, *, related=COMPLETE_LINKS, analysis=None, placement=OBJECTIVE):
    return evaluate_unresolved_v2_policy(
        analysis=analysis or observed_analysis(), related_fields=related,
        text=text, placement=placement,
    )


@pytest.mark.parametrize("text", (
    OBSERVED_TEXT,
    "经核验确认部署条件满足后，完成检索入口的接入。",
    "在核验确认部署条件满足后,按已验证方案完成检索服务与上传索引的接入。",
    "若经核验部署条件满足，则接入上传索引和检索入口。",
))
def test_complete_satisfied_condition_and_bounded_technical_work_are_parsed(text):
    clauses = parse_plan_expression(text)
    assert clauses is not None
    assert [(c.kind.value, c.prerequisite.value, c.dependencies) for c in clauses] == [
        ("conditional_work", "satisfied", ("deployment_requirement",)),
    ]


@pytest.mark.parametrize("status", (S.UNKNOWN, S.UNCLEAR, S.CONFLICT))
def test_observed_sentence_with_correct_links_is_a_candidate_without_mutation(status):
    analysis = observed_analysis(status)
    before = asdict(analysis)
    assert policy(OBSERVED_TEXT, analysis=analysis).decision.value == "candidate"
    assert asdict(analysis) == before


@pytest.mark.parametrize("links", (ORIGINAL_LINKS, (), (D.BUSINESS_GOAL,)))
def test_observed_missing_deployment_link_is_still_rejected_before_verifier(links):
    provider = _AdmissibilityVerifier()
    with pytest.raises(SolutionDraftGroundingError) as error:
        _verify(proposals_for(OBJECTIVE, OBSERVED_TEXT, related=links),
                provider, analysis=observed_analysis())
    assert error.value.code == "invalid_solution_grounding_input"
    assert provider.calls == []


def test_completed_check_is_not_satisfied_deployment_for_technical_work():
    text = "在部署条件核验完成后，按已验证方案完成检索入口的落地接入。"
    clauses = parse_plan_expression(text)
    assert clauses is not None
    assert clauses[0].prerequisite.value == "completed"
    assert policy(text).reason.value == "unqualified_precondition"


@pytest.mark.parametrize("text", (
    "在核验确认部署条件不满足后，完成检索入口的接入。",
    "在核验确认部署条件满足后，保证完成检索入口的接入。",
    "在核验确认部署条件满足后，完成检索入口的接入并保证按期上线。",
    "在核验确认部署条件满足后，完成检索入口的接入，现有容量已经足够。",
    "在核验确认部署条件满足后，完成检索入口的接入。无需核验服务器容量。",
    "在核验确认部署条件满足后，完成检索入口与自动业务审批的接入。",
    "在核验确认部署条件满足后，完成检索入口的接入以及其它任意事项。",
    "在核验确认部署条件满足后，按已验证方案承诺检索入口已完成接入。",
))
def test_conditions_cannot_hide_assertions_or_unconsumed_work_tails(text):
    result = policy(text)
    assert result is not None and result.decision.value != "candidate"


def test_unrelated_satisfied_budget_does_not_release_deployment_for_new_work():
    result = policy("经核验确认预算满足后，完成检索入口的接入。")
    assert result.reason.value == "unqualified_precondition"


def test_satisfied_deployment_cannot_release_separate_unconfirmed_environment():
    analysis = observed_analysis()
    analysis = replace(analysis, requirements=replace(analysis.requirements,
        existing_environment=RequirementFieldAnalysis(S.UNCLEAR, None, "环境尚未核验")))
    assert policy(OBSERVED_TEXT, analysis=analysis).reason.value == "unqualified_precondition"


def test_observed_candidate_reaches_formal_verifier_with_original_text_and_links():
    analysis = observed_analysis()
    before = asdict(analysis)
    provider = _AdmissibilityVerifier()
    proposals = proposals_for(OBJECTIVE, OBSERVED_TEXT, related=COMPLETE_LINKS)
    assert _verify(proposals, provider, analysis=analysis) is proposals
    packet = _sent_proposal_packets(provider)[0]
    assert packet["text"] == OBSERVED_TEXT
    assert packet["related_requirement_fields"] == [
        "existing_environment", "integration_requirement", "deployment_requirement",
    ]
    assert asdict(analysis) == before


@pytest.mark.parametrize("decision,atomicity", (
    ("INADMISSIBLE", "ATOMIC"), ("ADMISSIBLE", "COMPOUND"),
))
def test_observed_candidate_still_has_independent_semantic_and_atomicity_veto(decision, atomicity):
    provider = _AdmissibilityVerifier(decision=decision, atomicity=atomicity)
    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposals_for(OBJECTIVE, OBSERVED_TEXT, related=COMPLETE_LINKS),
                provider, analysis=observed_analysis())
    assert len(provider.calls) == 1


def test_satisfied_connector_does_not_bypass_unsupported_precision():
    provider = _AdmissibilityVerifier()
    diagnostics = VerifierEvaluationDiagnostics()
    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposals_for(OBJECTIVE, "在核验确认部署条件满足后，配置2台服务器。",
                              related=(D.DEPLOYMENT_REQUIREMENT,)),
                provider, analysis=partial_analysis(), diagnostics=diagnostics)
    assert diagnostics.deterministic_rejections[0].reason_code == "unsupported_precision"
    assert provider.calls == []


def test_observed_condition_does_not_release_unclear_integration_from_generic_fixture():
    result = policy(OBSERVED_TEXT, analysis=partial_analysis())
    assert result.reason.value == "unqualified_precondition"


def test_removing_technical_work_recognition_is_detected_and_restored(monkeypatch):
    from apps.sales.services import solution_plan_expressions as expressions
    test_observed_sentence_with_correct_links_is_a_candidate_without_mutation(S.UNCLEAR)
    with monkeypatch.context() as mutant:
        mutant.setattr(expressions, "_WORK", re.compile(r"开展建设\Z"))
        with pytest.raises(AssertionError):
            test_observed_sentence_with_correct_links_is_a_candidate_without_mutation(S.UNCLEAR)
    test_observed_sentence_with_correct_links_is_a_candidate_without_mutation(S.UNCLEAR)


def test_open_ended_work_tail_mutation_is_detected_and_restored(monkeypatch):
    from apps.sales.services import solution_plan_expressions as expressions
    text = "在核验确认部署条件满足后，完成检索入口的接入并保证按期上线。"
    test_conditions_cannot_hide_assertions_or_unconsumed_work_tails(text)
    with monkeypatch.context() as mutant:
        mutant.setattr(expressions, "_WORK", re.compile(r".+\Z"))
        with pytest.raises(AssertionError):
            test_conditions_cannot_hide_assertions_or_unconsumed_work_tails(text)
    test_conditions_cannot_hide_assertions_or_unconsumed_work_tails(text)


@pytest.mark.parametrize("phase", ("implementation", "assurance"))
def test_public_generation_request_explicitly_guides_deployment_linkage(phase):
    # Verify the provider-bound request; this does not claim model compliance.
    system = messages_for(phase, partial_analysis())[0]["content"]
    assert "部署条件、服务器容量或承载条件" in system
    assert "related_requirement_fields 必须包含 deployment_requirement" in system
    assert "不能只用 existing_environment 或 integration_requirement 代替" in system
