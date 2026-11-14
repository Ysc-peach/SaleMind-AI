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
from apps.sales.services.solution_prompt_v2_text import (
    _ASSURANCE_PASS_CONTRACT,
    _ASSURANCE_PASS_EXAMPLE,
    _CORE_PASS_CONTRACT,
    _CORE_PASS_EXAMPLE,
    _IMPLEMENTATION_PASS_CONTRACT,
    _IMPLEMENTATION_PASS_EXAMPLE,
    _SYSTEM_PROMPT,
)


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

_MAX_LEGACY_SINGLE_PASS_PROPOSALS = 38

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



def build_solution_v2_messages(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
) -> list[LLMMessage]:
    """Build proposal-only V2 messages from program-admitted evidence."""

    if not isinstance(analysis, OpportunityRequirementAnalysis):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    customer = escape(json.dumps(asdict(analysis), ensure_ascii=False), quote=False)
    readiness_data = escape(json.dumps(asdict(readiness), ensure_ascii=False), quote=False)
    admitted_claims = escape(
        json.dumps([asdict(item) for item in admission.claims.claims], ensure_ascii=False),
        quote=False,
    )
    allowed = frozenset(admission.allowed_proposal_source_labels)
    evidence = "\n\n".join(
        format_source(source, source_id=source.label)
        for source in sources
        if source.label in allowed
    )
    return [
        {
            "role": "system",
            "content": _SYSTEM_PROMPT.replace(
                "__REQUIREMENT_DIMENSIONS__",
                ", ".join(item.value for item in RequirementDimension),
            ),
        },
        {"role": "user", "content": (
            f"<customer_requirements>\n{customer}\n</customer_requirements>\n"
            f"<solution_readiness>\n{readiness_data}\n</solution_readiness>\n"
            f"<program_admitted_claims>\n{admitted_claims}\n</program_admitted_claims>\n"
            f"<allowed_enterprise_capabilities>\n{evidence}\n</allowed_enterprise_capabilities>"
        )},
    ]




def _solution_v2_input_context(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
) -> str:
    if not isinstance(analysis, OpportunityRequirementAnalysis):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    customer = escape(json.dumps(asdict(analysis), ensure_ascii=False), quote=False)
    readiness_data = escape(json.dumps(asdict(readiness), ensure_ascii=False), quote=False)
    # Project for generation only: negative facts keep their original admission
    # and durable provenance, but are not offered as positive capability citations.
    # Source membership alone is insufficient: one chunk may support one subject
    # while explicitly denying another.
    # Classify the existing dimensions only. Do not infer confirmed subfacts
    # from an unclear value or mutate the saved analysis/admission authority.
    design_scope = {"confirmed_fields": [], "conditional_fields": {}}
    for dimension in RequirementDimension:
        requirement = getattr(analysis.requirements, dimension.value)
        if requirement.status is RequirementStatus.KNOWN:
            design_scope["confirmed_fields"].append(dimension.value)
        else:
            design_scope["conditional_fields"][dimension.value] = requirement.status.value
    design_scope_json = escape(json.dumps(design_scope, ensure_ascii=False), quote=False)
    supported_subjects = {
        item.subject_key for item in admission.enterprise_decisions
        if item.status == EnterpriseGroundingFactStatus.CONFIRMED_SUPPORTED
    }
    supported_claims = {
        item.claim for item in admission.enterprise_provenance
        if item.subject_key in supported_subjects
    }
    usable, boundaries = [], []
    for item in admission.claims.claims:
        projected = asdict(item)
        if (
            item.statement_type == SolutionStatementType.UNRESOLVED
            or (item.statement_type == SolutionStatementType.ENTERPRISE_FACT
                and item not in supported_claims)
        ):
            projected.pop("citations")
            boundaries.append(projected)
        else:
            usable.append(projected)
    admitted_claims = escape(json.dumps(usable, ensure_ascii=False), quote=False)
    boundary_claims = escape(json.dumps(boundaries, ensure_ascii=False), quote=False)
    allowed = frozenset(admission.allowed_proposal_source_labels)
    evidence = "\n\n".join(
        format_source(source, source_id=source.label)
        for source in sources
        if source.label in allowed
    )
    return (
        f"<customer_requirements>\n{customer}\n</customer_requirements>\n"
        f"<requirement_design_scope>\n{design_scope_json}\n</requirement_design_scope>\n"
        f"<solution_readiness>\n{readiness_data}\n</solution_readiness>\n"
        f"<program_admitted_claims>\n{admitted_claims}\n</program_admitted_claims>\n"
        f"<solution_boundaries>\n{boundary_claims}\n</solution_boundaries>\n"
        "<generation_context_rules>\n"
        "solution_boundaries 保留已确认不支持、冲突和待确认的方案边界；"
        "不得忽略、改写或将其升格为支持，也不得从该块生成 proposal citation。"
        "边界中的企业事实仍保留既有事实状态，不因未展示来源编号而变为未确认。"
        "proposal 只引用 allowed_citation_ids 中的编号，且实际证据必须支持对应判断。"
        "\n</generation_context_rules>\n"
        "<allowed_citation_ids>\n"
        f"{escape(json.dumps(admission.allowed_proposal_source_labels), quote=False)}\n"
        "</allowed_citation_ids>\n"
        f"<allowed_enterprise_capabilities>\n{evidence}\n</allowed_enterprise_capabilities>"
    )


