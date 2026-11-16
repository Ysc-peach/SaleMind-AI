"""Prompt builders for the three V2 generation passes.

They live apart from ``solution_prompt_v2`` so the parsing and merge half can be
read without the prompt text, and so the builders can be tested directly. The
parent re-exports every public name to keep the existing imports working.
"""

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
    # The system prompt is built by _semantic_pass_prompt, which applies the
    # contract and the runtime budget itself.
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
