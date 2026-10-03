"""Offline regressions for rubric alignment with production Solution V2."""

from dataclasses import asdict, replace

import pytest

from apps.sales.services.solution_payloads import (
    solution_draft_v2_from_payload,
    solution_draft_v2_to_payload,
)
from apps.sales.services.solution_prompt_v2 import (
    AtomicSolutionProposalSetV2,
    SolutionV2ContainerKind,
    SolutionV2StructureRelation,
    SolutionV2StructureRelationType,
)
from apps.sales.services.solution_schema_v2 import (
    ArchitectureFlowTypeV2,
    assemble_solution_draft_v2,
    build_v2_deterministic_items,
)
from apps.sales.tests.test_solution_quality_v2 import (
    _approved_demo_admission,
    _approved_demo_analysis,
    _approved_demo_proposals,
    evaluate_solution_quality,
)


def _architecture_assembly(
    count,
    *,
    dependency=True,
    request_flow=True,
    data_flow=True,
):
    proposals = _approved_demo_proposals()
    component_kind = SolutionV2ContainerKind.ARCHITECTURE_COMPONENT
    component_keys = tuple(dict.fromkeys(
        proposal.placement.container_key
        for proposal in proposals.proposals
        if proposal.placement.container_kind is component_kind
    ))[:count]
    selected = tuple(
        proposal
        for proposal in proposals.proposals
        if proposal.placement.container_kind is not component_kind
        or proposal.placement.container_key in component_keys
    )
    relations = [
        relation for relation in proposals.structure_relations
        if relation.source_container_kind is not component_kind
        and relation.target_container_kind is not component_kind
    ]
    if len(component_keys) >= 2:
        source, target = component_keys[:2]
        for enabled, relation_type in (
            (dependency, SolutionV2StructureRelationType.COMPONENT_DEPENDENCY),
            (True, SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW),
            (data_flow, SolutionV2StructureRelationType.COMPONENT_DATA_FLOW),
        ):
            if enabled:
                relations.append(SolutionV2StructureRelation(
                    relation_type, component_kind, source, component_kind, target,
                ))
    assembly = assemble_solution_draft_v2(
        build_v2_deterministic_items(
            _approved_demo_analysis(), _approved_demo_admission(),
        ),
        AtomicSolutionProposalSetV2(selected, tuple(relations)),
    )
    # Legacy persisted V2 drafts may omit flows even though current generation
    # requires request flow evidence. Their dependencies must not stand in for it.
    if not request_flow:
        assembly = replace(assembly, draft=replace(
            assembly.draft,
            architecture=replace(
                assembly.draft.architecture,
                flows=tuple(
                    flow for flow in assembly.draft.architecture.flows
                    if flow.flow_type is not ArchitectureFlowTypeV2.REQUEST
                ),
            ),
        ))
    # Evaluate the same authoritative structure that survives persistence.
    persisted_draft = solution_draft_v2_from_payload(
        solution_draft_v2_to_payload(assembly.draft),
    )
    return replace(assembly, draft=persisted_draft)


@pytest.mark.parametrize("component_count", [3, 4])
def test_production_allowed_architecture_can_earn_full_twenty_points(component_count):
    assembly = _architecture_assembly(component_count)

    evaluation = evaluate_solution_quality(assembly)

    assert len(assembly.draft.architecture.components) == component_count
    assert evaluation.section_scores["architecture"] == 20
    assert all(evaluation.hard_gates.values())


@pytest.mark.parametrize("component_count, expected_score", [(0, 3), (1, 7), (2, 8)])
def test_lower_component_quantity_bands_remain_unchanged(component_count, expected_score):
    evaluation = evaluate_solution_quality(_architecture_assembly(
        component_count, dependency=False, request_flow=False, data_flow=False,
    ))

    assert evaluation.section_scores["architecture"] == expected_score


@pytest.mark.parametrize(
    "dependency,request_flow,data_flow,expected_score",
    [
        (False, False, False, 17),
        (True, False, False, 18),
        (False, True, False, 18),
        (False, False, True, 18),
        (True, True, False, 19),
        (True, False, True, 19),
        (False, True, True, 19),
    ],
)
def test_dependency_and_persisted_flows_are_independent_relationship_evidence(
    dependency, request_flow, data_flow, expected_score,
):
    evaluation = evaluate_solution_quality(_architecture_assembly(
        4, dependency=dependency, request_flow=request_flow, data_flow=data_flow,
    ))

    assert evaluation.section_scores["architecture"] == expected_score


def test_quality_result_records_rubric_version_for_score_comparisons():
    evaluation = evaluate_solution_quality(_architecture_assembly(4))

    assert asdict(evaluation).get("rubric_version") == "solution-quality-v2.1"
