"""Closed generation IR for placing verified proposals in Solution Domain V2."""

import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from html import escape
from typing import NoReturn

from apps.knowledge.models import EnterpriseGroundingFactStatus
from apps.knowledge.evidence import format_source
from apps.llm.base import LLMMessage
from apps.sales.services.requirement_analysis import (
    OpportunityRequirementAnalysis,
    RequirementDimension,
    RequirementStatus,
)
from apps.sales.services.solution_admission import GroundingAdmission
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode
from apps.sales.services.solution_readiness import SolutionReadiness
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import SolutionStatementType
from apps.sales.services.solution_prompt_v2_helpers import _invalid
from apps.sales.services.solution_prompt_v2_semantic import _semantic_pass_prompt
from apps.sales.services.solution_prompt_v2_text import _SYSTEM_PROMPT


from apps.sales.services.solution_generation_contract import (
    MAX_ARCHITECTURE_COMPONENTS,
    CORE_PROPOSED_SOLUTION_LIMIT,
    CORE_ARCHITECTURE_OVERVIEW_LIMIT,
    CORE_COMPONENT_FIELD_LIMITS,
    CORE_DEPLOYMENT_TOPIC_LIMITS,
    CORE_CAPABILITY_GROUP_LIMIT,
    CORE_CAPABILITY_GROUP_ITEMS_LIMIT,
    MAX_CORE_PROPOSALS,
    MAX_IMPLEMENTATION_PROPOSALS,
    MAX_ASSURANCE_PROPOSALS,
    MAX_ASSURANCE_RISKS,
    ASSURANCE_RISK_FIELDS,
    MAX_ASSURANCE_ACCEPTANCE,
    MAX_ASSURANCE_OUT_OF_SCOPE,
    MAX_ASSURANCE_PHASE_ACCEPTANCE,
    MAX_SOLUTION_V2_PROPOSALS,
    MAX_IMPLEMENTATION_PHASES,
    IMPLEMENTATION_PHASE_FIELD_LIMITS,
    MAX_IMPLEMENTATION_MILESTONES,
    IMPLEMENTATION_MILESTONE_FIELD_LIMITS,
    IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
    ASSURANCE_SECTION_PROPOSAL_LIMITS,
    LOCAL_REF,
    MANAGED_LINKAGE_PLACEMENTS,
    SEMANTIC_IR_VERSION,
    SEMANTIC_ROOT_KEYS,
    validate_claim_fields,
    validate_citation_allowlist,
    closed_object,
    reject_contract,
)
from apps.sales.services.solution_prompt_v2_types import (
    SolutionV2Section,
    SolutionV2ContainerKind,
    SolutionV2PlacementField,
    SolutionV2StructureRelationType,
    SolutionV2OutputDiagnosticCategory,
    SolutionV2Placement,
    SolutionV2StructureRelation,
    AtomicSolutionProposalV2,
    AtomicSolutionProposalSetV2,
    _ALLOWED_PLACEMENTS,
    _RELATION_KINDS,
    _CORE_SECTIONS,
    _IMPLEMENTATION_SECTIONS,
    _ASSURANCE_SECTIONS,
    _CORE_RELATIONS,
    _IMPLEMENTATION_RELATIONS,
    _ASSURANCE_RELATIONS,
    _CONTAINER_KEY,
)
from apps.sales.services.solution_prompt_v2_passes import (
    build_solution_v2_messages,
    _solution_v2_input_context,
    build_solution_v2_core_messages,
    _clarification_action_style_context,
    build_solution_v2_implementation_messages,
    build_solution_v2_assurance_messages,
    _implementation_budget_options,
    implementation_runtime_proposal_budget,
    assurance_runtime_proposal_budget,
    _section_budget_failure_category,
    implementation_budget_failure_category,
    assurance_budget_failure_category,
    _section_counts,
    _validate_section_budgets,
    _validate_pass_contract,
)

_MAX_LEGACY_SINGLE_PASS_PROPOSALS = 38




