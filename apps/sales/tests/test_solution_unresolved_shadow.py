"""Offline comparison never replaces the formal guard or invokes a provider."""

import pytest
from apps.sales.services.solution_grounding import _asserts_unresolved_as_confirmed
from apps.sales.services.requirement_analysis import RequirementDimension
from apps.sales.tests.test_solution_clarification_action_guard import partial_analysis
from apps.sales.tests.test_solution_unresolved_policy import evaluate, TARGETS


@pytest.mark.parametrize("text,old_reject,new_decision", [
    ("形成容量核验记录", True, "candidate"),
    ("现有服务器容量已经足够", True, "reject"),
    ("若客户同意则保证交付", False, "reject"),
])
def test_shadow_comparison_has_no_authority(text, old_reject, new_decision):
    assert _asserts_unresolved_as_confirmed(partial_analysis(), (RequirementDimension.DEPLOYMENT_REQUIREMENT,), text) is old_reject
    assert evaluate(text, TARGETS[2][0]).decision.value == new_decision
