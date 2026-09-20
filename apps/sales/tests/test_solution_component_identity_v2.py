"""Semantic architecture component identity contracts for newly generated V2 drafts."""

import json
from dataclasses import replace

import pytest

from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.tests.test_solution_v2_pipeline import admission_fixture, analysis_fixture


def _proposal(
    key: str | None,
    field: str,
    text: str,
    *,
    section: str = "architecture",
    kind: str = "architecture_component",
) -> dict:
    return {
        "placement": {
            "section": section,
            "container_kind": kind,
            "container_key": key,
            "field": field,
        },
        "text": text,
        "citations": ["S1"],
        "related_requirement_fields": ["business_goal"],
    }


def _request_flow_relations(count: int) -> list[dict]:
    return [
        {
            "relation_type": "component_request_flow",
            "source_container_kind": "architecture_component",
            "source_container_key": f"component_{index:02d}",
            "target_container_kind": "architecture_component",
            "target_container_key": f"component_{index + 1:02d}",
        }
        for index in range(count - 1)
    ]


def _parse(proposals: list[dict], *, relations: list[dict] | None = None):
    from apps.sales.services.solution_prompt_v2 import (
        parse_atomic_solution_v2_proposals,
    )

    return parse_atomic_solution_v2_proposals(
        json.dumps(
            {
                "proposals": proposals,
                "structure_relations": relations or [],
            },
            ensure_ascii=False,
        ),
        allowed_source_labels=("S1",),
    )


def _component_proposals(count: int) -> list[dict]:
    result = []
    for index in range(count):
        key = f"component_{index:02d}"
        result.extend(
            (
                _proposal(key, "identity", f"业务组件 {index + 1}"),
                _proposal(key, "responsibilities", f"组件 {index + 1} 承担独立业务职责。"),
                _proposal(key, "rationale", f"组件 {index + 1} 用于隔离该业务边界。"),
                _proposal(key, "interfaces", f"组件 {index + 1} 通过受控接口交互。"),
            )
        )
    return result


def test_bounded_component_and_proposal_budgets_accept_the_exact_ceilings():
    from apps.sales.services.solution_prompt_v2 import (
        MAX_ARCHITECTURE_COMPONENTS,
        MAX_SOLUTION_V2_PROPOSALS,
    )

    proposals = _component_proposals(MAX_ARCHITECTURE_COMPONENTS)
    proposals.extend(
        _proposal(
            None,
            "overview",
            f"总体方案建议 {index + 1}。",
            section="proposed_solution",
            kind="root",
        )
        for index in range(MAX_SOLUTION_V2_PROPOSALS - len(proposals))
    )

    parsed = _parse(
        proposals,
        relations=_request_flow_relations(MAX_ARCHITECTURE_COMPONENTS),
    )

    assert MAX_ARCHITECTURE_COMPONENTS == 4
    assert MAX_SOLUTION_V2_PROPOSALS == 38
    assert len(parsed.proposals) == 38


def test_fifth_architecture_component_is_rejected_without_truncation():
    with pytest.raises(SolutionDraftError):
        _parse(_component_proposals(5), relations=_request_flow_relations(5))


def test_thirty_ninth_proposal_is_rejected_without_truncation():
    proposals = _component_proposals(1)
    proposals.extend(
        _proposal(
            None,
            "overview",
            f"总体方案建议 {index + 1}。",
            section="proposed_solution",
            kind="root",
        )
        for index in range(35)
    )

    with pytest.raises(SolutionDraftError):
        _parse(proposals)


def test_new_component_requires_exactly_one_identity_proposal():
    complete = _component_proposals(1)
    missing = [item for item in complete if item["placement"]["field"] != "identity"]
    duplicate = [
        *complete,
        _proposal("component_00", "identity", "知识编排服务"),
    ]

    with pytest.raises(SolutionDraftError):
        _parse(missing)
    with pytest.raises(SolutionDraftError):
        _parse(duplicate)


@pytest.mark.parametrize("missing_field", ["responsibilities", "rationale", "interfaces"])
def test_new_component_requires_complete_architecture_semantics(missing_field):
    proposals = [
        item
        for item in _component_proposals(1)
        if item["placement"]["field"] != missing_field
    ]

    with pytest.raises(SolutionDraftError):
        _parse(proposals)


