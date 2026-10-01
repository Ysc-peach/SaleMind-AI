"""Generation-only semantic IR lowers into the unchanged V2 proposal contract."""

import json

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.base import LLMProvider
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services.solution_prompt_v2 import (
    AtomicSolutionProposalSetV2,
    parse_solution_v2_assurance_output,
    parse_solution_v2_core_output,
    parse_solution_v2_implementation_output,
    build_solution_v2_core_messages,
    build_solution_v2_implementation_messages,
    build_solution_v2_assurance_messages,
)
from apps.sales.services.solution_readiness import check_solution_readiness
from apps.sales.tests.test_solution_v2_pipeline import analysis_fixture, admission_fixture


def claim(text):
    return {
        "text": text,
        "citations": ["S1"],
        "related_requirement_fields": ["business_goal"],
    }


def core_ir():
    return {
        "ir_version": "semantic_v1",
        "proposed_solution": [claim("Use a knowledge service.")],
        "capability_groups": [],
        "architecture": {
            "overview": [],
            "components": [
                {"ref": ref, "identity": claim(name),
                 "responsibilities": [claim(f"{name} handles requests.")],
                 "rationale": [claim(f"{name} isolates its boundary.")],
                 "interfaces": [claim(f"{name} exposes a controlled interface.")]}
                for ref, name in (("entry", "Business entry"), ("service", "Knowledge service"))
            ],
            "dependencies": [{"from": "entry", "to": "service"}],
            "request_flows": [{"from": "entry", "to": "service"}],
            "data_flows": [{"from": "service", "to": "entry"}],
        },
        "deployment_and_integration": {"deployment": [claim("Place the service in the customer network.")]},
    }


def implementation_ir():
    return {
        "ir_version": "semantic_v1",
        "phases": [
            {"ref": "discovery", "objective": [claim("Confirm interfaces.")],
             "tasks": [claim("Inspect available interfaces.")],
             "deliverables": [claim("Interface inventory.")], "timing": []},
            {"ref": "build", "objective": [claim("Implement the integration.")],
             "tasks": [claim("Build the adapter.")],
             "deliverables": [claim("Working adapter.")], "timing": []},
        ],
        "milestones": [{"ref": "ready", "outcome": [claim("Integration ready for validation.")],
                        "timing": [], "phase_refs": ["build"]}],
        "dependencies": [{"from": "build", "to": "discovery"}],
    }


def _bounded_implementation_ir():
    payload = implementation_ir()
    payload["phases"] = [
        {"ref": f"phase_{n}", "objective": [claim(f"Objective {n}.")],
         "tasks": [claim(f"Task {n}.")],
         "deliverables": [claim(f"Deliverable {n}.")], "timing": []}
        for n in range(4)
    ]
    payload["milestones"] = [
        {"ref": f"milestone_{n}", "outcome": [claim(f"Outcome {n}.")],
         "phase_refs": [f"phase_{n}"], "timing": []}
        for n in range(2)
    ]
    payload["dependencies"] = [
        {"from": f"phase_{n}", "to": f"phase_{n - 1}"}
        for n in range(1, 4)
    ]
    payload["phases"][0]["tasks"].append(claim("Second task 0."))
    payload["phases"][1]["tasks"].append(claim("Second task 1."))
    return payload


def assurance_ir():
    return {
        "ir_version": "semantic_v1",
        "risks": [{"ref": "interface_change", "condition": [claim("The interface may change.")],
                   "impact": [claim("The adapter may need revision.")],
                   "mitigation": [claim("Validate the contract before build.")],
                   "trigger": [claim("A contract change is detected.")]}],
        "acceptance": [{"ref": "integration_test", "criterion": [claim("Complete end-to-end integration test.")]}],
        "out_of_scope": [claim("Do not replace the customer identity system.")],
        "phase_acceptance": [{"from": "build", "to": "integration_test"}],
    }


def parse_core(payload):
    return parse_solution_v2_core_output(json.dumps(payload), allowed_source_labels=("S1",))


def parse_implementation(payload):
    return parse_solution_v2_implementation_output(json.dumps(payload), allowed_source_labels=("S1",))


def parse_assurance(payload, implementation):
    return parse_solution_v2_assurance_output(
        json.dumps(payload), allowed_source_labels=("S1",), implementation=implementation,
    )


def _max_assurance_ir():
    return {
        "ir_version": "semantic_v1",
        "risks": [
            {"ref": f"risk_{n}", **{
                field: [claim(f"Risk {n} {field}.")]
                for field in ("condition", "impact", "mitigation", "trigger")
            }} for n in range(3)
        ],
        "acceptance": [
            {"ref": f"check_{n}", "criterion": [claim(f"Verify outcome {n}.")]}
            for n in range(6)
        ],
        "out_of_scope": [claim(f"Excluded scope {n}.") for n in range(2)],
        "phase_acceptance": [
            {"from": "build", "to": f"check_{n}"} for n in range(6)
        ],
    }


