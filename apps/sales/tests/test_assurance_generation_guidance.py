"""Assurance request guidance must agree with the unchanged closed parser."""

import json

import pytest

from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services.solution_prompt_v2 import build_solution_v2_assurance_messages
from apps.sales.services.solution_readiness import check_solution_readiness
from apps.sales.tests.test_solution_semantic_ir_v2 import (
    assurance_ir,
    core_ir,
    implementation_ir,
    parse_assurance,
    parse_core,
    parse_implementation,
)
from apps.sales.tests.test_solution_v2_pipeline import admission_fixture, analysis_fixture


def assurance_messages():
    analysis = analysis_fixture()
    return build_solution_v2_assurance_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
        parse_core(core_ir()), parse_implementation(implementation_ir()),
    )


@pytest.mark.parametrize("instruction", (
    "acceptance 中每个对象恰好只有 ref、criterion 两个必填键。",
    "criterion 是恰好包含 1 个 claim 对象的数组；每个 claim 恰好只有 "
    "text、citations、related_requirement_fields 三个必填键。",
    "阶段关联只写在顶层 phase_acceptance 数组，每个关系对象恰好只有 from、to 两个必填键。",
))
def test_assurance_request_explicitly_distinguishes_each_closed_object_layer(instruction):
    # The request sent to the provider is the boundary under test, not source text.
    # This checks request guidance, not a probabilistic model's compliance with it.
    messages = assurance_messages()
    assert messages[0]["role"] == "system"
    assert instruction in messages[0]["content"]


def test_assurance_request_example_lowers_nested_claim_and_separate_phase_edge():
    prompt = assurance_messages()[0]["content"]
    payload = json.loads(prompt.split("示例仅展示格式，不能照抄示例的技术结论：", 1)[1])
    acceptance = payload["acceptance"][0]
    assert set(acceptance) == {"ref", "criterion"}
    assert len(acceptance["criterion"]) == 1
    assert set(acceptance["criterion"][0]) == {
        "text", "citations", "related_requirement_fields",
    }
    assert payload["phase_acceptance"] == [{"from": "discovery", "to": "integration_check"}]

    result = parse_assurance(payload, parse_implementation(implementation_ir()))
    criterion = next(p for p in result.proposals if p.placement.field.value == "criterion")
    assert criterion.placement.container_key == "integration_check"
    assert criterion.citations == ("S1",)
    edge = next(r for r in result.structure_relations if r.relation_type.value == "phase_acceptance")
    assert edge.source_container_key == "discovery"
    assert edge.target_container_key == "integration_check"


@pytest.mark.parametrize("extra_key", (
    "phase_ref", "phase_refs", "text", "citations", "related_requirement_fields",
))
def test_acceptance_outer_extra_keys_remain_rejected_without_repair(extra_key):
    payload = assurance_ir()
    payload["acceptance"][0][extra_key] = "not an outer field"
    before = json.dumps(payload, sort_keys=True)
    with pytest.raises(SolutionDraftError) as captured:
        parse_assurance(payload, parse_implementation(implementation_ir()))
    failure = captured.value.contract_failure
    assert failure.category == "unknown_key"
    assert failure.json_path == f"$.acceptance[0].{extra_key}"
    assert set(failure.allowed_keys) == {"ref", "criterion"}
    assert json.dumps(payload, sort_keys=True) == before


@pytest.mark.parametrize("layer,extra_key,path,allowed_keys", (
    ("claim", "phase_ref", "$.acceptance[0].criterion[0].phase_ref",
     {"text", "citations", "related_requirement_fields"}),
    ("edge", "citations", "$.phase_acceptance[0].citations", {"from", "to"}),
))
def test_other_assurance_layers_still_reject_extra_keys(layer, extra_key, path, allowed_keys):
    payload = assurance_ir()
    target = payload["acceptance"][0]["criterion"][0] if layer == "claim" else payload["phase_acceptance"][0]
    target[extra_key] = ["S1"]
    with pytest.raises(SolutionDraftError) as captured:
        parse_assurance(payload, parse_implementation(implementation_ir()))
    failure = captured.value.contract_failure
    assert failure.category == "unknown_key"
    assert failure.json_path == path
    assert set(failure.allowed_keys) == allowed_keys
