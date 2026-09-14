"""Transient structure relations for deterministic Solution V2 assembly."""

from copy import deepcopy
import json

import pytest

from apps.sales.services.requirement_analysis import RequirementDimension
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.tests.test_solution_v2_pipeline import admission_fixture, analysis_fixture


def _proposal(
    section,
    kind,
    key,
    field,
    text,
    *,
    related=(RequirementDimension.BUSINESS_GOAL.value,),
):
    return {
        "placement": {
            "section": section,
            "container_kind": kind,
            "container_key": key,
            "field": field,
        },
        "text": text,
        "citations": ["S1"],
        "related_requirement_fields": list(related),
    }


def _relation(relation_type, source_kind, source_key, target_kind, target_key):
    return {
        "relation_type": relation_type,
        "source_container_kind": source_kind,
        "source_container_key": source_key,
        "target_container_kind": target_kind,
        "target_container_key": target_key,
    }


def _payload():
    proposals = [
        _proposal(
            "architecture",
            "architecture_component",
            "identity_boundary",
            "responsibilities",
            "建议身份边界统一校验访问身份。",
            related=(RequirementDimension.DATA_SECURITY_REQUIREMENT.value,),
        ),
        _proposal(
            "architecture",
            "architecture_component",
            "application_service",
            "responsibilities",
            "建议应用服务编排企业知识查询请求。",
        ),
        _proposal(
            "architecture",
            "architecture_component",
            "application_service",
            "rationale",
            "独立编排边界可隔离业务入口与检索能力。",
        ),
        _proposal(
            "architecture",
            "architecture_component",
            "application_service",
            "interfaces",
            "应用服务在身份校验后接收查询请求。",
        ),
        _proposal(
            "implementation_plan",
            "implementation_phase",
            "discovery",
            "objective",
            "确认需求与接口边界。",
        ),
        _proposal(
            "implementation_plan",
            "implementation_phase",
            "discovery",
            "tasks",
            "核对身份和知识数据接口。",
        ),
        _proposal(
            "implementation_plan",
            "implementation_phase",
            "discovery",
            "deliverables",
            "交付确认后的接口清单。",
        ),
        _proposal(
            "implementation_plan",
            "implementation_phase",
            "build",
            "objective",
            "实现核心查询链路。",
        ),
        _proposal(
            "implementation_plan",
            "implementation_phase",
            "build",
            "tasks",
            "实现身份校验与知识查询编排。",
        ),
        _proposal(
            "implementation_plan",
            "implementation_phase",
            "build",
            "deliverables",
            "交付可验证的核心查询服务。",
        ),
        _proposal(
            "acceptance_criteria",
            "acceptance_criterion",
            "access_control",
            "criterion",
            "未授权用户无法查询受限知识。",
            related=(RequirementDimension.DATA_SECURITY_REQUIREMENT.value,),
        ),
        _proposal(
            "milestones",
            "milestone",
            "core_ready",
            "outcome",
            "核心查询链路完成验证。",
        ),
        _proposal(
            "risks",
            "risk",
            "identity_mismatch",
            "condition",
            "若身份协议与现有认证边界不兼容。",
            related=(RequirementDimension.INTEGRATION_REQUIREMENT.value,),
        ),
        _proposal(
            "risks",
            "risk",
            "identity_mismatch",
            "impact",
            "身份集成路径可能需要额外适配。",
            related=(RequirementDimension.INTEGRATION_REQUIREMENT.value,),
        ),
        _proposal(
            "risks",
            "risk",
            "identity_mismatch",
            "mitigation",
            "在核心实现前完成协议兼容性验证。",
            related=(RequirementDimension.INTEGRATION_REQUIREMENT.value,),
        ),
        _proposal(
            "risks",
            "risk",
            "identity_mismatch",
            "trigger",
            "接口确认发现协议能力不匹配时触发适配评估。",
            related=(RequirementDimension.INTEGRATION_REQUIREMENT.value,),
        ),
    ]
    relations = [
        _relation(
            "component_dependency",
            "architecture_component",
            "application_service",
            "architecture_component",
            "identity_boundary",
        ),
        _relation(
            "phase_dependency",
            "implementation_phase",
            "build",
            "implementation_phase",
            "discovery",
        ),
        _relation(
            "phase_acceptance",
            "implementation_phase",
            "build",
            "acceptance_criterion",
            "access_control",
        ),
        _relation(
            "milestone_phase",
            "milestone",
            "core_ready",
            "implementation_phase",
            "build",
        ),
    ]
    return {"proposals": proposals, "structure_relations": relations}


def _parse(payload):
    from apps.sales.services.solution_prompt_v2 import parse_atomic_solution_v2_proposals

    return parse_atomic_solution_v2_proposals(
        json.dumps(payload, ensure_ascii=False),
        allowed_source_labels=("S1",),
    )


def _assemble(payload):
    from apps.sales.services.solution_schema_v2 import (
        assemble_solution_draft_v2,
        build_v2_deterministic_items,
    )

    deterministic = build_v2_deterministic_items(
        analysis_fixture(), admission_fixture()
    )
    return assemble_solution_draft_v2(deterministic, _parse(payload)).draft