def test_assurance_local_cardinality_maximum_is_twenty_semantic_claims():
    result = parse_assurance(_max_assurance_ir(), parse_implementation(implementation_ir()))
    assert len(result.proposals) == 20
    assert len(result.structure_relations) == 6


def test_assurance_four_risks_rejected_before_section_proposal_budget():
    from apps.sales.services.solution_semantic_ir_v2 import convert_semantic_solution_v2_output

    payload = assurance_ir()
    payload["risks"] = _max_assurance_ir()["risks"] + [{
        "ref": "risk_3", **{field: [claim(f"Risk 3 {field}.")]
                          for field in ("condition", "impact", "mitigation", "trigger")}
    }]
    payload["acceptance"] = []
    payload["phase_acceptance"] = []
    payload["out_of_scope"] = []
    with pytest.raises(SolutionDraftError):
        convert_semantic_solution_v2_output(
            json.dumps(payload), pass_name="assurance", allowed_source_labels=("S1",),
            max_proposals=20, external_phases=("build",),
        )


@pytest.mark.parametrize("field", ("condition", "impact", "mitigation", "trigger"))
@pytest.mark.parametrize("invalid", ("missing", "empty", "two"))
def test_assurance_risk_requires_exactly_one_claim_per_field(field, invalid):
    payload = assurance_ir()
    risk = payload["risks"][0]
    if invalid == "missing":
        del risk[field]
    elif invalid == "empty":
        risk[field] = []
    else:
        risk[field].append(claim(f"Second {field}."))
    with pytest.raises(SolutionDraftError):
        parse_assurance(payload, parse_implementation(implementation_ir()))


def test_assurance_acceptance_limit_and_single_criterion():
    from apps.sales.services.solution_semantic_ir_v2 import convert_semantic_solution_v2_output

    payload = _max_assurance_ir()
    payload["risks"] = []
    payload["out_of_scope"] = []
    assert len(parse_assurance(payload, parse_implementation(implementation_ir())).proposals) == 6
    payload["acceptance"].append({"ref": "check_6", "criterion": [claim("Verify seventh outcome.")]})
    payload["phase_acceptance"] = []
    with pytest.raises(SolutionDraftError):
        convert_semantic_solution_v2_output(
            json.dumps(payload), pass_name="assurance", allowed_source_labels=("S1",),
            max_proposals=20, external_phases=("build",),
        )
    payload["acceptance"].pop()
    for invalid in ([], [claim("First check."), claim("Second check.")]):
        payload["acceptance"][0]["criterion"] = invalid
        with pytest.raises(SolutionDraftError):
            parse_assurance(payload, parse_implementation(implementation_ir()))


def test_assurance_out_of_scope_limit_and_relation_limit_are_independent_of_claim_budget():
    from apps.sales.services.solution_semantic_ir_v2 import convert_semantic_solution_v2_output

    payload = _max_assurance_ir()
    payload["risks"] = []
    payload["acceptance"] = []
    payload["phase_acceptance"] = []
    assert len(parse_assurance(payload, parse_implementation(implementation_ir())).proposals) == 2
    payload["out_of_scope"].append(claim("Excluded scope 2."))
    with pytest.raises(SolutionDraftError):
        convert_semantic_solution_v2_output(
            json.dumps(payload), pass_name="assurance", allowed_source_labels=("S1",),
            max_proposals=20, external_phases=("build",),
        )

    payload = _max_assurance_ir()
    payload["risks"] = []
    payload["out_of_scope"] = []
    payload["phase_acceptance"].append({"from": "discovery", "to": "check_0"})
    with pytest.raises(SolutionDraftError):
        convert_semantic_solution_v2_output(
            json.dumps(payload), pass_name="assurance", allowed_source_labels=("S1",),
            max_proposals=20, external_phases=("build", "discovery"),
        )


def test_assurance_twenty_one_claims_rejected_without_truncation():
    payload = _max_assurance_ir()
    payload["risks"][0]["impact"].append(claim("Extra impact claim."))
    with pytest.raises(SolutionDraftError):
        parse_assurance(payload, parse_implementation(implementation_ir()))


