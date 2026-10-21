"""Input style examples cannot authorize facts or extend the output contract."""

import copy
import json
from dataclasses import asdict
from xml.etree import ElementTree

import pytest

from apps.sales.services.requirement_analysis import RequirementStatus
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services.solution_grounding import SolutionDraftGroundingError
from apps.sales.services.solution_prompt_v2 import (
    SolutionV2Section, SolutionV2ContainerKind, SolutionV2PlacementField,
    parse_solution_v2_implementation_output, parse_solution_v2_assurance_output,
)
from apps.sales.tests.test_solution_clarification_action_guard import partial_analysis, deployment_status
from apps.sales.tests.test_solution_requirement_design_scope import messages_for
from apps.sales.tests.test_solution_proposal_admissibility_v2 import _AdmissibilityVerifier, _proposal, _verify, _sent_proposal_packets
from apps.sales.tests.test_solution_semantic_ir_v2 import implementation_ir, assurance_ir


TARGETS = [
    ("implementation", "phases[].objective", SolutionV2Section.IMPLEMENTATION_PLAN,
     SolutionV2ContainerKind.IMPLEMENTATION_PHASE, SolutionV2PlacementField.OBJECTIVE),
    ("implementation", "phases[].tasks", SolutionV2Section.IMPLEMENTATION_PLAN,
     SolutionV2ContainerKind.IMPLEMENTATION_PHASE, SolutionV2PlacementField.TASKS),
    ("assurance", "risks[].mitigation", SolutionV2Section.RISKS,
     SolutionV2ContainerKind.RISK, SolutionV2PlacementField.MITIGATION),
]


def input_style(phase, analysis):
    root = ElementTree.fromstring("<root>" + messages_for(phase, analysis)[1]["content"] + "</root>")
    node = root.find("clarification_action_style")
    assert node is not None, "Unconfirmed inquiry inputs need distinct action/result guidance"
    return root, json.loads(node.text)


@pytest.mark.parametrize("phase", ("implementation", "assurance"))
def test_system_guidance_distinguishes_inquiry_from_admission(phase):
    system = messages_for(phase, partial_analysis())[0]["content"]
    assert "<clarification_action_style>" in system
    assert "不是输出字段或事实依据" in system
    assert "待执行的核验动作" in system
    assert "不要把待核验的结果写成环境可用或容量足够" in system
    assert "不得把事实断言或承诺机械改写成核验动作来规避校验" in system
    assert "不得改变原始需求关联" in system


@pytest.mark.parametrize("phase,expected", [
    ("implementation", ["phases[].objective", "phases[].tasks", "phases[].deliverables", "phases[].timing", "milestones[].outcome"]),
    ("assurance", ["risks[].condition", "risks[].impact", "risks[].mitigation"]),
])
@pytest.mark.parametrize("status", (RequirementStatus.UNKNOWN, RequirementStatus.UNCLEAR, RequirementStatus.CONFLICT))
def test_style_targets_only_approved_fields_and_preserves_customer_context(phase, expected, status):
    analysis = partial_analysis(status)
    before = copy.deepcopy(asdict(analysis))
    root, style = input_style(phase, analysis)
    assert style["targets"] == expected
    assert style["action_examples"]
    assert style["result_counterexamples"]
    assert json.loads(root.find("customer_requirements").text) == json.loads(json.dumps(before))
    assert asdict(analysis) == before


@pytest.mark.parametrize("phase,target,section,kind,field", TARGETS)
def test_style_actions_reach_review_but_result_counterexamples_are_rejected(phase, target, section, kind, field):
    analysis = partial_analysis()
    _, style = input_style(phase, analysis)
    assert target in style["targets"]
    for text in style["action_examples"]:
        proposals = _proposal(text, section=section, container_kind=kind, field=field)
        provider = _AdmissibilityVerifier()
        assert _verify(proposals, provider, analysis=analysis) is proposals
        assert len(provider.calls) == 1
        assert deployment_status(_sent_proposal_packets(provider)[0]) == "unclear"
    for text in style["result_counterexamples"]:
        provider = _AdmissibilityVerifier()
        with pytest.raises(SolutionDraftGroundingError):
            _verify(_proposal(text, section=section, container_kind=kind, field=field), provider, analysis=analysis)
        assert provider.calls == []


@pytest.mark.parametrize("phase,target,section,kind,field", TARGETS)
@pytest.mark.parametrize("decision,atomicity", (("INADMISSIBLE", "ATOMIC"), ("ADMISSIBLE", "COMPOUND")))
def test_style_examples_cannot_override_semantic_or_atomicity_veto(phase, target, section, kind, field, decision, atomicity):
    analysis = partial_analysis()
    _, style = input_style(phase, analysis)
    provider = _AdmissibilityVerifier(decision=decision, atomicity=atomicity)
    proposals = _proposal(style["action_examples"][0], section=section, container_kind=kind, field=field)
    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposals, provider, analysis=analysis)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("phase", ("implementation", "assurance"))
def test_style_is_input_only_and_never_becomes_an_allowed_output_field(phase):
    _, style = input_style(phase, partial_analysis())
    payload = implementation_ir() if phase == "implementation" else assurance_ir()
    payload["clarification_action_style"] = style
    if phase == "implementation":
        parse = lambda text: parse_solution_v2_implementation_output(text, allowed_source_labels=("S1",))
    else:
        implementation = parse_solution_v2_implementation_output(json.dumps(implementation_ir()), allowed_source_labels=("S1",))
        parse = lambda text: parse_solution_v2_assurance_output(text, allowed_source_labels=("S1",), implementation=implementation)
    with pytest.raises(SolutionDraftError) as exc:
        parse(json.dumps(payload))
    assert exc.value.code == "solution_draft_invalid_response"


def test_core_does_not_receive_scoped_action_guidance():
    messages = messages_for("core", partial_analysis())
    root = ElementTree.fromstring("<root>" + messages[1]["content"] + "</root>")
    assert root.find("clarification_action_style") is None
    assert "<clarification_action_style>" not in messages[0]["content"]
