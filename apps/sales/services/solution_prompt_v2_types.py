"""V2 solution types: sections, containers, placements and constant tables.

These are pure data definitions shared by the prompt builders and the parser.
Keeping them out of ``solution_prompt_v2`` is what lets those two halves be
split into separate modules without importing each other.
"""

from dataclasses import dataclass
from enum import StrEnum

from apps.sales.services.requirement_analysis import RequirementDimension
from apps.sales.services.solution_generation_contract import LOCAL_REF


class SolutionV2Section(StrEnum):
    PROPOSED_SOLUTION = "proposed_solution"
    ARCHITECTURE = "architecture"
    DEPLOYMENT_AND_INTEGRATION = "deployment_and_integration"
    IMPLEMENTATION_PLAN = "implementation_plan"
    RISKS = "risks"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    MILESTONES = "milestones"
    OUT_OF_SCOPE = "out_of_scope"


class SolutionV2ContainerKind(StrEnum):
    ROOT = "root"
    CAPABILITY_GROUP = "capability_group"
    ARCHITECTURE_COMPONENT = "architecture_component"
    TOPIC_BLOCK = "topic_block"
    IMPLEMENTATION_PHASE = "implementation_phase"
    RISK = "risk"
    ACCEPTANCE_CRITERION = "acceptance_criterion"
    MILESTONE = "milestone"
    SCOPE = "scope"


class SolutionV2PlacementField(StrEnum):
    OVERVIEW = "overview"
    ITEMS = "items"
    IDENTITY = "identity"
    RESPONSIBILITIES = "responsibilities"
    RATIONALE = "rationale"
    INTERFACES = "interfaces"
    OBJECTIVE = "objective"
    TASKS = "tasks"
    DELIVERABLES = "deliverables"
    TIMING = "timing"
    CONDITION = "condition"
    IMPACT = "impact"
    MITIGATION = "mitigation"
    TRIGGER = "trigger"
    CRITERION = "criterion"
    OUTCOME = "outcome"
    SCOPE = "scope"


class SolutionV2StructureRelationType(StrEnum):
    COMPONENT_DEPENDENCY = "component_dependency"
    COMPONENT_REQUEST_FLOW = "component_request_flow"
    COMPONENT_DATA_FLOW = "component_data_flow"
    PHASE_DEPENDENCY = "phase_dependency"
    PHASE_ACCEPTANCE = "phase_acceptance"
    MILESTONE_PHASE = "milestone_phase"


class SolutionV2OutputDiagnosticCategory(StrEnum):
    """Safe evaluation-only categories; never exposed by the runtime API."""

    MALFORMED_JSON = "malformed_json"
    UNKNOWN_KEY = "unknown_key"
    WRONG_VALUE_TYPE = "wrong_value_type"
    PROPOSAL_COUNT_EXCEEDED = "proposal_count_exceeded"
    COMPONENT_COUNT_EXCEEDED = "component_count_exceeded"
    MISSING_COMPONENT_IDENTITY = "missing_component_identity"
    MISSING_COMPONENT_RESPONSIBILITY = "missing_component_responsibility"
    MISSING_COMPONENT_RATIONALE = "missing_component_rationale"
    MISSING_COMPONENT_INTERFACE = "missing_component_interface"
    INVALID_PLACEMENT = "invalid_placement"
    INVALID_RELATION_TYPE = "invalid_relation_type"
    DANGLING_RELATION = "dangling_relation"
    SELF_RELATION = "self_relation"
    DUPLICATE_RELATION = "duplicate_relation"
    DEPENDENCY_CYCLE = "dependency_cycle"
    MISSING_REQUEST_FLOW = "missing_request_flow"
    MALFORMED_REQUIREMENT_LINKAGE = "malformed_requirement_linkage"
    INVALID_CITATION = "invalid_citation"
    IMPLEMENTATION_TOTAL_BUDGET_EXCEEDED = (
        "implementation_total_budget_exceeded"
    )
    ASSURANCE_TOTAL_BUDGET_EXCEEDED = "assurance_total_budget_exceeded"
    IMPLEMENTATION_BUDGET_EXCEEDED = "implementation_budget_exceeded"
    RISK_BUDGET_EXCEEDED = "risk_budget_exceeded"
    ACCEPTANCE_BUDGET_EXCEEDED = "acceptance_budget_exceeded"
    MILESTONE_BUDGET_EXCEEDED = "milestone_budget_exceeded"
    ASSUMPTION_BUDGET_EXCEEDED = "assumption_budget_exceeded"
    OPEN_QUESTION_BUDGET_EXCEEDED = "open_question_budget_exceeded"
    OUT_OF_SCOPE_BUDGET_EXCEEDED = "out_of_scope_budget_exceeded"
    UNCLASSIFIED_CONTRACT_FAILURE = "unclassified_contract_failure"


@dataclass(frozen=True, slots=True)
class SolutionV2Placement:
    section: SolutionV2Section
    container_kind: SolutionV2ContainerKind
    container_key: str | None
    field: SolutionV2PlacementField