def _pass_system_prompt(contract: str, example: str) -> str:
    prompt = _SYSTEM_PROMPT.replace(
            "__REQUIREMENT_DIMENSIONS__",
            ", ".join(item.value for item in RequirementDimension),
        )
    prompt = prompt.replace(
        "顶层恰好只有 proposals、structure_relations；proposals 数量为 0 至 38，绝对不得超过 38，这是最大上限而不是目标数量；只生成完成当前方案真正需要的 proposal。",
        "顶层恰好只有 proposals、structure_relations；只生成完成当前 pass 真正需要的 proposal，并严格遵守下方当前 pass 上限。",
    ).replace(
        "使用 4 个组件时，identity、responsibility、rationale、interface 至少占用 16 条 proposal，其余所有 section 必须共享剩余最多 22 条，不得通过增加低价值 claim 挤占预算。",
        "使用 4 个组件时，identity、responsibility、rationale、interface 至少占用 16 条 proposal，不得通过增加低价值 claim 挤占当前 pass 预算。",
    ).replace(
        "proposal 总数不超过 38；组件不超过 4；",
        "proposal 总数不超过当前 pass 的明确上限；组件不超过 4；",
    )
    example_start = "只返回一个 JSON 对象，不含 Markdown 或解释：\n"
    example_end = "\n顶层恰好只有 proposals、structure_relations；"
    prefix, marker, remainder = prompt.partition(example_start)
    _old_example, suffix_marker, suffix = remainder.partition(example_end)
    if not marker or not suffix_marker:
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    prompt = prefix + example_start + example + example_end + suffix
    return prompt + contract




def build_solution_v2_core_messages(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
) -> list[LLMMessage]:
    """Build the bounded Technical Core generation request."""

    return [
        {
            "role": "system",
            "content": _semantic_pass_prompt(
                "core", MAX_CORE_PROPOSALS,
                allowed_source_labels=admission.allowed_proposal_source_labels,
            ),
        },
        {
            "role": "user",
            "content": _solution_v2_input_context(
                analysis, readiness, sources, admission
            ),
        },
    ]


def _clarification_action_style_context(pass_name: str) -> str:
    """Input-only inquiry style; neither output intent tags nor admission."""
    from .solution_unresolved_policy import unresolved_v2_generation_guidance

    guidance = unresolved_v2_generation_guidance(pass_name)
    if guidance is None:
        return ""
    style = asdict(guidance)
    payload = escape(json.dumps(style, ensure_ascii=False, separators=(",", ":")), quote=False)
    return f"\n<clarification_action_style>{payload}</clarification_action_style>"