def parse_atomic_solution_v2_proposals(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
    _max_proposals: int = _MAX_LEGACY_SINGLE_PASS_PROPOSALS,
    _external_containers: frozenset[tuple[SolutionV2ContainerKind, str]] = frozenset(),
    _proposal_paths: tuple[str, ...] = (),
    _relation_paths: tuple[str, ...] = (),
) -> AtomicSolutionProposalSetV2:
    """Strictly parse the closed V2 proposal-placement IR without repairs."""

    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError):
        reject_contract("malformed_json", "$", "complete unique-key JSON", "malformed JSON")
    closed_object(payload, {"proposals"}, {"structure_relations"})
    items = payload["proposals"]
    if (
        not isinstance(_max_proposals, int)
        or isinstance(_max_proposals, bool)
        or _max_proposals < 0
    ):
        _invalid()
    if not isinstance(items, list):
        reject_contract("wrong_type", "$.proposals", "array", type(items).__name__)
    if len(items) > _max_proposals:
        reject_contract("proposal_count_exceeded", "$.proposals", f"at most {_max_proposals} proposals", str(len(items)))
    validate_citation_allowlist(allowed_source_labels)

    proposals: list[AtomicSolutionProposalV2] = []
    for index, item in enumerate(items):
        path = _proposal_paths[index] if index < len(_proposal_paths) else f"$.proposals[{index}]"
        closed_object(item, {"placement", "text", "citations"}, {"related_requirement_fields"}, path=path)
        placement_data = item["placement"]
        closed_object(placement_data, {"section", "container_kind", "container_key", "field"}, path=path + ".placement")
        try:
            section = SolutionV2Section(placement_data["section"])
            container_kind = SolutionV2ContainerKind(placement_data["container_kind"])
            field = SolutionV2PlacementField(placement_data["field"])
        except (TypeError, ValueError):
            reject_contract("invalid_enum", path + ".placement", "allowed placement enums", "unknown enum or wrong type")
        if field not in _ALLOWED_PLACEMENTS.get((section, container_kind), set()):
            _invalid()
        container_key = placement_data["container_key"]
        if container_kind is SolutionV2ContainerKind.ROOT:
            if container_key is not None:
                _invalid()
        elif not isinstance(container_key, str) or _CONTAINER_KEY.fullmatch(container_key) is None:
            _invalid()
        managed_linkage = (
            (section.value, container_kind.value, field.value)
            in MANAGED_LINKAGE_PLACEMENTS
        )
        claim_text, citations, related_requirement_fields = validate_claim_fields(
            {key: value for key, value in item.items() if key != "placement"},
            allowed_source_labels=allowed_source_labels, path=path,
            require_linkage=managed_linkage,
        )
        if managed_linkage and not related_requirement_fields:
            # Same contract as the Semantic IR parser: an empty linkage would
            # leave the unresolved policy and its guard with nothing to inspect.
            reject_contract(
                "invalid_requirement_link", path + ".related_requirement_fields",
                "at least one RequirementDimension for this placement", "empty",
            )
        proposals.append(AtomicSolutionProposalV2(
            placement=SolutionV2Placement(section, container_kind, container_key, field),
            text=claim_text,
            citations=citations,
            related_requirement_fields=related_requirement_fields,
        ))
    relations_data = payload.get("structure_relations", [])
    if not isinstance(relations_data, list):
        reject_contract("wrong_type", "$.structure_relations", "array", type(relations_data).__name__)
    relations: list[SolutionV2StructureRelation] = []
    for index, item in enumerate(relations_data):
        path = _relation_paths[index] if index < len(_relation_paths) else f"$.structure_relations[{index}]"
        closed_object(item, {
            "relation_type",
            "source_container_kind",
            "source_container_key",
            "target_container_kind",
            "target_container_key",
        }, path=path)
        try:
            relation_type = SolutionV2StructureRelationType(item["relation_type"])
            source_kind = SolutionV2ContainerKind(item["source_container_kind"])
            target_kind = SolutionV2ContainerKind(item["target_container_kind"])
        except (TypeError, ValueError):
            reject_contract("invalid_relation", path, "allowed relation type and endpoint kinds", "unknown enum or wrong type")
        source_key = item["source_container_key"]
        target_key = item["target_container_key"]
        if (
            not isinstance(source_key, str)
            or _CONTAINER_KEY.fullmatch(source_key) is None
            or not isinstance(target_key, str)
            or _CONTAINER_KEY.fullmatch(target_key) is None
        ):
            _invalid()
        expected_kinds = _RELATION_KINDS[relation_type]
        if (source_kind, target_kind) != expected_kinds:
            _invalid()
        relations.append(SolutionV2StructureRelation(
            relation_type=relation_type,
            source_container_kind=source_kind,
            source_container_key=source_key,
            target_container_kind=target_kind,
            target_container_key=target_key,
        ))
    result = AtomicSolutionProposalSetV2(tuple(proposals), tuple(relations))
    validate_solution_v2_structure_relations(
        result,
        max_proposals=_max_proposals,
        external_containers=_external_containers,
        relation_paths=_relation_paths,
    )
    return result


