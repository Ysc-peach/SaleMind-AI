"""Guidance examples must agree with the policy and stay input-only."""

from dataclasses import asdict
import pytest

from apps.sales.tests.test_solution_unresolved_policy import evaluate, TARGETS
from apps.sales.tests.test_solution_clarification_generation_guidance import input_style
from apps.sales.tests.test_solution_clarification_action_guard import partial_analysis


@pytest.mark.parametrize("phase,targets", [
    ("implementation", ["phases[].objective", "phases[].tasks", "phases[].deliverables", "phases[].timing", "milestones[].outcome"]),
    ("assurance", ["risks[].condition", "risks[].impact", "risks[].mitigation"]),
])
def test_generated_guidance_targets_and_examples_are_actual_policy_candidates(phase, targets):
    from apps.sales.services.solution_unresolved_policy import unresolved_v2_generation_guidance
    guidance = unresolved_v2_generation_guidance(phase)
    assert list(guidance.targets) == targets
    _, serialized = input_style(phase, partial_analysis())
    assert serialized["targets"] == targets
    assert len(serialized["field_examples"]) == len(targets)
    for example in guidance.field_examples:
        field = example.target.split(".")[-1]
        placement = next(placement for placement, _ in TARGETS if placement[-1] == field
                         and (placement[0] == "risks") == (phase == "assurance")
                         and (placement[0] == "milestones") == example.target.startswith("milestones"))
        result = evaluate(example.text, placement)
        assert result.decision.value == "candidate"
        assert asdict(example)["kind"].value in ["inquiry", "conditional_work", "planned_artifact", "hypothetical_risk", "verification_outcome"]


def test_core_has_no_new_guidance_contract():
    from apps.sales.services.solution_unresolved_policy import unresolved_v2_generation_guidance
    assert unresolved_v2_generation_guidance("core") is None