def test_assurance_prompt_declares_same_local_limits_as_parser():
    analysis = analysis_fixture()
    core = parse_core(core_ir())
    implementation = parse_implementation(implementation_ir())
    prompt = build_solution_v2_assurance_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(), core, implementation,
    )[0]["content"]
    for phrase in ("risks 最多 3 个", "每个 risk 的 condition、impact、mitigation、trigger 各恰好 1 条",
                   "acceptance 最多 6 个", "criterion 恰好 1 条", "out_of_scope 最多 2 条",
                   "phase_acceptance 最多 6 条", "phase_acceptance 不计入 proposal 总预算"):
        assert phrase in prompt


def test_core_semantic_ir_lowers_claims_and_typed_relations_without_changing_semantics():
    result = parse_core(core_ir())
    assert isinstance(result, AtomicSolutionProposalSetV2)
    assert {p.placement.field.value for p in result.proposals if p.placement.container_key == "entry"} == {
        "identity", "responsibilities", "rationale", "interfaces",
    }
    assert {(r.relation_type.value, r.source_container_key, r.target_container_key)
            for r in result.structure_relations} == {
        ("component_dependency", "entry", "service"),
        ("component_request_flow", "entry", "service"),
        ("component_data_flow", "service", "entry"),
    }
    assert all(p.citations == ("S1",) and
               tuple(f.value for f in p.related_requirement_fields) == ("business_goal",)
               for p in result.proposals)


def test_implementation_and_assurance_semantic_ir_lower_cross_pass_relations():
    implementation = parse_implementation(implementation_ir())
    assurance = parse_assurance(assurance_ir(), implementation)
    assert {(r.relation_type.value, r.source_container_key, r.target_container_key)
            for r in implementation.structure_relations} == {
        ("phase_dependency", "build", "discovery"),
        ("milestone_phase", "ready", "build"),
    }
    assert [(r.relation_type.value, r.source_container_key, r.target_container_key)
            for r in assurance.structure_relations] == [
        ("phase_acceptance", "build", "integration_test"),
    ]


def test_implementation_four_complete_phases_and_sixteen_claims_are_accepted():
    payload = _bounded_implementation_ir()
    result = parse_implementation(payload)
    assert len(result.proposals) == 16
    assert {item.placement.container_key for item in result.proposals
            if item.placement.section.value == "implementation_plan"} == {
        "phase_0", "phase_1", "phase_2", "phase_3",
    }


@pytest.mark.parametrize("extra_work", ("task", "phase_timing", "milestone_timing"))
def test_implementation_shared_limit_rejects_before_any_atomic_claim_is_added(
    monkeypatch, extra_work,
):
    from apps.sales.services import solution_semantic_ir_v2 as semantic_ir

    payload = _bounded_implementation_ir()
    if extra_work == "task":
        payload["phases"][2]["tasks"].append(claim("Extra task."))
    elif extra_work == "phase_timing":
        payload["phases"][0]["timing"] = [claim("Confirmed phase timing.")]
    else:
        payload["milestones"][0]["timing"] = [claim("Confirmed milestone timing.")]

    added_claims = []
    original_claim = semantic_ir._claim

    def record_claim(value):
        added_claims.append(value)
        return original_claim(value)

    monkeypatch.setattr(semantic_ir, "_claim", record_claim)
    with pytest.raises(SolutionDraftError) as caught:
        parse_implementation(payload)
    assert added_claims == []
    assert caught.value.category == "implementation_shared_work_cardinality"
    assert caught.value.actual_count == 7
    assert caught.value.maximum_count == 6
    assert caught.value.code == "solution_draft_invalid_response"


def test_implementation_two_milestone_outcomes_and_two_timings_fit_section_and_total():
    payload = _bounded_implementation_ir()
    for phase in payload["phases"][:2]:
        phase["tasks"].pop()
    for milestone in payload["milestones"]:
        milestone["timing"] = [claim(f"Confirmed timing for {milestone['ref']}.")]

    result = parse_implementation(payload)
    milestone_claims = [item for item in result.proposals
                        if item.placement.section.value == "milestones"]
    assert len(result.proposals) == 16
    assert len(milestone_claims) == 4
    assert [item.placement.field for item in milestone_claims].count("outcome") == 2
    assert [item.placement.field for item in milestone_claims].count("timing") == 2


def test_implementation_five_complete_phases_are_rejected_at_local_boundary():
    from apps.sales.services.solution_semantic_ir_v2 import convert_semantic_solution_v2_output

    payload = _bounded_implementation_ir()
    payload["phases"] = payload["phases"][:4]
    for phase in payload["phases"][:2]:
        phase["tasks"].pop()
    payload["phases"].append({
        "ref": "phase_4", "objective": [claim("Objective 4.")],
        "tasks": [claim("Task 4.")],
        "deliverables": [claim("Deliverable 4.")], "timing": [],
    })
    payload["milestones"] = []
    # Thirteen claims fit the 16-claim converter budget; the phase limit is decisive.
    with pytest.raises(SolutionDraftError):
        convert_semantic_solution_v2_output(
            json.dumps(payload), pass_name="implementation",
            allowed_source_labels=("S1",), max_proposals=16,
        )


