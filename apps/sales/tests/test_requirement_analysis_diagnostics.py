"""Safe metadata emitted by the real analysis parser, with no provider calls."""

import json

import pytest

from apps.sales.services.requirement_analysis import RequirementAnalysisError, _parse_analysis
from apps.sales.tests.requirement_fakes import valid_analysis_payload


@pytest.mark.parametrize("path,replacement,category,json_path,expected,actual", [
    (("summary",), None, "wrong_type", "$.summary", "nonempty string", "null"),
    (("summary",), " ", "empty_text", "$.summary", "nonempty string", "empty string"),
    (("requirements",), [], "wrong_type", "$.requirements", "object", "array"),
    (("requirements", "budget", "status"), "secret-status", "invalid_enum",
     "$.requirements.budget.status", "known|unknown|unclear|conflict", "string"),
    (("requirements", "business_goal", "value"), "private-text", "status_value_mismatch",
     "$.requirements.business_goal.value", "null for unknown status", "string"),
    (("requirements", "business_goal", "evidence"), {}, "status_value_mismatch",
     "$.requirements.business_goal.evidence", "null for unknown status", "object"),
    (("requirements", "budget", "value"), 5, "status_value_mismatch",
     "$.requirements.budget.value", "null for conflict status", "number"),
    (("requirements", "budget", "evidence"), [], "wrong_type",
     "$.requirements.budget.evidence", "nonempty string", "array"),
    (("conflicts",), {}, "wrong_type", "$.conflicts", "array", "object"),
    (("conflicts", 0, "fields"), [], "cardinality", "$.conflicts[0].fields",
     "nonempty array", "array length 0"),
    (("conflicts", 0, "fields"), ["budget", "budget"], "duplicate_identifier",
     "$.conflicts[0].fields", "unique requirement dimensions", "duplicate dimensions"),
    (("conflicts", 0, "fields"), ["business_goal"], "conflict_status_mismatch",
     "$.conflicts[0].fields", "only conflict dimensions", "non-conflict dimension"),
    (("conflicts",), [], "conflict_coverage_mismatch", "$.conflicts",
     "all conflict dimensions referenced", "incomplete conflict coverage"),
    (("clarifying_questions", 0, "field"), ["budget"], "invalid_enum",
     "$.clarifying_questions[0].field", "valid requirement dimension", "array"),
])
def test_formal_parser_identifies_actual_rejection_branch(
    path, replacement, category, json_path, expected, actual,
):
    payload = valid_analysis_payload()
    parent = payload
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = replacement
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(json.dumps(payload))
    failure = caught.value.contract_failure
    assert (failure.category, failure.json_path, failure.expected, failure.actual) == (
        category, json_path, expected, actual,
    )
    assert caught.value.code == "requirement_analysis_invalid_response"
    assert "private-text" not in repr(failure) + str(caught.value)
    assert "secret-status" not in repr(failure) + str(caught.value)


@pytest.mark.parametrize("content,category", [
    ('{"private-customer-text":', "malformed_json"),
    ('{"secret-key":1,"secret-key":2}', "duplicate_key"),
    ('{"secret-key":NaN}', "nonstandard_json"),
])
def test_json_rejection_diagnostics_never_include_raw_keys_or_content(content, category):
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(content)
    failure = caught.value.contract_failure
    assert failure.category == category
    assert failure.json_path == "$"
    assert "secret-key" not in repr(failure) + str(caught.value)
    assert "private-customer-text" not in repr(failure) + str(caught.value)


def test_unknown_key_is_redacted_and_missing_key_is_a_documented_path():
    payload = valid_analysis_payload()
    payload["private-secret-extra-key"] = "private-provider-output"
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(json.dumps(payload))
    failure = caught.value.contract_failure
    assert (failure.category, failure.json_path, failure.actual) == (
        "unknown_key", "$", "unexpected key count 1",
    )
    assert "private" not in repr(failure)
    del payload["private-secret-extra-key"]
    del payload["requirements"]["budget"]
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(json.dumps(payload))
    assert caught.value.contract_failure.category == "missing_required_key"
    assert caught.value.contract_failure.json_path == "$.requirements.budget"


def test_clarification_cardinality_and_known_status_reject_without_repair():
    payload = valid_analysis_payload()
    payload["clarifying_questions"] *= 9
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(json.dumps(payload))
    failure = caught.value.contract_failure
    assert (failure.category, failure.json_path, failure.expected, failure.actual) == (
        "cardinality", "$.clarifying_questions", "array length <=8", "array length 9",
    )
    payload["clarifying_questions"] = [{"field": "business_goal", "question": "private text"}]
    payload["requirements"]["business_goal"] = {
        "status": "known", "value": "known goal", "evidence": "known evidence",
    }
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(json.dumps(payload))
    failure = caught.value.contract_failure
    assert (failure.category, failure.json_path) == (
        "question_targets_known_requirement", "$.clarifying_questions[0].field",
    )


def test_valid_analysis_still_uses_the_same_typed_contract():
    result = _parse_analysis(json.dumps(valid_analysis_payload()))
    assert result.requirements.budget.status == "conflict"
    assert result.requirements.business_goal.status == "unknown"


@pytest.mark.parametrize("dimension", [
    "business_goal", "use_scenario", "user_scale", "deployment_requirement",
    "data_security_requirement", "existing_environment", "integration_requirement",
    "timeline", "budget", "technical_constraints",
])
def test_known_question_diagnostic_identifies_dimension_without_business_text(dimension):
    payload = valid_analysis_payload()
    payload["conflicts"] = []
    for item in payload["requirements"].values():
        item.update(status="unknown", value=None, evidence=None)
    payload["requirements"][dimension] = {
        "status": "known", "value": "private-requirement-value",
        "evidence": "private-requirement-evidence",
    }
    payload["clarifying_questions"] = [{
        "field": dimension, "question": "private-customer-question",
    }]
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(json.dumps(payload))
    failure = caught.value.contract_failure
    assert failure.category == "question_targets_known_requirement"
    assert failure.json_path == "$.clarifying_questions[0].field"
    assert failure.expected == "unknown|unclear|conflict dimension"
    assert failure.actual == (
        f"known dimension: {dimension}; question type: string; question length: 25"
    )
    for secret in ("private-customer-question", "private-requirement-value", "private-requirement-evidence"):
        assert secret not in repr(failure) + str(caught.value)


@pytest.mark.parametrize("question,shape", [
    (None, "null"), (["private-question"], "array"),
    ({"private-key": "private-value"}, "object"), (42, "number"),
])
def test_known_question_diagnostics_preserve_rejection_order_for_nonstring_question(question, shape):
    payload = valid_analysis_payload()
    payload["requirements"]["business_goal"] = {
        "status": "known", "value": "known goal", "evidence": "known evidence",
    }
    payload["clarifying_questions"] = [{"field": "business_goal", "question": question}]
    with pytest.raises(RequirementAnalysisError) as caught:
        _parse_analysis(json.dumps(payload))
    failure = caught.value.contract_failure
    assert failure.category == "question_targets_known_requirement"
    assert failure.actual == (
        f"known dimension: business_goal; question type: {shape}; question length: unavailable"
    )
    assert "private" not in repr(failure)