def test_transient_relations_populate_existing_v2_relation_fields():
    draft = _assemble(_payload())

    components = {item.component_id: item for item in draft.architecture.components}
    phases = {item.phase_id: item for item in draft.implementation_plan.phases}
    milestones = {item.milestone_id: item for item in draft.milestones}

    assert components["application_service"].dependency_component_ids == (
        "identity_boundary",
    )
    assert phases["build"].dependency_phase_ids == ("discovery",)
    assert phases["build"].acceptance_criterion_ids == ("access_control",)
    assert milestones["core_ready"].related_phase_ids == ("build",)


def test_structure_relations_and_assembly_are_independent_of_provider_array_order():
    first_payload = _payload()
    reversed_payload = {
        "proposals": list(reversed(first_payload["proposals"])),
        "structure_relations": list(reversed(first_payload["structure_relations"])),
    }

    assert _assemble(first_payload) == _assemble(reversed_payload)


def test_assembly_groups_complete_risk_without_changing_atomic_claim_text():
    payload = _payload()
    draft = _assemble(payload)
    claim_by_id = {claim.claim_id: claim for claim in draft.claims}
    risk = draft.risks[0]

    assert [item.risk_id for item in draft.risks] == ["identity_mismatch"]
    assert claim_by_id[risk.condition_claim_id].text == payload["proposals"][12]["text"]
    assert [claim_by_id[item].text for item in risk.impact_claim_ids] == [
        payload["proposals"][13]["text"]
    ]
    assert [claim_by_id[item].text for item in risk.mitigation_claim_ids] == [
        payload["proposals"][14]["text"]
    ]
    assert [claim_by_id[item].text for item in risk.trigger_claim_ids] == [
        payload["proposals"][15]["text"]
    ]
    proposal_texts = {
        claim.text for claim in draft.claims if claim.statement_type.value == "proposal"
    }
    assert proposal_texts == {item["text"] for item in payload["proposals"]}


def test_requirement_linkage_survives_every_structured_section():
    draft = _assemble(_payload())
    claims = {claim.claim_id: claim for claim in draft.claims}
    architecture_ids = {
        claim_id
        for component in draft.architecture.components
        for claim_id in (
            component.responsibility_claim_ids
            + component.rationale_claim_ids
            + component.interface_claim_ids
        )
    }
    phase_ids = {
        claim_id
        for phase in draft.implementation_plan.phases
        for claim_id in (
            phase.objective_claim_ids + phase.task_claim_ids + phase.deliverable_claim_ids
        )
    }
    risk_ids = {
        claim_id
        for risk in draft.risks
        for claim_id in (
            (risk.condition_claim_id,)
            + risk.impact_claim_ids
            + risk.mitigation_claim_ids
            + risk.trigger_claim_ids
        )
    }

    assert all(claims[item].related_requirement_fields for item in architecture_ids)
    assert all(claims[item].related_requirement_fields for item in phase_ids)
    assert all(claims[item].related_requirement_fields for item in risk_ids)
    assert all(
        claims[item.claim_id].related_requirement_fields
        for item in draft.acceptance_criteria
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda relations: relations.append(deepcopy(relations[0])),
        lambda relations: relations[0].update(target_container_key="application_service"),
        lambda relations: relations[0].update(target_container_key="missing_component"),
        lambda relations: relations[0].update(source_container_kind="implementation_phase"),
        lambda relations: relations[0].update(target_container_kind="implementation_phase"),
        lambda relations: relations[0].update(relation_type="unknown_relation"),
        lambda relations: relations[0].pop("target_container_key"),
        lambda relations: relations[0].update(unexpected="must fail closed"),
    ],
)
def test_structure_relation_parser_rejects_invalid_edges(mutation):
    payload = _payload()
    mutation(payload["structure_relations"])

    with pytest.raises(SolutionDraftError):
        _parse(payload)


@pytest.mark.parametrize("invalid_relations", [None, {}, "relations"])
def test_structure_relation_parser_rejects_invalid_collection_type(invalid_relations):
    payload = _payload()
    payload["structure_relations"] = invalid_relations

    with pytest.raises(SolutionDraftError):
        _parse(payload)


@pytest.mark.parametrize(
    "relation_type,kind,key",
    [
        ("component_dependency", "architecture_component", "application_service"),
        ("phase_dependency", "implementation_phase", "build"),
    ],
)
def test_dependency_cycles_are_rejected(relation_type, kind, key):
    payload = _payload()
    original = next(
        item
        for item in payload["structure_relations"]
        if item["relation_type"] == relation_type
    )
    payload["structure_relations"].append(
        _relation(
            relation_type,
            kind,
            original["target_container_key"],
            kind,
            key,
        )
    )

    with pytest.raises(SolutionDraftError):
        _parse(payload)


def test_old_provider_payload_without_structure_relations_remains_compatible():
    payload = _payload()
    payload.pop("structure_relations")

    parsed = _parse(payload)

    assert parsed.structure_relations == ()