@pytest.mark.parametrize(("field", "size"), (
    ("objective", 0), ("objective", 2),
    ("tasks", 0), ("tasks", 3),
    ("deliverables", 0), ("deliverables", 2),
    ("timing", 2),
))
def test_implementation_phase_field_cardinality_fails_closed(field, size):
    payload = implementation_ir()
    payload["phases"][0][field] = [claim(f"{field} {n}.") for n in range(size)]
    with pytest.raises(SolutionDraftError):
        parse_implementation(payload)


def test_implementation_six_tasks_and_timing_claims_are_accepted_seven_rejected():
    payload = _bounded_implementation_ir()
    payload["phases"][0]["tasks"].pop()
    payload["phases"][1]["tasks"].pop()
    payload["phases"][0]["timing"] = [claim("Confirmed phase timing.")]
    payload["phases"][1]["timing"] = [claim("Confirmed second phase timing.")]
    assert len(parse_implementation(payload).proposals) == 16

    payload = _bounded_implementation_ir()
    payload["phases"] = payload["phases"][:3]
    payload["phases"][2]["tasks"].append(claim("Second task 2."))
    payload["phases"][0]["timing"] = [claim("Confirmed phase timing.")]
    payload["dependencies"] = payload["dependencies"][:2]
    # Three objectives, three deliverables, seven task/timing claims and two
    # milestones make only 15 claims: the shared local limit must reject it.
    assert 3 + 3 + 7 + 2 == 15
    with pytest.raises(SolutionDraftError):
        parse_implementation(payload)


def test_implementation_milestone_timing_counts_against_shared_six():
    payload = _bounded_implementation_ir()
    payload["phases"] = payload["phases"][:3]
    payload["phases"][1]["tasks"].pop()
    payload["phases"][2]["tasks"].append(claim("Second task 2."))
    payload["dependencies"] = payload["dependencies"][:2]
    payload["milestones"] = payload["milestones"][:1]
    payload["milestones"][0]["timing"] = [claim("Confirmed milestone timing.")]
    assert len(parse_implementation(payload).proposals) == 13
    payload["phases"][0]["timing"] = [claim("Confirmed phase timing.")]
    with pytest.raises(SolutionDraftError):
        parse_implementation(payload)


def test_implementation_milestone_and_outcome_cardinality_fails_closed():
    payload = implementation_ir()
    payload["milestones"].append({
        "ref": "second", "outcome": [claim("Second outcome.")],
        "phase_refs": ["build"],
    })
    assert len(parse_implementation(payload).proposals) == 8
    payload["milestones"].append({
        "ref": "third", "outcome": [claim("Third outcome.")],
        "phase_refs": ["build"],
    })
    with pytest.raises(SolutionDraftError):
        parse_implementation(payload)

    for outcomes in ([], [claim("First outcome."), claim("Second outcome.")]):
        payload = implementation_ir()
        payload["milestones"][0]["outcome"] = outcomes
        with pytest.raises(SolutionDraftError):
            parse_implementation(payload)


def test_implementation_seventeenth_claim_is_rejected_without_truncation():
    payload = _bounded_implementation_ir()
    payload["phases"][2]["tasks"].append(claim("Seventeenth claim."))
    with pytest.raises(SolutionDraftError):
        parse_implementation(payload)


def test_implementation_prompt_states_same_local_cardinality_as_parser():
    analysis = analysis_fixture()
    core = parse_core(core_ir())
    prompt = build_solution_v2_implementation_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(), core,
    )[0]["content"]
    for requirement in (
        "phases 最多 4 个", "每个 phase 的 objective 恰好 1 条",
        "tasks 为 1～2 条", "deliverables 恰好 1 条",
        "tasks 与所有 timing 合计最多 6 条", "milestones 最多 2 个",
        "每个 milestone 的 outcome 恰好 1 条",
    ):
        assert requirement in prompt