def build_solution_v2_implementation_messages(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
    core: AtomicSolutionProposalSetV2,
) -> list[LLMMessage]:
    """Build Implementation Planning from one already validated core."""

    _validate_pass_contract(
        core,
        max_proposals=MAX_CORE_PROPOSALS,
        allowed_sections=_CORE_SECTIONS,
        allowed_relations=_CORE_RELATIONS,
    )
    compact_core = escape(
        json.dumps(asdict(core), ensure_ascii=False, separators=(",", ":")),
        quote=False,
    )
    runtime_budget = implementation_runtime_proposal_budget(len(core.proposals))
    budget_options = json.dumps(_implementation_budget_options(runtime_budget), separators=(",", ":"))
    contract = _IMPLEMENTATION_PASS_CONTRACT.replace(
        "__IMPLEMENTATION_RUNTIME_BUDGET__", str(runtime_budget)
    )
    return [
        {
            "role": "system",
            "content": _semantic_pass_prompt(
                "implementation", runtime_budget,
                allowed_source_labels=admission.allowed_proposal_source_labels,
            ),
        },
        {
            "role": "user",
            "content": (
                _solution_v2_input_context(analysis, readiness, sources, admission)
                + _clarification_action_style_context("implementation")
                + f"\n<validated_technical_core>\n{compact_core}\n"
                "</validated_technical_core>"
                + f"\n<implementation_budget_options>{budget_options}</implementation_budget_options>"
            ),
        },
    ]


def build_solution_v2_assurance_messages(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
    core: AtomicSolutionProposalSetV2,
    implementation: AtomicSolutionProposalSetV2,
) -> list[LLMMessage]:
    """Build Assurance & Boundaries from validated earlier passes."""

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
    _validate_section_budgets(
        implementation,
        limits=IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
        max_proposals=implementation_runtime_proposal_budget(len(core.proposals)),
    )
    compact_core = escape(
        json.dumps(asdict(core), ensure_ascii=False, separators=(",", ":")),
        quote=False,
    )
    compact_implementation = escape(
        json.dumps(
            asdict(implementation), ensure_ascii=False, separators=(",", ":")
        ),
        quote=False,
    )
    runtime_budget = assurance_runtime_proposal_budget(
        len(core.proposals), len(implementation.proposals)
    )
    contract = _ASSURANCE_PASS_CONTRACT.replace(
        "__ASSURANCE_RUNTIME_BUDGET__", str(runtime_budget)
    )
    return [
        {
            "role": "system",
            "content": _semantic_pass_prompt(
                "assurance", runtime_budget,
                allowed_source_labels=admission.allowed_proposal_source_labels,
            ),
        },
        {
            "role": "user",
            "content": (
                _solution_v2_input_context(analysis, readiness, sources, admission)
                + _clarification_action_style_context("assurance")
                + f"\n<validated_technical_core>\n{compact_core}\n"
                "</validated_technical_core>"
                + f"\n<validated_implementation_plan>\n{compact_implementation}\n"
                "</validated_implementation_plan>"
            ),
        },
    ]


def _implementation_budget_options(runtime_budget: int) -> list[dict[str, int]]:
    """Compute feasible shape allowances without changing the formal contract.

    The model chooses the business plan; these program-owned numbers only
    remove arithmetic over total, section and per-container limits.
    """
    options = []
    phase_field_maximum = sum(IMPLEMENTATION_PHASE_FIELD_LIMITS[field][1]
                              for field in ("tasks", "timing"))
    for phases in range(1, MAX_IMPLEMENTATION_PHASES + 1):
        phase_base = phases * (IMPLEMENTATION_PHASE_FIELD_LIMITS["objective"][0]
                               + IMPLEMENTATION_PHASE_FIELD_LIMITS["deliverables"][0])
        for milestones in range(MAX_IMPLEMENTATION_MILESTONES + 1):
            milestone_base = milestones * IMPLEMENTATION_MILESTONE_FIELD_LIMITS["outcome"][0]
            remaining = runtime_budget - phase_base - milestone_base
            if remaining < phases * IMPLEMENTATION_PHASE_FIELD_LIMITS["tasks"][0]:
                continue
            phase_work = min(phases * phase_field_maximum,
                             IMPLEMENTATION_SECTION_PROPOSAL_LIMITS["implementation_plan"] - phase_base,
                             remaining)
            milestone_timing = min(milestones * IMPLEMENTATION_MILESTONE_FIELD_LIMITS["timing"][1],
                                   IMPLEMENTATION_SECTION_PROPOSAL_LIMITS["milestones"] - milestone_base)
            options.append({
                "phase_count": phases, "milestone_count": milestones,
                "shared_work_maximum": min(remaining, phase_work + milestone_timing),
                "phase_work_maximum": phase_work,
                "milestone_timing_maximum": milestone_timing,
            })
    return options


