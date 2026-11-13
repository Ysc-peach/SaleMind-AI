"""Managed placements must declare at least one requirement dimension.

An empty ``related_requirement_fields`` made the unresolved policy return
``None`` and the unresolved-as-confirmed guard return ``False``, so the model
could disable both deterministic checks by emitting an empty array. The contract
layer now rejects that shape before any policy or guard runs.
"""

import json

import pytest

from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services.solution_generation_contract import MANAGED_LINKAGE_PLACEMENTS
from apps.sales.services.solution_prompt_v2 import (
    parse_solution_v2_assurance_output,
    parse_solution_v2_core_output,
    parse_solution_v2_implementation_output,
)
from apps.sales.services.solution_unresolved_policy import _TARGETS


def claim(text, related=("business_goal",)):
    return {
        "text": text,
        "citations": ["S1"],
        "related_requirement_fields": list(related),
    }


def core_payload():
    return {
        "ir_version": "semantic_v1",
        "proposed_solution": [claim("Use a knowledge service.")],
        "capability_groups": [],
        "architecture": {
            "overview": [],
            "components": [{
                "ref": "entry",
                "identity": claim("Business entry"),
                "responsibilities": [claim("Entry handles requests.")],
                "rationale": [claim("Entry isolates its boundary.")],
                "interfaces": [claim("Entry exposes a controlled interface.")],
            }],
            "dependencies": [],
            "request_flows": [],
            "data_flows": [],
        },
        "deployment_and_integration": {"deployment": [claim("Place the service in the network.")]},
    }


def implementation_payload():
    return {
        "ir_version": "semantic_v1",
        "phases": [{
            "ref": "build",
            "objective": [claim("Confirm interfaces.")],
            "tasks": [claim("Inspect available interfaces.")],
            "deliverables": [claim("Interface inventory.")],
            "timing": [claim("In the first week.")],
        }],
        "milestones": [{
            "ref": "ready",
            "outcome": [claim("Integration ready for validation.")],
            "timing": [claim("Before validation.")],
            "phase_refs": ["build"],
        }],
        "dependencies": [],
    }


def assurance_payload():
    return {
        "ir_version": "semantic_v1",
        "risks": [{
            "ref": "interface_change",
            "condition": [claim("The interface may change.")],
            "impact": [claim("The adapter may need revision.")],
            "mitigation": [claim("Validate the contract before build.")],
            "trigger": [claim("A contract change is detected.")],
        }],
        "acceptance": [{"ref": "integration_test", "criterion": [claim("Complete integration test.")]}],
        "out_of_scope": [claim("Do not replace the customer identity system.")],
        "phase_acceptance": [{"from": "build", "to": "integration_test"}],
    }


def _parse_implementation(payload):
    return parse_solution_v2_implementation_output(
        json.dumps(payload), allowed_source_labels=("S1",),
    )


def _parse(pass_name, payload):
    if pass_name == "core":
        return parse_solution_v2_core_output(json.dumps(payload), allowed_source_labels=("S1",))
    if pass_name == "implementation":
        return _parse_implementation(payload)
    implementation = _parse_implementation(implementation_payload())
    return parse_solution_v2_assurance_output(
        json.dumps(payload), allowed_source_labels=("S1",), implementation=implementation,
    )


def _payload(pass_name):
    return {
        "core": core_payload,
        "implementation": implementation_payload,
        "assurance": assurance_payload,
    }[pass_name]()


def _claim_at(payload, location):
    """Return the claim dict at an alternating key/index location tuple."""
    node = payload
    for part in location:
        node = node[part]
    return node


MANAGED_CASES = [
    ("implementation", ("phases", 0, "objective", 0), "$.phases[0].objective[0]"),
    ("implementation", ("phases", 0, "tasks", 0), "$.phases[0].tasks[0]"),
    ("implementation", ("phases", 0, "deliverables", 0), "$.phases[0].deliverables[0]"),
    ("implementation", ("phases", 0, "timing", 0), "$.phases[0].timing[0]"),
    ("implementation", ("milestones", 0, "outcome", 0), "$.milestones[0].outcome[0]"),
    ("assurance", ("risks", 0, "condition", 0), "$.risks[0].condition[0]"),
    ("assurance", ("risks", 0, "impact", 0), "$.risks[0].impact[0]"),
    ("assurance", ("risks", 0, "mitigation", 0), "$.risks[0].mitigation[0]"),
]


def test_managed_placements_match_the_unresolved_policy_targets():
    assert MANAGED_LINKAGE_PLACEMENTS == frozenset(_TARGETS)