@pytest.mark.parametrize("broken", [
    lambda p: p["architecture"]["request_flows"][0].update({"to": "missing"}),
    lambda p: p["architecture"]["components"][0].update({"ref": "service"}),
    lambda p: p["architecture"]["components"][0]["identity"].update({"citations": ["S9"]}),
    lambda p: p["architecture"]["components"][0]["identity"].update({"related_requirement_fields": ["made_up"]}),
])
def test_core_semantic_ir_fails_closed_for_invalid_refs_and_claim_bindings(broken):
    payload = core_ir()
    broken(payload)
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def test_semantic_ir_array_order_does_not_change_local_ref_mapping():
    first = parse_core(core_ir())
    reversed_payload = core_ir()
    reversed_payload["architecture"]["components"].reverse()
    second = parse_core(reversed_payload)
    assert {r for r in first.structure_relations} == {r for r in second.structure_relations}
    assert {p for p in first.proposals} == {p for p in second.proposals}


def test_assurance_semantic_ir_rejects_dangling_phase_reference():
    payload = assurance_ir()
    payload["phase_acceptance"][0]["from"] = "missing_phase"
    with pytest.raises(SolutionDraftError):
        parse_assurance(payload, parse_implementation(implementation_ir()))


def test_semantic_ir_preserves_exact_claim_text_and_rejects_unknown_fields():
    payload = core_ir()
    original = payload["architecture"]["components"][0]["identity"]["text"]
    result = parse_core(payload)
    assert next(p.text for p in result.proposals if p.placement.field.value == "identity" and
                p.placement.container_key == "entry") == original
    payload["architecture"]["components"][0]["identity"]["approval"] = "approved"
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def _max_core_ir():
    payload = core_ir()
    payload["proposed_solution"] = [claim(f"Recommendation {n}.") for n in range(5)]
    payload["capability_groups"] = [
        {"ref": f"basis_{n}", "items": [claim(f"Basis {n}-{i}.") for i in range(2)]}
        for n in range(2)
    ]
    payload["architecture"]["overview"] = [claim(f"Architecture overview {n}.") for n in range(2)]
    payload["architecture"]["components"] = [
        {"ref": f"component_{n}", "identity": claim(f"Component {n}"),
         "responsibilities": [claim(f"Responsibility {n}-{i}.") for i in range(2)],
         "rationale": [claim(f"Rationale {n}.")],
         "interfaces": [claim(f"Interface {n}-{i}.") for i in range(2)]}
        for n in range(4)
    ]
    payload["architecture"]["dependencies"] = []
    payload["architecture"]["request_flows"] = [{"from": "component_0", "to": "component_1"}]
    payload["architecture"]["data_flows"] = []
    payload["deployment_and_integration"] = {
        topic: [claim(f"{topic} {n}.") for n in range(limit)]
        for topic, limit in (("deployment", 4), ("integration", 3),
                             ("data_security", 2), ("environment", 2))
    }
    return payload


def test_semantic_ir_core_all_local_limits_and_46_total_are_accepted():
    payload = _max_core_ir()
    assert len(parse_core(payload).proposals) == 46


@pytest.mark.parametrize(("path", "limit"), (
    (("proposed_solution",), 5),
    (("architecture", "overview"), 2),
    (("deployment_and_integration", "deployment"), 4),
    (("deployment_and_integration", "integration"), 3),
    (("deployment_and_integration", "data_security"), 2),
    (("deployment_and_integration", "environment"), 2),
))
def test_semantic_ir_core_root_and_topic_arrays_reject_limit_plus_one(path, limit):
    payload = core_ir()
    target = payload
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = [claim(f"{path[-1]} {n}.") for n in range(limit)]
    assert parse_core(payload).proposals
    target[path[-1]].append(claim("Extra claim."))
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


@pytest.mark.parametrize(("field", "limit"), (
    ("responsibilities", 2), ("rationale", 1), ("interfaces", 2),
))
def test_semantic_ir_core_component_arrays_reject_limit_plus_one(field, limit):
    payload = core_ir()
    component = payload["architecture"]["components"][0]
    component[field] = [claim(f"{field} {n}.") for n in range(limit)]
    assert parse_core(payload).proposals
    component[field].append(claim("Extra claim."))
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def test_semantic_ir_core_group_and_item_limits_reject_limit_plus_one():
    payload = core_ir()
    groups = payload["capability_groups"] = [
        {"ref": f"basis_{n}", "items": [claim(f"Basis {n}-{i}.") for i in range(2)]}
        for n in range(2)
    ]
    assert parse_core(payload).proposals
    groups[0]["items"].append(claim("Extra group item."))
    with pytest.raises(SolutionDraftError):
        parse_core(payload)
    groups[0]["items"].pop()
    groups.append({"ref": "basis_2", "items": [claim("Extra group.")]})
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def test_semantic_ir_core_four_components_accepted_five_rejected():
    payload = _max_core_ir()
    assert len(parse_core(payload).proposals) == 46
    payload["architecture"]["components"].append({
        "ref": "component_4", "identity": claim("Fifth component"),
        "responsibilities": [claim("Fifth responsibility")],
        "rationale": [claim("Fifth rationale")],
        "interfaces": [claim("Fifth interface")],
    })
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def test_semantic_ir_core_47_claims_rejected_without_cropping():
    payload = _max_core_ir()
    payload["proposed_solution"].append(claim("Forty-seventh distinct claim."))
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def test_evaluation_diagnostic_counts_successful_semantic_ir_claims():
    from apps.sales.services.real_provider_benchmark import diagnose_generation_pass

    payload = json.dumps(core_ir())
    result = diagnose_generation_pass(
        pass_name="core", generate=lambda: LLMGeneration(payload),
        parse=lambda content: parse_solution_v2_core_output(content, allowed_source_labels=("S1",)),
        allowed_source_labels=("S1",), max_proposals=46,
    )
    assert result.diagnostic.proposal_count == len(result.value.proposals) == 10