def implementation_runtime_proposal_budget(core_proposal_count: int) -> int:
    """Return the bounded Implementation allowance left by Technical Core."""

    if (
        not isinstance(core_proposal_count, int)
        or isinstance(core_proposal_count, bool)
        or not 0 <= core_proposal_count <= MAX_CORE_PROPOSALS
    ):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    return min(
        MAX_IMPLEMENTATION_PROPOSALS,
        MAX_SOLUTION_V2_PROPOSALS - core_proposal_count,
    )


def assurance_runtime_proposal_budget(
    core_proposal_count: int,
    implementation_proposal_count: int,
) -> int:
    """Return the bounded Assurance allowance left by both earlier passes."""

    if (
        not isinstance(core_proposal_count, int)
        or isinstance(core_proposal_count, bool)
        or not 0 <= core_proposal_count <= MAX_CORE_PROPOSALS
        or not isinstance(implementation_proposal_count, int)
        or isinstance(implementation_proposal_count, bool)
        or not 0 <= implementation_proposal_count <= MAX_IMPLEMENTATION_PROPOSALS
    ):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    return min(
        MAX_ASSURANCE_PROPOSALS,
        MAX_SOLUTION_V2_PROPOSALS
        - core_proposal_count
        - implementation_proposal_count,
    )


_SECTION_BUDGET_CATEGORIES = {
    "implementation_plan": (
        SolutionV2OutputDiagnosticCategory.IMPLEMENTATION_BUDGET_EXCEEDED
    ),
    "risks": SolutionV2OutputDiagnosticCategory.RISK_BUDGET_EXCEEDED,
    "acceptance_criteria": (
        SolutionV2OutputDiagnosticCategory.ACCEPTANCE_BUDGET_EXCEEDED
    ),
    "milestones": SolutionV2OutputDiagnosticCategory.MILESTONE_BUDGET_EXCEEDED,
    "assumptions": SolutionV2OutputDiagnosticCategory.ASSUMPTION_BUDGET_EXCEEDED,
    "open_questions": (
        SolutionV2OutputDiagnosticCategory.OPEN_QUESTION_BUDGET_EXCEEDED
    ),
    "out_of_scope": (
        SolutionV2OutputDiagnosticCategory.OUT_OF_SCOPE_BUDGET_EXCEEDED
    ),
}


def _section_budget_failure_category(
    section_counts: dict[str, int],
    *,
    limits: dict[str, int],
    max_proposals: int,
    maximum_ceiling: int,
    total_category: SolutionV2OutputDiagnosticCategory,
) -> SolutionV2OutputDiagnosticCategory | None:
    """Classify bounded pass counts without exposing proposal content."""

    if (
        not isinstance(section_counts, dict)
        or set(section_counts) - set(limits)
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in section_counts.values()
        )
        or not isinstance(max_proposals, int)
        or isinstance(max_proposals, bool)
        or not 0 <= max_proposals <= maximum_ceiling
    ):
        return SolutionV2OutputDiagnosticCategory.WRONG_VALUE_TYPE
    for section, maximum in limits.items():
        if section_counts.get(section, 0) > maximum:
            return _SECTION_BUDGET_CATEGORIES[section]
    if sum(section_counts.values()) > max_proposals:
        return total_category
    return None