@pytest.mark.parametrize("pass_name,location,json_path", MANAGED_CASES)
def test_managed_placement_rejects_empty_linkage(pass_name, location, json_path):
    payload = _payload(pass_name)
    _claim_at(payload, location)["related_requirement_fields"] = []

    with pytest.raises(SolutionDraftError) as caught:
        _parse(pass_name, payload)

    evidence = caught.value.contract_failure
    assert evidence.category == "invalid_requirement_link"
    assert evidence.json_path == json_path + ".related_requirement_fields"
    assert evidence.actual == "empty"


@pytest.mark.parametrize("pass_name,location,json_path", MANAGED_CASES)
def test_managed_placement_accepts_a_single_requirement_dimension(pass_name, location, json_path):
    payload = _payload(pass_name)
    _claim_at(payload, location)["related_requirement_fields"] = ["business_goal"]

    result = _parse(pass_name, payload)

    assert result.proposals


@pytest.mark.parametrize("location,json_path", [
    (("proposed_solution", 0), "$.proposed_solution[0]"),
    (("architecture", "components", 0, "identity"), "$.architecture.components[0].identity"),
])
def test_unmanaged_core_placement_still_allows_empty_linkage(location, json_path):
    payload = core_payload()
    _claim_at(payload, location)["related_requirement_fields"] = []

    result = parse_solution_v2_core_output(json.dumps(payload), allowed_source_labels=("S1",))

    assert result.proposals


def test_unmanaged_assurance_placement_still_allows_empty_linkage():
    payload = assurance_payload()
    payload["acceptance"][0]["criterion"][0]["related_requirement_fields"] = []
    payload["out_of_scope"][0]["related_requirement_fields"] = []

    implementation = _parse_implementation(implementation_payload())
    result = parse_solution_v2_assurance_output(
        json.dumps(payload), allowed_source_labels=("S1",), implementation=implementation,
    )

    assert result.proposals


def test_all_managed_placements_convert_when_linkage_is_present():
    core = parse_solution_v2_core_output(json.dumps(core_payload()), allowed_source_labels=("S1",))
    implementation = _parse_implementation(implementation_payload())
    assurance = parse_solution_v2_assurance_output(
        json.dumps(assurance_payload()), allowed_source_labels=("S1",),
        implementation=implementation,
    )

    assert core.proposals
    assert len(implementation.proposals) == 6
    assert len(assurance.proposals) == 6


LEGACY_MANAGED_CASES = [
    ("implementation_plan", "implementation_phase", "phase_one", "objective"),
    ("implementation_plan", "implementation_phase", "phase_one", "tasks"),
    ("implementation_plan", "implementation_phase", "phase_one", "deliverables"),
    ("implementation_plan", "implementation_phase", "phase_one", "timing"),
    ("risks", "risk", "interface_change", "condition"),
    ("risks", "risk", "interface_change", "impact"),
    ("risks", "risk", "interface_change", "mitigation"),
    ("milestones", "milestone", "ready", "outcome"),
]


def _legacy_proposal(section, kind, key, field, *, related=("business_goal",)):
    return {
        "placement": {
            "section": section,
            "container_kind": kind,
            "container_key": key,
            "field": field,
        },
        "text": "Confirm the condition before build.",
        "citations": ["S1"],
        "related_requirement_fields": list(related),
    }


def _parse_legacy(proposal):
    from apps.sales.services.solution_prompt_v2 import parse_atomic_solution_v2_proposals

    return parse_atomic_solution_v2_proposals(
        json.dumps({"proposals": [proposal], "structure_relations": []}),
        allowed_source_labels=("S1",),
    )


@pytest.mark.parametrize("section,kind,key,field", LEGACY_MANAGED_CASES)
def test_legacy_atomic_parser_rejects_empty_managed_linkage(section, kind, key, field):
    with pytest.raises(SolutionDraftError) as caught:
        _parse_legacy(_legacy_proposal(section, kind, key, field, related=()))

    evidence = caught.value.contract_failure
    assert evidence.category == "invalid_requirement_link"
    assert evidence.json_path == "$.proposals[0].related_requirement_fields"
    assert evidence.actual == "empty"


@pytest.mark.parametrize("section,kind,key,field", LEGACY_MANAGED_CASES)
def test_legacy_atomic_parser_rejects_missing_managed_linkage(section, kind, key, field):
    proposal = _legacy_proposal(section, kind, key, field)
    del proposal["related_requirement_fields"]

    with pytest.raises(SolutionDraftError) as caught:
        _parse_legacy(proposal)

    assert caught.value.contract_failure.category == "missing_required_key"


def test_legacy_atomic_parser_keeps_unmanaged_linkage_optional():
    proposal = _legacy_proposal(
        "proposed_solution", "root", None, "overview", related=(),
    )
    del proposal["related_requirement_fields"]

    assert _parse_legacy(proposal).proposals