def test_three_generation_prompts_request_only_semantic_ir_without_legacy_envelope():
    analysis = analysis_fixture()
    readiness = check_solution_readiness(analysis)
    admission = admission_fixture()
    core = parse_core(core_ir())
    implementation = parse_implementation(implementation_ir())
    prompts = (
        build_solution_v2_core_messages(analysis, readiness, (), admission)[0]["content"],
        build_solution_v2_implementation_messages(analysis, readiness, (), admission, core)[0]["content"],
        build_solution_v2_assurance_messages(analysis, readiness, (), admission, core, implementation)[0]["content"],
    )
    for prompt in prompts:
        assert '"ir_version":"semantic_v1"' in prompt
        assert '"related_requirement_fields"' in prompt
        assert '"placement"' not in prompt
        assert '"structure_relations"' not in prompt
        assert '"relation_type"' not in prompt
    assert '"request_flows"' in prompts[0]
    assert '"phases"' in prompts[1]
    assert '"phase_acceptance"' in prompts[2]


def test_core_format_example_keeps_identity_responsibility_rationale_interface_distinct():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]
    example = json.loads(prompt.split("示例仅展示格式，不能照抄示例的技术结论：", 1)[1])
    component = example["architecture"]["components"][0]
    texts = [component["identity"]["text"]] + [
        component[field][0]["text"]
        for field in ("responsibilities", "rationale", "interfaces")
    ]
    assert len(set(texts)) == 4


def test_core_prompt_declares_exact_five_key_component_contract():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]
    example = json.loads(prompt.split("示例仅展示格式，不能照抄示例的技术结论：", 1)[1])
    expected_keys = {"ref", "identity", "responsibilities", "rationale", "interfaces"}

    assert all(set(component) == expected_keys for component in example["architecture"]["components"])
    assert parse_core(example).proposals
    assert "architecture.components 每项必须且只能包含 ref、identity、responsibilities、rationale、interfaces 五个键" in prompt
    assert "identity_note、description、summary、notes、metadata" in prompt
    assert "任何其他额外键" in prompt
    assert "示例中的 architecture.components 即合法五键格式" in prompt


def test_core_prompt_scopes_independent_judgment_rule_to_proposed_solution_items():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]

    assert "proposed_solution.items（包括 capability_groups[].items）" in prompt
    assert "每个 item 必须只表达一个可独立批准/拒绝的技术判断" in prompt
    assert "两个独立能力、技术选择或交付项，必须拆成两个独立 item" in prompt


def test_core_prompt_demonstrates_independent_capability_split_without_conjunction_ban():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]

    assert "BAD：接口服务能力可支撑 JWT 身份认证与 CSV 批量导出。" in prompt
    assert "GOOD：两个独立 item：接口服务能力可支撑 JWT 身份认证。" in prompt
    assert "接口服务能力可支撑 CSV 批量导出。" in prompt
    assert "不禁止所有“和/与”句式" in prompt
    assert "独立成立、独立失败、独立审批" in prompt


def test_core_overview_prompt_requires_independently_reviewable_recommendations():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]

    for requirement in (
        "proposed_solution 数组对应最终 proposed_solution.overview",
        "每条 claim 必须代表一个独立可审核的总体技术推荐",
        "多个独立技术选型", "多个独立系统集成决策",
        "多个可以分别批准/拒绝的能力建设", "拆成多个 overview claim",
    ):
        assert requirement in prompt


def test_core_overview_prompt_demonstrates_separate_oa_and_sso_decisions():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]

    assert "BAD overview：建议通过标准接口对接 OA 门户并接入企业 SSO 统一身份。" in prompt
    assert "GOOD overview claim：建议通过标准接口对接现有 OA 门户。" in prompt
    assert "GOOD overview claim：建议接入企业 SSO 实现统一身份管理。" in prompt


