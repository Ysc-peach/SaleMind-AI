"""Do not equate provider health, safe admission and final solution quality."""

import importlib

import pytest


def report():
    return importlib.import_module("apps.sales.services.solution_evaluation").BenchmarkEvaluationReport()


def passed_generation(value):
    for phase, count in (("core", 30), ("implementation", 18), ("assurance", 20)):
        value.observe("generation_provider", phase=phase, attempt=1, success=True)
        value.observe("generation_parser", phase=phase, attempt=1, success=True, count=count)


def test_complete_json_contract_failure_is_not_provider_unavailability():
    value = report()
    value.observe("generation_provider", phase="core", attempt=1, success=True)
    value.observe("generation_parser", phase="core", attempt=1, success=False, category="unknown_key")
    result = value.to_dict()
    assert result["provider_availability"]["generation"]["status"] == "PASS"
    assert result["generation_contract_validity"]["core"]["status"] == "FAIL"
    assert result["deterministic_admission"]["status"] == "NOT_REACHED"
    assert result["qwen_admission"]["status"] == "NOT_REACHED"
    assert result["persistence"]["solution_persisted"] is False
    assert result["final_solution_quality"]["status"] == "NOT_EVALUATED"


def test_permission_error_is_not_an_inadmissible_verdict():
    value = report()
    passed_generation(value)
    value.observe("deterministic_admission", success=True)
    value.observe("verifier_provider", success=False, category="permission_denied")
    result = value.to_dict()
    assert result["provider_availability"]["verifier"]["status"] == "FAIL"
    assert result["qwen_admission"]["status"] == "BLOCKED_PROVIDER"
    assert result["qwen_admission"]["INADMISSIBLE"] == 0
    assert result["deterministic_admission"]["status"] == "PASS"


def test_generation_provider_failure_counts_attempt_but_not_parser_execution():
    value = report()
    value.observe("generation_provider", phase="core", success=False, category="connection_error")
    result = value.to_dict()
    assert result["generation_contract_validity"]["core"]["attempts"] == 1
    assert result["generation_contract_validity"]["core"]["parser_attempts"] == 0
    assert result["generation_contract_validity"]["core"]["status"] == "BLOCKED_PROVIDER"


def test_real_veto_and_provider_success_are_distinct():
    value = report()
    passed_generation(value)
    value.observe("deterministic_admission", success=True)
    value.observe("verifier_provider", success=True)
    value.observe("verifier_verdict", decision="ADMISSIBLE", atomicity="COMPOUND", veto=True)
    result = value.to_dict()
    assert result["provider_availability"]["verifier"]["status"] == "PASS"
    assert result["qwen_admission"]["status"] == "FAIL"
    assert result["qwen_admission"]["COMPOUND"] == 1
    assert result["persistence"]["status"] == "NOT_REACHED"


def test_persistence_does_not_automatically_establish_quality():
    value = report()
    passed_generation(value)
    value.observe("deterministic_admission", success=True)
    value.observe("verifier_admission", success=True)
    value.observe("persistence", success=True, provenance=True)
    result = value.to_dict()
    assert result["persistence"]["status"] == "PASS"
    assert result["final_solution_quality"]["status"] == "NOT_EVALUATED"
    value.set_quality(score=87, rubric_version="solution-quality-v2.1", hard_gates={"facts": True})
    assert value.to_dict()["final_solution_quality"] == {
        "status": "EVALUATED", "score": 87, "rubric_version": "solution-quality-v2.1",
        "hard_gates": {"facts": True},
    }


def test_quality_cannot_be_assigned_to_a_failed_or_unpersisted_run():
    with pytest.raises(ValueError):
        report().set_quality(score=87, rubric_version="solution-quality-v2.1", hard_gates={})


def test_unknown_events_and_content_are_not_retained():
    value = report()
    value.observe("private_payload", prompt="SECRET", raw_response="SECRET")
    value.observe("generation_provider", phase="core", attempt=1, success=True, prompt="SECRET")
    assert "SECRET" not in str(value.to_dict())


@pytest.mark.parametrize("order", (("veto", "provider"), ("provider", "veto")))
def test_concurrent_provider_error_and_veto_do_not_overwrite_each_other(order):
    value = report()
    for item in order:
        if item == "veto":
            value.observe("verifier_verdict", decision="INADMISSIBLE", atomicity="ATOMIC", veto=True)
        else:
            value.observe("verifier_provider", success=False, category="permission_denied")
    result = value.to_dict()
    assert result["provider_availability"]["verifier"]["status"] == "FAIL"
    assert result["qwen_admission"]["status"] == "FAIL"
    assert result["qwen_admission"]["INADMISSIBLE"] == 1


@pytest.mark.django_db
def test_return_time_provenance_failure_is_not_reported_as_admission_pass(monkeypatch):
    from dataclasses import replace
    from apps.sales.services.solution_evaluation import evaluation_scope
    from apps.sales.services.solution_errors import SolutionDraftError
    from apps.sales.tests.test_solution_v2_pipeline import (
        _generate_v2, _complete_component, _VerifierProvider, admission_fixture,
    )
    original = admission_fixture()
    value = report()
    with evaluation_scope(value), pytest.raises(SolutionDraftError):
        _generate_v2(monkeypatch, _complete_component(
            key="knowledge_service", identity="企业知识服务", responsibility="承担知识查询职责。",
        ), verifier=_VerifierProvider(), admissions=(original, replace(original, allowed_proposal_source_labels=())))
    value.finish_failure()
    result = value.to_dict()
    assert result["deterministic_admission"]["status"] == "FAIL"
    assert result["qwen_admission"]["status"] == "PASS"
    assert result["persistence"]["solution_persisted"] is False


@pytest.mark.django_db
def test_deterministic_only_draft_reports_executed_admission_without_faking_qwen(monkeypatch):
    from apps.sales.services.solution_evaluation import evaluation_scope
    from apps.sales.tests.test_solution_v2_pipeline import _generate_v2, _VerifierProvider
    value = report()
    verifier = _VerifierProvider()
    with evaluation_scope(value):
        _generate_v2(monkeypatch, [], verifier=verifier)
    result = value.to_dict()
    assert result["deterministic_admission"]["status"] == "PASS"
    assert result["qwen_admission"]["status"] == "NOT_REACHED"
    assert not verifier.calls
