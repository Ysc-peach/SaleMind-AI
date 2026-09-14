"""Scenario-specific quality contracts for the offline production demo."""

from collections import Counter

import pytest

from apps.sales.demo_fixtures import DEMO_SCENARIOS
from apps.sales.services.requirement_analysis import RequirementDimension
from apps.sales.services.solution_prompt_v2 import SolutionV2StructureRelationType
from apps.sales.tests.test_solution_quality_v2 import (
    _demo_proposals,
    demo_assembly,
)


SCENARIO_KEYS = tuple(item.key for item in DEMO_SCENARIOS)


@pytest.mark.parametrize("scenario_key", SCENARIO_KEYS)
def test_demo_proposals_use_requirement_linkage_across_solution_sections(scenario_key):
    proposal_set = _demo_proposals(scenario_key)
    structured_sections = {
        "architecture",
        "deployment_and_integration",
        "implementation_plan",
        "risks",
        "acceptance_criteria",
    }
    structured = [
        item
        for item in proposal_set.proposals
        if item.placement.section.value in structured_sections
    ]

    assert structured
    assert all(item.related_requirement_fields for item in structured)
    assert {
        field
        for item in structured
        for field in item.related_requirement_fields
    } <= set(RequirementDimension)


@pytest.mark.parametrize("scenario_key", SCENARIO_KEYS)
def test_demo_solutions_persist_meaningful_structure_relations(scenario_key):
    proposal_set = _demo_proposals(scenario_key)
    relation_types = {item.relation_type for item in proposal_set.structure_relations}
    draft = demo_assembly(scenario_key).draft

    assert relation_types == set(SolutionV2StructureRelationType)
    assert any(item.dependency_component_ids for item in draft.architecture.components)
    assert any(item.dependency_phase_ids for item in draft.implementation_plan.phases)
    assert any(item.acceptance_criterion_ids for item in draft.implementation_plan.phases)
    assert all(item.related_phase_ids for item in draft.milestones)


def test_demo_scenarios_are_structurally_and_semantically_distinct():
    architecture_keys = {}
    integration_texts = {}
    risk_texts = {}
    acceptance_texts = {}
    linkage_distributions = {}

    for scenario_key in SCENARIO_KEYS:
        proposal_set = _demo_proposals(scenario_key)
        architecture_keys[scenario_key] = frozenset(
            item.placement.container_key
            for item in proposal_set.proposals
            if item.placement.container_kind.value == "architecture_component"
        )
        integration_texts[scenario_key] = frozenset(
            item.text
            for item in proposal_set.proposals
            if item.placement.section.value == "deployment_and_integration"
        )
        risk_texts[scenario_key] = frozenset(
            item.text
            for item in proposal_set.proposals
            if item.placement.section.value == "risks"
        )
        acceptance_texts[scenario_key] = frozenset(
            item.text
            for item in proposal_set.proposals
            if item.placement.section.value == "acceptance_criteria"
        )
        linkage_distributions[scenario_key] = tuple(sorted(Counter(
            field.value
            for item in proposal_set.proposals
            for field in item.related_requirement_fields
        ).items()))

    for values in (
        architecture_keys,
        integration_texts,
        risk_texts,
        acceptance_texts,
        linkage_distributions,
    ):
        assert len(set(values.values())) == len(SCENARIO_KEYS)


def test_approved_contract_draft_has_controlled_human_review_boundary():
    proposal_texts = {
        item.text
        for item in _demo_proposals("enterprise_service_approved").proposals
    }

    assert any("已审核模板" in text for text in proposal_texts)
    assert any("人工复核" in text for text in proposal_texts)
    assert all(
        "不" in text or "不得" in text
        for text in proposal_texts
        if "最终合同" in text or "自动批准" in text
    )


def test_incomplete_identity_scenario_keeps_protocol_conditional():
    proposal_texts = {
        item.text
        for item in _demo_proposals("manufacturing_identity").proposals
    }

    assert any("如果" in text and "OIDC" in text for text in proposal_texts)
    assert not any("客户使用 OIDC" in text for text in proposal_texts)