def test_core_overview_prompt_preserves_supporting_description_not_independent_choices():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]

    assert "允许同一推荐的目的、条件或紧密配套描述" in prompt
    assert "允许 overview：建设统一智能服务平台，提升企业知识管理能力。" in prompt
    assert "BAD overview：采用 Kafka、Redis、Kubernetes 完成消息、缓存、高可用部署。" in prompt
    assert "不按动词数量判断，也不禁止所有“和/与”句式" in prompt


def test_core_prompt_declares_every_semantic_ir_local_limit():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]
    for expected in (
        "proposals 最多 46 条", "组件最多 4 个",
        "proposed_solution 最多 5 条", "architecture.overview 最多 2 条",
        "capability_groups 最多 2 组", "每组 items 最多 2 条",
        "responsibilities 为 1～2 条", "rationale 为 1～1 条",
        "interfaces 为 1～2 条", "deployment 最多 4 条",
        "integration 最多 3 条", "data_security 最多 2 条",
        "environment 最多 2 条",
    ):
        assert expected in prompt


def test_core_prompt_canonical_skeleton_matches_formal_parser_at_every_level():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]
    skeleton = json.loads(prompt.split("示例仅展示格式，不能照抄示例的技术结论：", 1)[1])

    assert set(skeleton) == {
        "ir_version", "proposed_solution", "architecture",
        "deployment_and_integration", "capability_groups",
    }
    assert set(skeleton["architecture"]) == {
        "overview", "components", "dependencies", "request_flows", "data_flows",
    }
    assert set(skeleton["architecture"]["components"][0]) == {
        "ref", "identity", "responsibilities", "rationale", "interfaces",
    }
    assert set(skeleton["deployment_and_integration"]) == {
        "deployment", "integration", "data_security", "environment",
    }
    assert len(skeleton["capability_groups"]) == 1
    assert set(skeleton["capability_groups"][0]) == {"ref", "items"}
    assert skeleton["capability_groups"][0]["items"]
    for relation_name in ("dependencies", "request_flows", "data_flows"):
        assert all(set(relation) == {"from", "to"}
                   for relation in skeleton["architecture"][relation_name])
    assert "capability_groups 是 TOP-LEVEL 字段，不属于 architecture" in prompt
    assert "MUST contain only the documented keys" in prompt
    assert "Do not move fields between levels" in prompt
    assert "Do not add sibling or nested keys" in prompt
    assert parse_core(skeleton).proposals


def test_formal_core_parser_rejects_capability_groups_nested_under_architecture():
    payload = core_ir()
    payload["architecture"]["capability_groups"] = [
        {"ref": "knowledge_basis", "items": [claim("Approved knowledge basis.")]},
    ]
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def test_core_component_with_exact_five_keys_is_accepted():
    payload = core_ir()
    assert set(payload["architecture"]["components"][0]) == {
        "ref", "identity", "responsibilities", "rationale", "interfaces",
    }
    assert parse_core(payload).proposals


@pytest.mark.parametrize("extra_key", (
    "identity_note", "description", "summary", "notes", "metadata", "arbitrary_extra",
))
def test_core_component_with_extra_key_is_rejected(extra_key):
    payload = core_ir()
    payload["architecture"]["components"][0][extra_key] = "not allowed"

    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def test_core_prompt_demonstrates_all_three_relation_arrays_with_exact_two_key_edges():
    analysis = analysis_fixture()
    prompt = build_solution_v2_core_messages(
        analysis, check_solution_readiness(analysis), (), admission_fixture(),
    )[0]["content"]
    example = json.loads(prompt.split("示例仅展示格式，不能照抄示例的技术结论：", 1)[1])
    component_refs = {item["ref"] for item in example["architecture"]["components"]}
    for relation_name in ("dependencies", "request_flows", "data_flows"):
        edges = example["architecture"][relation_name]
        assert edges, f"Core prompt lacks a concrete {relation_name} example"
        assert all(set(edge) == {"from", "to"} for edge in edges)
        assert all(edge["from"] in component_refs and edge["to"] in component_refs
                   and edge["from"] != edge["to"] for edge in edges)
    assert parse_core(example).structure_relations
    assert "citations、related_requirement_fields 只属于 claim" in prompt
    assert "relation item 只能有 from、to" in prompt


@pytest.mark.parametrize("relation_name", ("dependencies", "request_flows", "data_flows"))
def test_core_relation_with_only_from_to_is_accepted(relation_name):
    payload = core_ir()
    assert set(payload["architecture"][relation_name][0]) == {"from", "to"}
    assert parse_core(payload).structure_relations