def implementation_budget_failure_category(
    section_counts: dict[str, int],
    *,
    max_proposals: int,
) -> SolutionV2OutputDiagnosticCategory | None:
    return _section_budget_failure_category(
        section_counts,
        limits=IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
        max_proposals=max_proposals,
        maximum_ceiling=MAX_IMPLEMENTATION_PROPOSALS,
        total_category=(
            SolutionV2OutputDiagnosticCategory.IMPLEMENTATION_TOTAL_BUDGET_EXCEEDED
        ),
    )


def assurance_budget_failure_category(
    section_counts: dict[str, int],
    *,
    max_proposals: int,
) -> SolutionV2OutputDiagnosticCategory | None:
    return _section_budget_failure_category(
        section_counts,
        limits=ASSURANCE_SECTION_PROPOSAL_LIMITS,
        max_proposals=max_proposals,
        maximum_ceiling=MAX_ASSURANCE_PROPOSALS,
        total_category=(
            SolutionV2OutputDiagnosticCategory.ASSURANCE_TOTAL_BUDGET_EXCEEDED
        ),
    )


def _section_counts(
    value: AtomicSolutionProposalSetV2,
    *,
    limits: dict[str, int],
) -> dict[str, int]:
    counts = {section: 0 for section in limits}
    for proposal in value.proposals:
        counts[proposal.placement.section.value] += 1
    return counts


def _validate_section_budgets(
    value: AtomicSolutionProposalSetV2,
    *,
    limits: dict[str, int],
    max_proposals: int,
    section_paths: dict[str, str] | None = None,
) -> None:
    maximum_ceiling = (
        MAX_IMPLEMENTATION_PROPOSALS
        if limits is IMPLEMENTATION_SECTION_PROPOSAL_LIMITS
        else MAX_ASSURANCE_PROPOSALS
    )
    total_category = (
        SolutionV2OutputDiagnosticCategory.IMPLEMENTATION_TOTAL_BUDGET_EXCEEDED
        if limits is IMPLEMENTATION_SECTION_PROPOSAL_LIMITS
        else SolutionV2OutputDiagnosticCategory.ASSURANCE_TOTAL_BUDGET_EXCEEDED
    )
    counts = _section_counts(value, limits=limits)
    category = _section_budget_failure_category(
        counts,
        limits=limits,
        max_proposals=max_proposals,
        maximum_ceiling=maximum_ceiling,
        total_category=total_category,
    )
    if category is not None:
        for section, maximum in limits.items():
            if counts[section] > maximum:
                indices = [index for index, proposal in enumerate(value.proposals)
                           if proposal.placement.section.value == section]
                index = indices[maximum]
                path = (section_paths or {}).get(section, f"$.proposals[{index}]")
                reject_contract(category.value, path, f"at most {maximum} {section} claims", f"{counts[section]} claims")
        reject_contract(category.value, "$.proposals", f"at most {max_proposals} proposals", str(sum(counts.values())))


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


def _validate_pass_contract(
    value: AtomicSolutionProposalSetV2,
    *,
    max_proposals: int,
    allowed_sections: frozenset[SolutionV2Section],
    allowed_relations: frozenset[SolutionV2StructureRelationType],
) -> None:
    if not isinstance(value, AtomicSolutionProposalSetV2):
        reject_contract("wrong_type", "$", "AtomicSolutionProposalSetV2", type(value).__name__)
    if len(value.proposals) > max_proposals:
        reject_contract("proposal_count_exceeded", "$.proposals", f"at most {max_proposals} proposals", str(len(value.proposals)))
    for index, proposal in enumerate(value.proposals):
        if proposal.placement.section not in allowed_sections:
            reject_contract("invalid_placement", f"$.proposals[{index}].placement.section",
                            "current pass allowed section", proposal.placement.section.value)
    for index, relation in enumerate(value.structure_relations):
        if relation.relation_type not in allowed_relations:
            reject_contract("invalid_relation", f"$.structure_relations[{index}].relation_type",
                            "current pass allowed relation", relation.relation_type.value)


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