def test_identity_is_an_atomic_proposal_and_survives_deterministic_assembly():
    from apps.sales.services.solution_schema_v2 import (
        assemble_solution_draft_v2,
        build_v2_deterministic_items,
    )

    proposals = _component_proposals(1)
    proposals[0]["text"] = "知识检索编排服务"
    proposals[1]["text"] = "知识检索编排服务负责组织受控知识查询。"
    parsed = _parse(proposals)
    result = assemble_solution_draft_v2(
        build_v2_deterministic_items(analysis_fixture(), admission_fixture()),
        parsed,
    )
    component = result.draft.architecture.components[0]
    claims = {claim.claim_id: claim for claim in result.draft.claims}

    assert component.identity_claim_id is not None
    assert claims[component.identity_claim_id].text == "知识检索编排服务"
    assert claims[component.identity_claim_id].statement_type.value == "proposal"
    assert any(
        binding.claim_id == component.identity_claim_id
        for binding in result.provenance_bindings
    )


def test_provider_order_does_not_change_identity_mapping():
    from apps.sales.services.solution_schema_v2 import (
        assemble_solution_draft_v2,
        build_v2_deterministic_items,
    )

    proposals = _component_proposals(2)
    deterministic = build_v2_deterministic_items(analysis_fixture(), admission_fixture())

    relations = _request_flow_relations(2)
    first = assemble_solution_draft_v2(
        deterministic,
        _parse(proposals, relations=relations),
    ).draft
    second = assemble_solution_draft_v2(
        deterministic,
        _parse(list(reversed(proposals)), relations=list(reversed(relations))),
    ).draft

    assert first == second


def test_malformed_or_truncated_provider_payload_fails_closed():
    from apps.sales.services.solution_prompt_v2 import (
        parse_atomic_solution_v2_proposals,
    )

    with pytest.raises(SolutionDraftError):
        parse_atomic_solution_v2_proposals(
            '{"proposals":[{"placement":{"section":"architecture"',
            allowed_source_labels=("S1",),
        )


def test_identity_claim_round_trips_while_historical_payload_may_omit_it():
    from apps.sales.services.solution_payloads import (
        solution_draft_v2_from_payload,
        solution_draft_v2_to_payload,
    )
    from apps.sales.tests.test_solution_schema_v2 import valid_draft

    historical = valid_draft()
    historical_payload = solution_draft_v2_to_payload(historical)
    historical_payload["architecture"]["components"][0].pop("identity_claim_id")

    restored_historical = solution_draft_v2_from_payload(historical_payload)
    assert restored_historical.architecture.components[0].identity_claim_id is None

    identity_claim = replace(historical.claims[2], text="企业知识服务")
    component = replace(
        historical.architecture.components[0],
        identity_claim_id=identity_claim.claim_id,
    )
    current = replace(
        historical,
        claims=(historical.claims[:2] + (identity_claim,) + historical.claims[3:]),
        architecture=replace(historical.architecture, components=(component,)),
    )

    restored_current = solution_draft_v2_from_payload(
        solution_draft_v2_to_payload(current)
    )
    assert restored_current == current
    assert restored_current.architecture.components[0].identity_claim_id == "C0003"


def test_identity_reference_must_be_a_proposal_and_names_must_be_unique():
    from apps.sales.services.solution_schema_v2 import (
        ArchitectureComponentV2,
        SolutionAtomicClaimV2,
        SolutionClaimTypeV2,
        validate_solution_draft_v2,
    )
    from apps.sales.tests.test_solution_schema_v2 import valid_draft

    draft = valid_draft()
    wrong_type = replace(
        draft.architecture.components[0], identity_claim_id="C0001"
    )
    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(
            replace(draft, architecture=replace(draft.architecture, components=(wrong_type,)))
        )

    identity_a = replace(draft.claims[2], text="企业应用服务")
    identity_b = SolutionAtomicClaimV2(
        claim_id="C0006",
        statement_type=SolutionClaimTypeV2.PROPOSAL,
        text="企业应用服务",
        citations=("S1",),
        related_requirement_fields=(),
    )
    first = replace(
        draft.architecture.components[0],
        identity_claim_id=identity_a.claim_id,
    )
    second = ArchitectureComponentV2(
        component_id="application_service",
        name="架构组件 2",
        responsibility_claim_ids=(),
        rationale_claim_ids=(),
        dependency_component_ids=(),
        interface_claim_ids=(),
        identity_claim_id=identity_b.claim_id,
    )
    duplicate = replace(
        draft,
        claims=draft.claims[:2] + (identity_a,) + draft.claims[3:] + (identity_b,),
        architecture=replace(draft.architecture, components=(first, second)),
    )

    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(duplicate)
