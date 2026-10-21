"""In-memory boundary mutations; no production files or decisions are altered."""

import re
from apps.sales.services import solution_clarification_actions as objects
from apps.sales.services.solution_plan_expressions import parse_plan_expression
from apps.sales.tests.test_solution_clarification_generation_guidance import input_style
from apps.sales.tests.test_solution_clarification_action_guard import partial_analysis
from apps.sales.tests.test_solution_requirement_design_scope import messages_for


def test_first_object_only_mutation_is_detected_and_restored(monkeypatch):
    text = "核验本期部署条件与现有SalesMind AI环境的可用服务器容量。"
    assert parse_plan_expression(text)[0].kind.value == "inquiry"
    with monkeypatch.context() as mutant:
        mutant.setattr(objects, "_PLAN_OBJECT_SEQUENCE", re.compile(
            objects._PLAN_ENVIRONMENT_SCOPE + objects._OBJECT + r"(?:[、和与及]" + objects._OBJECT + r")*\Z"))
        old_pattern = objects._ACTION.pattern.replace(
            r"(?:[、和与及]" + objects._QUALIFIED_OBJECT + r")*",
            r"(?:[、和与及]" + objects._OBJECT + r")*",
        )
        mutant.setattr(objects, "_ACTION", re.compile(old_pattern))
        assert parse_plan_expression(text) is None
    assert parse_plan_expression(text)[0].kind.value == "inquiry"


def test_missing_policy_input_guidance_mutation_is_detected(monkeypatch):
    from apps.sales.services import solution_unresolved_policy as policy
    _, original = input_style("implementation", partial_analysis())
    assert len(original["field_examples"]) == 5
    with monkeypatch.context() as mutant:
        mutant.setattr(policy, "unresolved_v2_generation_guidance", lambda phase: None)
        try:
            input_style("implementation", partial_analysis())
        except AssertionError:
            pass
        else:
            raise AssertionError("Guidance removal was not detected")
    _, restored = input_style("implementation", partial_analysis())
    assert len(restored["field_examples"]) == 5


def test_system_prerequisite_guidance_removal_is_detected_and_restored(monkeypatch):
    from apps.sales.services import solution_prompt_v2 as prompt
    required = "核验完成不等于核验通过或条件满足"
    def check():
        for phase in ("implementation", "assurance"):
            assert required in messages_for(phase, partial_analysis())[0]["content"]
    check()
    original = prompt._semantic_pass_prompt
    with monkeypatch.context() as mutant:
        mutant.setattr(prompt, "_semantic_pass_prompt", lambda *args, **kwargs: original(*args, **kwargs).replace(required, ""))
        try:
            check()
        except AssertionError:
            pass
        else:
            raise AssertionError("System prerequisite guidance removal not detected")
    check()