@dataclass(frozen=True, slots=True)
class SolutionV2StructureRelation:
    relation_type: SolutionV2StructureRelationType
    source_container_kind: SolutionV2ContainerKind
    source_container_key: str
    target_container_kind: SolutionV2ContainerKind
    target_container_key: str


@dataclass(frozen=True, slots=True)
class AtomicSolutionProposalV2:
    placement: SolutionV2Placement
    text: str
    citations: tuple[str, ...]
    related_requirement_fields: tuple[RequirementDimension, ...] = ()


@dataclass(frozen=True, slots=True)
class AtomicSolutionProposalSetV2:
    proposals: tuple[AtomicSolutionProposalV2, ...]
    structure_relations: tuple[SolutionV2StructureRelation, ...] = ()


_ALLOWED_PLACEMENTS = {
    (SolutionV2Section.PROPOSED_SOLUTION, SolutionV2ContainerKind.ROOT): {
        SolutionV2PlacementField.OVERVIEW,
    },
    (SolutionV2Section.PROPOSED_SOLUTION, SolutionV2ContainerKind.CAPABILITY_GROUP): {
        SolutionV2PlacementField.ITEMS,
    },
    (SolutionV2Section.ARCHITECTURE, SolutionV2ContainerKind.ROOT): {
        SolutionV2PlacementField.OVERVIEW,
    },
    (SolutionV2Section.ARCHITECTURE, SolutionV2ContainerKind.ARCHITECTURE_COMPONENT): {
        SolutionV2PlacementField.IDENTITY,
        SolutionV2PlacementField.RESPONSIBILITIES,
        SolutionV2PlacementField.RATIONALE,
        SolutionV2PlacementField.INTERFACES,
    },
    (SolutionV2Section.DEPLOYMENT_AND_INTEGRATION, SolutionV2ContainerKind.TOPIC_BLOCK): {
        SolutionV2PlacementField.ITEMS,
    },
    (SolutionV2Section.IMPLEMENTATION_PLAN, SolutionV2ContainerKind.IMPLEMENTATION_PHASE): {
        SolutionV2PlacementField.OBJECTIVE,
        SolutionV2PlacementField.TASKS,
        SolutionV2PlacementField.DELIVERABLES,
        SolutionV2PlacementField.TIMING,
    },
    (SolutionV2Section.RISKS, SolutionV2ContainerKind.RISK): {
        SolutionV2PlacementField.CONDITION,
        SolutionV2PlacementField.IMPACT,
        SolutionV2PlacementField.MITIGATION,
        SolutionV2PlacementField.TRIGGER,
    },
    (SolutionV2Section.ACCEPTANCE_CRITERIA, SolutionV2ContainerKind.ACCEPTANCE_CRITERION): {
        SolutionV2PlacementField.CRITERION,
    },
    (SolutionV2Section.MILESTONES, SolutionV2ContainerKind.MILESTONE): {
        SolutionV2PlacementField.OUTCOME,
        SolutionV2PlacementField.TIMING,
    },
    (SolutionV2Section.OUT_OF_SCOPE, SolutionV2ContainerKind.SCOPE): {
        SolutionV2PlacementField.SCOPE,
    },
}

_RELATION_KINDS = {
    SolutionV2StructureRelationType.COMPONENT_DEPENDENCY: (
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
    ),
    SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW: (
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
    ),
    SolutionV2StructureRelationType.COMPONENT_DATA_FLOW: (
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
    ),
    SolutionV2StructureRelationType.PHASE_DEPENDENCY: (
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
    ),
    SolutionV2StructureRelationType.PHASE_ACCEPTANCE: (
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        SolutionV2ContainerKind.ACCEPTANCE_CRITERION,
    ),
    SolutionV2StructureRelationType.MILESTONE_PHASE: (
        SolutionV2ContainerKind.MILESTONE,
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
    ),
}

_CORE_SECTIONS = frozenset({
    SolutionV2Section.PROPOSED_SOLUTION,
    SolutionV2Section.ARCHITECTURE,
    SolutionV2Section.DEPLOYMENT_AND_INTEGRATION,
})
_IMPLEMENTATION_SECTIONS = frozenset({
    SolutionV2Section.IMPLEMENTATION_PLAN,
    SolutionV2Section.MILESTONES,
})
_ASSURANCE_SECTIONS = frozenset({
    SolutionV2Section.RISKS,
    SolutionV2Section.ACCEPTANCE_CRITERIA,
    SolutionV2Section.OUT_OF_SCOPE,
})
_CORE_RELATIONS = frozenset({
    SolutionV2StructureRelationType.COMPONENT_DEPENDENCY,
    SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW,
    SolutionV2StructureRelationType.COMPONENT_DATA_FLOW,
})
_IMPLEMENTATION_RELATIONS = frozenset({
    SolutionV2StructureRelationType.PHASE_DEPENDENCY,
    SolutionV2StructureRelationType.MILESTONE_PHASE,
})
_ASSURANCE_RELATIONS = frozenset({
    SolutionV2StructureRelationType.PHASE_ACCEPTANCE,
})

_CONTAINER_KEY = LOCAL_REF
