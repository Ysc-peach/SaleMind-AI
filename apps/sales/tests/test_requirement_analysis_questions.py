"""Offline generation/assembly contracts for deterministic sales follow-up."""

import json
from copy import deepcopy
from dataclasses import asdict

import pytest

from apps.sales.models import Customer, Opportunity
from apps.sales.demo_fixtures import DEMO_SCENARIOS, DemoRequirementAnalysisProvider
from apps.sales.services.requirement_analysis import (
    RequirementAnalysisError, _parse_analysis, analyze_opportunity_requirement,
)
from apps.sales.tests.requirement_fakes import AnalysisFakeLLM


DIMENSIONS = (
    "business_goal", "use_scenario", "user_scale", "deployment_requirement",
    "data_security_requirement", "existing_environment", "integration_requirement",
    "timeline", "budget", "technical_constraints",
)


@pytest.fixture(autouse=True)
def no_provider_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Question assembly must not call a real provider.")
    monkeypatch.setattr("socket.socket.connect", blocked)


@pytest.fixture
def facts():
    return {
        "summary": "建设技术资料检索入口。",
        "requirements": {
            name: {"status": "known", "value": "明确的客户要求", "evidence": "客户原文"}
            for name in DIMENSIONS
        },
        "conflicts": [],
    }


def run(facts):
    opportunity = Opportunity(
        customer=Customer(name="企业客户"), project_name="技术资料检索",
        raw_requirement="建设技术资料检索入口。",
    )
    provider = AnalysisFakeLLM(content=json.dumps(facts, ensure_ascii=False))
    result = analyze_opportunity_requirement(opportunity, llm_provider=provider)
    assert len(provider.calls) == 1  # No additional generation for questions.
    return result


def unresolved(facts, name, status):
    facts["requirements"][name] = {
        "status": status,
        "value": "有相关信息，具体边界未明确" if status == "unclear" else None,
        "evidence": None if status == "unknown" else "客户信息尚未明确或存在冲突",
    }
    if status == "conflict":
        facts["conflicts"].append({"fields": [name], "description": "两项客户表述相互矛盾"})


def test_all_known_requirements_create_no_questions(facts):
    assert run(facts).clarifying_questions == ()


@pytest.mark.parametrize("scenario", DEMO_SCENARIOS, ids=lambda scenario: scenario.key)
def test_offline_demo_provider_uses_generation_contract_and_preserves_legacy_fixture(scenario):
    provider = DemoRequirementAnalysisProvider(scenario)
    generation = json.loads(provider.generate_json(()).content)
    assert set(generation) == {"summary", "requirements", "conflicts"}
    result = run(generation)
    assert [q.field.value for q in result.clarifying_questions] == ["timeline", "budget"]
    legacy = _parse_analysis(json.dumps(provider.legacy_snapshot_payload()))
    assert legacy.requirements == result.requirements
    assert legacy.clarifying_questions[0].question == "客户期望何时完成首批业务上线？"


@pytest.mark.parametrize("name", DIMENSIONS)
@pytest.mark.parametrize("status", ("unknown", "unclear", "conflict"))
def test_only_unresolved_dimension_is_asked_without_inventing_facts(facts, name, status):
    unresolved(facts, name, status)
    original = deepcopy(facts)
    result = run(facts)
    assert [q.field.value for q in result.clarifying_questions] == [name]
    assert result.clarifying_questions[0].question.endswith("？")
    assert "请提供更多信息" not in result.clarifying_questions[0].question
    stored = json.loads(json.dumps(asdict(result), ensure_ascii=False))
    assert {k: stored[k] for k in ("summary", "requirements", "conflicts")} == original
    assert _parse_analysis(json.dumps(stored)) == result


def test_questions_prioritize_conflict_then_unclear_with_stable_eight_item_cap(facts):
    for name in DIMENSIONS:
        unresolved(facts, name, "unknown")
    unresolved(facts, "budget", "conflict")
    unresolved(facts, "technical_constraints", "unclear")
    result = run(facts)
    assert [q.field.value for q in result.clarifying_questions] == [
        "budget", "technical_constraints", "business_goal", "use_scenario", "user_scale",
        "deployment_requirement", "data_security_requirement", "existing_environment",
    ]
    assert result.clarifying_questions[0].question.startswith("当前记录中预算信息存在冲突")
    assert result.clarifying_questions[1].question.startswith("技术约束信息尚不明确")
    assert run(facts) == result


@pytest.mark.parametrize("questions", ([], [{"field": "data_security_requirement", "question": "是否有敏感资料？"}]))
def test_provider_supplied_question_field_is_rejected_not_silently_filtered(facts, questions):
    facts["clarifying_questions"] = questions
    with pytest.raises(RequirementAnalysisError) as caught:
        run(facts)
    assert caught.value.contract_failure.category == "unknown_key"


@pytest.mark.parametrize("name", ("deployment_requirement", "data_security_requirement", "technical_constraints"))
def test_confirmed_boundaries_never_generate_repeat_questions(facts, name):
    unresolved(facts, "budget", "unknown")
    result = run(facts)
    assert name not in [q.field.value for q in result.clarifying_questions]


def test_historical_snapshot_questions_are_preserved_and_still_strict(facts):
    unresolved(facts, "budget", "unknown")
    facts["clarifying_questions"] = [{"field": "budget", "question": "一期预算预计何时能够确认？"}]
    result = _parse_analysis(json.dumps(facts))
    assert result.clarifying_questions[0].question == "一期预算预计何时能够确认？"
    facts["clarifying_questions"][0]["field"] = "data_security_requirement"
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(json.dumps(facts))
    assert caught.value.contract_failure.category == "question_targets_known_requirement"


@pytest.mark.parametrize("mutation,category", (
    ("bad_status", "invalid_enum"), ("missing_evidence", "empty_text"),
    ("unknown_with_value", "status_value_mismatch"), ("uncovered_conflict", "conflict_coverage_mismatch"),
))
def test_invalid_facts_are_rejected_before_question_assembly(facts, mutation, category):
    item = facts["requirements"]["business_goal"]
    if mutation == "bad_status":
        item["status"] = "guess"
    elif mutation == "missing_evidence":
        item["evidence"] = ""
    elif mutation == "unknown_with_value":
        item.update(status="unknown", evidence=None)
    else:
        item.update(status="conflict", value=None)
    with pytest.raises(RequirementAnalysisError) as caught:
        run(facts)
    assert caught.value.contract_failure.category == category