def parse_solution_v2_core_output(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
) -> AtomicSolutionProposalSetV2:
    """Parse one bounded Technical Core response without moving placements."""

    result = _parse_generation_output(
        content, pass_name="core", allowed_source_labels=allowed_source_labels,
        max_proposals=MAX_CORE_PROPOSALS,
    )
    _validate_pass_contract(
        result,
        max_proposals=MAX_CORE_PROPOSALS,
        allowed_sections=_CORE_SECTIONS,
        allowed_relations=_CORE_RELATIONS,
    )
    return result


def parse_solution_v2_implementation_output(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
    max_proposals: int = MAX_IMPLEMENTATION_PROPOSALS,
) -> AtomicSolutionProposalSetV2:
    """Parse one bounded Implementation Planning response without repairs."""

    if (
        not isinstance(max_proposals, int)
        or isinstance(max_proposals, bool)
        or not 0 <= max_proposals <= MAX_IMPLEMENTATION_PROPOSALS
    ):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    result = _parse_generation_output(
        content, pass_name="implementation",
        allowed_source_labels=allowed_source_labels, max_proposals=max_proposals,
    )
    _validate_pass_contract(
        result,
        max_proposals=max_proposals,
        allowed_sections=_IMPLEMENTATION_SECTIONS,
        allowed_relations=_IMPLEMENTATION_RELATIONS,
    )
    _validate_section_budgets(
        result,
        limits=IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
        max_proposals=max_proposals,
    )
    return result


def parse_solution_v2_assurance_output(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
    implementation: AtomicSolutionProposalSetV2,
    max_proposals: int = MAX_ASSURANCE_PROPOSALS,
) -> AtomicSolutionProposalSetV2:
    """Parse Assurance while validating phase references against Pass 2."""

    if (
        not isinstance(max_proposals, int)
        or isinstance(max_proposals, bool)
        or not 0 <= max_proposals <= MAX_ASSURANCE_PROPOSALS
    ):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    _validate_pass_contract(
        implementation,
        max_proposals=MAX_IMPLEMENTATION_PROPOSALS,
        allowed_sections=_IMPLEMENTATION_SECTIONS,
        allowed_relations=_IMPLEMENTATION_RELATIONS,
    )
    phase_containers = frozenset(
        (
            SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
            proposal.placement.container_key,
        )
        for proposal in implementation.proposals
        if proposal.placement.container_kind
        is SolutionV2ContainerKind.IMPLEMENTATION_PHASE
    )
    result = _parse_generation_output(
        content, pass_name="assurance", allowed_source_labels=allowed_source_labels,
        max_proposals=max_proposals, external_containers=phase_containers,
    )
    _validate_pass_contract(
        result,
        max_proposals=max_proposals,
        allowed_sections=_ASSURANCE_SECTIONS,
        allowed_relations=_ASSURANCE_RELATIONS,
    )
    _validate_section_budgets(
        result,
        limits=ASSURANCE_SECTION_PROPOSAL_LIMITS,
        max_proposals=max_proposals,
    )
    return result


