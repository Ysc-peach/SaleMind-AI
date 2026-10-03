"""Real parser rejection evidence and malformed-input containment, offline."""

import json

import pytest

from apps.llm.base import LLMGeneration
from apps.sales.services.real_provider_benchmark import (
    EvaluationPassFailure,
    diagnose_generation_pass,
)
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services.solution_prompt_v2 import (
    parse_solution_v2_assurance_output,
    parse_solution_v2_core_output,
    parse_solution_v2_implementation_output,
)
from apps.sales.tests.test_solution_semantic_ir_v2 import (
    assurance_ir, core_ir, implementation_ir,
)


def parser_and_payload(pass_name):
    if pass_name == "core":
        return core_ir(), lambda text: parse_solution_v2_core_output(
            text, allowed_source_labels=("S1",),
        )
    if pass_name == "implementation":
        return implementation_ir(), lambda text: parse_solution_v2_implementation_output(
            text, allowed_source_labels=("S1",),
        )
    implementation = parse_solution_v2_implementation_output(
        json.dumps(implementation_ir()), allowed_source_labels=("S1",),
    )
    return assurance_ir(), lambda text: parse_solution_v2_assurance_output(
        text, allowed_source_labels=("S1",), implementation=implementation,
    )


@pytest.mark.parametrize("pass_name", ("core", "implementation", "assurance"))
@pytest.mark.parametrize("mutation, category, path", (
    (lambda p: p.update({"unexpected": True}), "unknown_key", "$.unexpected"),
    (lambda p: p.pop("ir_version"), "missing_required_key", "$.ir_version"),
    (lambda p: p.update({"ir_version": "wrong"}), "invalid_enum", "$.ir_version"),
))
def test_all_passes_expose_the_actual_formal_rejection(pass_name, mutation, category, path):
    payload, parse = parser_and_payload(pass_name)
    mutation(payload)
    with pytest.raises(SolutionDraftError) as caught:
        parse(json.dumps(payload))
    evidence = caught.value.contract_failure
    assert evidence.category == category
    assert evidence.json_path == path
    assert evidence.expected
    assert evidence.actual
    assert "unexpected" not in str(caught.value)  # External contract stays data-free.


@pytest.mark.parametrize("pass_name, root, container_field, path", (
    ("core", "proposed_solution", None, "$.proposed_solution[0]"),
    ("implementation", "phases", "tasks", "$.phases[0].tasks[0]"),
    ("assurance", "risks", "mitigation", "$.risks[0].mitigation[0]"),
))
@pytest.mark.parametrize("field, invalid", (
    ("citations", [{}]), ("citations", [[]]), ("citations", [1]),
    ("citations", None), ("related_requirement_fields", [{}]),
    ("related_requirement_fields", [[]]), ("text", {}),
))
def test_bad_claim_types_are_contract_errors_not_python_exceptions(
    pass_name, root, container_field, path, field, invalid,
):
    payload, parse = parser_and_payload(pass_name)
    claim = payload[root][0] if container_field is None else payload[root][0][container_field][0]
    claim[field] = invalid
    with pytest.raises(SolutionDraftError) as caught:
        parse(json.dumps(payload))
    evidence = caught.value.contract_failure
    assert evidence.category in {"invalid_citation", "invalid_requirement_link", "wrong_type"}
    assert evidence.json_path == path + "." + field


@pytest.mark.parametrize("pass_name", ("core", "implementation", "assurance"))
def test_diagnostic_adapter_consumes_parser_evidence_without_reclassification(pass_name):
    payload, parse = parser_and_payload(pass_name)
    payload["unexpected"] = {"private": "DO_NOT_LOG"}
    with pytest.raises(EvaluationPassFailure) as caught:
        diagnose_generation_pass(
            pass_name=pass_name,
            generate=lambda: LLMGeneration(json.dumps(payload)), parse=parse,
            allowed_source_labels=("S1",), max_proposals=46,
        )
    evidence = caught.value.diagnostic
    assert (evidence.category, evidence.json_path) == ("unknown_key", "$.unexpected")
    assert evidence.expected == "allowed key"
    assert evidence.actual == "unknown key"
    assert "DO_NOT_LOG" not in repr(evidence)


def test_adapter_does_not_guess_a_category_when_parser_provides_none():
    def reject(_text):
        from apps.sales.services.solution_errors import SolutionDraftErrorCode
        raise SolutionDraftError(SolutionDraftErrorCode.INVALID_RESPONSE)

    with pytest.raises(EvaluationPassFailure) as caught:
        diagnose_generation_pass(
            pass_name="implementation", generate=lambda: LLMGeneration('{"unexpected":true}'),
            parse=reject, allowed_source_labels=("S1",), max_proposals=18,
        )
    assert caught.value.diagnostic.category == "unknown_contract_failure"


def test_section_budget_rejection_preserves_the_real_count_and_path():
    from apps.sales.tests.test_solution_split_generation_v2 import _implementation_payload
    with pytest.raises(SolutionDraftError) as caught:
        parse_solution_v2_implementation_output(
            json.dumps(_implementation_payload(implementation=17)), allowed_source_labels=("S1",),
        )
    evidence = caught.value.contract_failure
    assert evidence.category == "implementation_budget_exceeded"
    assert evidence.json_path == "$.proposals[16]"
    assert evidence.expected == "at most 16 implementation_plan claims"
    assert evidence.actual == "17 claims"


@pytest.mark.parametrize("labels", (None, ["S1"], ({},), ("S1", "S1")))
def test_semantic_ir_invalid_citation_allowlist_is_invalid_input(labels):
    with pytest.raises(SolutionDraftError) as caught:
        parse_solution_v2_core_output(json.dumps(core_ir()), allowed_source_labels=labels)
    assert caught.value.code == "invalid_solution_draft_input"


@pytest.mark.parametrize("pass_name", ("core", "implementation", "assurance"))
def test_non_utf8_claim_text_is_rejected_by_the_formal_contract(pass_name):
    payload, parse = parser_and_payload(pass_name)
    if pass_name == "core":
        claim = payload["proposed_solution"][0]
    elif pass_name == "implementation":
        claim = payload["phases"][0]["tasks"][0]
    else:
        claim = payload["out_of_scope"][0]
    claim["text"] = "unpaired surrogate: " + chr(0xD800)
    with pytest.raises(SolutionDraftError) as caught:
        parse(json.dumps(payload))
    assert caught.value.contract_failure.category == "wrong_type"
    assert caught.value.contract_failure.json_path.endswith(".text")