@pytest.mark.parametrize("relation_name", ("dependencies", "request_flows", "data_flows"))
@pytest.mark.parametrize("extra_key", (
    "citations", "related_requirement_fields", "text", "rationale",
    "type", "container_kind", "field", "unexpected",
))
def test_core_relation_rejects_claim_metadata_and_every_other_extra_key(relation_name, extra_key):
    payload = core_ir()
    payload["architecture"][relation_name][0][extra_key] = ["S1"]
    with pytest.raises(SolutionDraftError):
        parse_core(payload)


def test_three_semantic_passes_merge_into_unchanged_solution_v2_payload():
    from apps.sales.services.solution_prompt_v2 import merge_solution_v2_proposal_passes
    from apps.sales.services.solution_schema_v2 import (
        assemble_solution_draft_v2, build_v2_deterministic_items, SolutionDraftV2,
    )
    from apps.sales.services.solution_payloads import (
        solution_draft_v2_to_payload, solution_draft_v2_from_payload,
    )

    core = parse_core(core_ir())
    implementation = parse_implementation(implementation_ir())
    assurance = parse_assurance(assurance_ir(), implementation)
    merged = merge_solution_v2_proposal_passes(core, implementation, assurance)
    assembled = assemble_solution_draft_v2(
        build_v2_deterministic_items(analysis_fixture(), admission_fixture()), merged,
    )
    assert isinstance(assembled.draft, SolutionDraftV2)
    payload = solution_draft_v2_to_payload(assembled.draft)
    assert solution_draft_v2_from_payload(payload) == assembled.draft
    assert len(assembled.draft.architecture.components) == 2
    assert {flow.flow_type.value for flow in assembled.draft.architecture.flows} == {"request", "data"}
    assert assembled.provenance_bindings


@pytest.mark.django_db
def test_semantic_ir_uses_existing_generation_and_verifier_pipeline(monkeypatch):
    from apps.rag.tests.test_answering import search_result
    from apps.sales.services import solution_draft as service
    from apps.sales.tests.solution_fakes import analysis_record
    from apps.sales.tests.test_solution_v2_pipeline import _VerifierProvider

    class SemanticProvider(LLMProvider):
        provider_name = "semantic-ir-fixture"
        model_name = "semantic-ir-fixture"

        def __init__(self):
            self.calls = 0

        def generate(self, messages, *, max_output_tokens=None):
            self.calls += 1
            prompt = messages[0]["content"]
            payload = (core_ir() if "Pass 1" in prompt else
                       implementation_ir() if "Pass 2" in prompt else assurance_ir())
            return LLMGeneration(json.dumps(payload))

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    admission = admission_fixture()
    monkeypatch.setattr(service, "build_solution_admission", lambda *args: admission)
    provider = SemanticProvider()
    verifier = _VerifierProvider()
    result = service.generate_grounded_solution_draft(
        analysis_record(), llm_provider=provider,
        verifier_provider=verifier, schema_version=2,
    )
    assert provider.calls == 3
    assert verifier.calls
    assert result.schema_version == 2
    assert result.draft.architecture.flows
    assert result.v2_provenance_bindings


def test_explicit_legacy_demo_envelope_retains_existing_fenced_json_compatibility():
    from apps.sales.tests.test_solution_split_generation_v2 import _core_payload

    content = "```json\n" + json.dumps(_core_payload()) + "\n```"
    result = parse_solution_v2_core_output(content, allowed_source_labels=("S1",))
    assert len(result.proposals) == 5


@pytest.mark.parametrize("kind", ("phase", "milestone", "risk", "acceptance", "capability_group"))
def test_semantic_ir_never_silently_drops_empty_named_containers(kind):
    if kind == "phase":
        payload = implementation_ir()
        payload["phases"][0].update(objective=[], tasks=[], deliverables=[])
        parse = parse_implementation
    elif kind == "milestone":
        payload = implementation_ir()
        payload["milestones"][0]["outcome"] = []
        parse = parse_implementation
    elif kind == "risk":
        payload = assurance_ir()
        payload["risks"][0].update(condition=[], impact=[], mitigation=[], trigger=[])
        parse = lambda value: parse_assurance(value, parse_implementation(implementation_ir()))
    elif kind == "acceptance":
        payload = assurance_ir()
        payload["acceptance"][0]["criterion"] = []
        parse = lambda value: parse_assurance(value, parse_implementation(implementation_ir()))
    else:
        payload = core_ir()
        payload["capability_groups"] = [{"ref": "basis", "items": []}]
        parse = parse_core
    with pytest.raises(SolutionDraftError):
        parse(payload)