def _parse_generation_output(
    content: str, *, pass_name: str, allowed_source_labels: tuple[str, ...],
    max_proposals: int,
    external_containers: frozenset[tuple[SolutionV2ContainerKind, str]] = frozenset(),
) -> AtomicSolutionProposalSetV2:
    """Explicitly distinguish new Semantic IR from the legacy demo envelope."""

    candidate = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", candidate, flags=re.DOTALL)
    if fence is not None:
        candidate = fence.group(1)
    try:
        payload = json.loads(candidate, object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        reject_contract("malformed_json", "$", "complete unique-key JSON", "malformed JSON")
    if isinstance(payload, dict) and ("ir_version" in payload or ("proposals" not in payload and SEMANTIC_ROOT_KEYS & payload.keys())):
        from apps.sales.services.solution_semantic_ir_v2 import (
            convert_semantic_solution_v2_output,
        )

        result = convert_semantic_solution_v2_output(
            candidate, pass_name=pass_name,
            allowed_source_labels=allowed_source_labels, max_proposals=max_proposals,
            external_phases=tuple(
                key for kind, key in external_containers
                if kind is SolutionV2ContainerKind.IMPLEMENTATION_PHASE
            ),
        )
        if pass_name in {"implementation", "assurance"}:
            _validate_section_budgets(
                result, max_proposals=max_proposals,
                limits=(IMPLEMENTATION_SECTION_PROPOSAL_LIMITS if pass_name == "implementation"
                        else ASSURANCE_SECTION_PROPOSAL_LIMITS),
                section_paths={"implementation_plan": "$.phases", "milestones": "$.milestones",
                               "risks": "$.risks", "acceptance_criteria": "$.acceptance",
                               "out_of_scope": "$.out_of_scope"},
            )
        return result
    return parse_atomic_solution_v2_proposals(
        content, allowed_source_labels=allowed_source_labels,
        _max_proposals=max_proposals, _external_containers=external_containers,
    )




def _proposal_sort_key(proposal: AtomicSolutionProposalV2) -> tuple:
    section_priority = {value: index for index, value in enumerate(SolutionV2Section)}
    kind_priority = {
        value: index for index, value in enumerate(SolutionV2ContainerKind)
    }
    field_priority = {
        value: index for index, value in enumerate(SolutionV2PlacementField)
    }
    return (
        section_priority[proposal.placement.section],
        kind_priority[proposal.placement.container_kind],
        proposal.placement.container_key or "",
        field_priority[proposal.placement.field],
        tuple(field.value for field in proposal.related_requirement_fields),
        proposal.text,
        proposal.citations,
    )


def _relation_sort_key(relation: SolutionV2StructureRelation) -> tuple:
    relation_priority = {
        value: index for index, value in enumerate(SolutionV2StructureRelationType)
    }
    kind_priority = {
        value: index for index, value in enumerate(SolutionV2ContainerKind)
    }
    return (
        relation_priority[relation.relation_type],
        kind_priority[relation.source_container_kind],
        relation.source_container_key,
        kind_priority[relation.target_container_kind],
        relation.target_container_key,
    )


def merge_solution_v2_proposal_passes(
    core: AtomicSolutionProposalSetV2,
    implementation: AtomicSolutionProposalSetV2,
    assurance: AtomicSolutionProposalSetV2,
) -> AtomicSolutionProposalSetV2:
    """Combine three validated passes deterministically without new semantics."""

    _validate_pass_contract(
        core,
        max_proposals=MAX_CORE_PROPOSALS,
        allowed_sections=_CORE_SECTIONS,
        allowed_relations=_CORE_RELATIONS,
    )
    _validate_pass_contract(
        implementation,
        max_proposals=MAX_IMPLEMENTATION_PROPOSALS,
        allowed_sections=_IMPLEMENTATION_SECTIONS,
        allowed_relations=_IMPLEMENTATION_RELATIONS,
    )
    implementation_budget = implementation_runtime_proposal_budget(
        len(core.proposals)
    )
    _validate_section_budgets(
        implementation,
        limits=IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
        max_proposals=implementation_budget,
    )
    _validate_pass_contract(
        assurance,
        max_proposals=MAX_ASSURANCE_PROPOSALS,
        allowed_sections=_ASSURANCE_SECTIONS,
        allowed_relations=_ASSURANCE_RELATIONS,
    )
    assurance_budget = assurance_runtime_proposal_budget(
        len(core.proposals), len(implementation.proposals)
    )
    _validate_section_budgets(
        assurance,
        limits=ASSURANCE_SECTION_PROPOSAL_LIMITS,
        max_proposals=assurance_budget,
    )
    merged = AtomicSolutionProposalSetV2(
        proposals=tuple(sorted(
            core.proposals + implementation.proposals + assurance.proposals,
            key=_proposal_sort_key,
        )),
        structure_relations=tuple(sorted(
            core.structure_relations
            + implementation.structure_relations
            + assurance.structure_relations,
            key=_relation_sort_key,
        )),
    )
    if len(merged.proposals) > MAX_SOLUTION_V2_PROPOSALS:
        _invalid()
    validate_solution_v2_structure_relations(
        merged, max_proposals=MAX_SOLUTION_V2_PROPOSALS
    )
    return merged


def diagnose_solution_v2_output(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
) -> SolutionV2OutputDiagnosticCategory | None:
    """Compatibility adapter over the executing parser, never a second validator."""
    try:
        parse_atomic_solution_v2_proposals(content, allowed_source_labels=allowed_source_labels)
    except SolutionDraftError as error:
        failure = getattr(error, "contract_failure", None)
        category = failure.category if failure else "unclassified_contract_failure"
        category = {
            "wrong_type": "wrong_value_type",
            "invalid_requirement_link": "malformed_requirement_linkage",
            "invalid_local_ref": "dangling_relation",
        }.get(category, category)
        return SolutionV2OutputDiagnosticCategory._value2member_map_.get(
            category, SolutionV2OutputDiagnosticCategory.UNCLASSIFIED_CONTRACT_FAILURE,
        )
    return None


def validate_solution_v2_structure_relations(
    value: AtomicSolutionProposalSetV2,
    *,
    max_proposals: int = MAX_SOLUTION_V2_PROPOSALS,
    external_containers: frozenset[
        tuple[SolutionV2ContainerKind, str]
    ] = frozenset(),
    relation_paths: tuple[str, ...] = (),
) -> None:
    """Validate the closed transient relation graph without inferring edges."""

    if not isinstance(value, AtomicSolutionProposalSetV2):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    if (
        not isinstance(value.proposals, tuple)
        or not isinstance(max_proposals, int)
        or isinstance(max_proposals, bool)
        or max_proposals < 0
        or len(value.proposals) > max_proposals
        or not isinstance(value.structure_relations, tuple)
        or not isinstance(external_containers, frozenset)
    ):
        _invalid()
    for external in external_containers:
        if (
            not isinstance(external, tuple)
            or len(external) != 2
            or not isinstance(external[0], SolutionV2ContainerKind)
            or not isinstance(external[1], str)
            or _CONTAINER_KEY.fullmatch(external[1]) is None
        ):
            _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    containers = {
        (proposal.placement.container_kind, proposal.placement.container_key)
        for proposal in value.proposals
        if proposal.placement.container_key is not None
    }
    containers.update(external_containers)
    architecture_components = {
        proposal.placement.container_key
        for proposal in value.proposals
        if proposal.placement.container_kind
        is SolutionV2ContainerKind.ARCHITECTURE_COMPONENT
    }
    if len(architecture_components) > MAX_ARCHITECTURE_COMPONENTS:
        reject_contract("component_count_exceeded", "$.architecture.components",
                        f"at most {MAX_ARCHITECTURE_COMPONENTS} components", str(len(architecture_components)))
    component_field_counts = {
        key: {
            SolutionV2PlacementField.IDENTITY: 0,
            SolutionV2PlacementField.RESPONSIBILITIES: 0,
            SolutionV2PlacementField.RATIONALE: 0,
            SolutionV2PlacementField.INTERFACES: 0,
        }
        for key in architecture_components
    }
    for proposal in value.proposals:
        if proposal.placement.container_kind is SolutionV2ContainerKind.ARCHITECTURE_COMPONENT:
            component_field_counts[proposal.placement.container_key][
                proposal.placement.field
            ] += 1
    for key, counts in sorted(component_field_counts.items()):
        for field, category in (
            (SolutionV2PlacementField.IDENTITY, "missing_component_identity"),
            (SolutionV2PlacementField.RESPONSIBILITIES, "missing_component_responsibility"),
            (SolutionV2PlacementField.RATIONALE, "missing_component_rationale"),
            (SolutionV2PlacementField.INTERFACES, "missing_component_interface"),
        ):
            if counts[field] < 1 or (field is SolutionV2PlacementField.IDENTITY and counts[field] != 1):
                reject_contract(category, "$.architecture.components", "complete component fields", str(counts[field]))
    seen = set()
    dependency_edges = {
        SolutionV2StructureRelationType.COMPONENT_DEPENDENCY: [],
        SolutionV2StructureRelationType.PHASE_DEPENDENCY: [],
    }
    request_flow_count = 0
    for index, relation in enumerate(value.structure_relations):
        path = relation_paths[index] if index < len(relation_paths) else f"$.structure_relations[{index}]"
        if not isinstance(relation, SolutionV2StructureRelation):
            _invalid()
        expected_kinds = _RELATION_KINDS.get(relation.relation_type)
        if expected_kinds != (
            relation.source_container_kind,
            relation.target_container_kind,
        ):
            _invalid()
        signature = (
            relation.relation_type,
            relation.source_container_kind,
            relation.source_container_key,
            relation.target_container_kind,
            relation.target_container_key,
        )
        if signature in seen:
            reject_contract("duplicate_identifier", path, "unique relation", "duplicate edge")
        seen.add(signature)
        if (
            (relation.source_container_kind, relation.source_container_key)
            not in containers
            or (relation.target_container_kind, relation.target_container_key)
            not in containers
        ):
            reject_contract("invalid_local_ref", path, "existing relation endpoints", "dangling endpoint")
        if relation.relation_type in dependency_edges:
            if relation.source_container_key == relation.target_container_key:
                reject_contract("invalid_relation", path, "distinct dependency endpoints", "self-loop")
            dependency_edges[relation.relation_type].append(
                (relation.source_container_key, relation.target_container_key)
            )
        elif relation.relation_type in {
            SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW,
            SolutionV2StructureRelationType.COMPONENT_DATA_FLOW,
        }:
            if relation.source_container_key == relation.target_container_key:
                reject_contract("invalid_relation", path, "distinct flow endpoints", "self-loop")
            if relation.relation_type is SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW:
                request_flow_count += 1
    if len(architecture_components) >= 2 and request_flow_count == 0:
        reject_contract("invalid_relation", "$.architecture.request_flows", "at least one request flow for multiple components", "0 flows")
    for edges in dependency_edges.values():
        _reject_dependency_cycle(edges)


def _reject_dependency_cycle(edges: list[tuple[str, str]]) -> None:
    dependencies: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for source, target in edges:
        nodes.update((source, target))
        dependencies.setdefault(source, set()).add(target)
    resolved: set[str] = set()
    remaining = set(nodes)
    while remaining:
        ready = {
            node for node in remaining if dependencies.get(node, set()) <= resolved
        }
        if not ready:
            reject_contract("invalid_relation", "$", "acyclic dependency graph", "dependency cycle")
        resolved.update(ready)
        remaining -= ready


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid()
    return value.strip()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError("Nonstandard JSON constant.")


