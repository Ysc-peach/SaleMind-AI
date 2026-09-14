"""Structured Solution Domain V2 with one authoritative atomic-claim registry."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, NoReturn

from apps.sales.services.requirement_analysis import (
    RequirementDimension,
    RequirementStatus,
)
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode


_FIELD_LABELS = {
    RequirementDimension.BUSINESS_GOAL: "业务目标",
    RequirementDimension.USE_SCENARIO: "使用场景",
    RequirementDimension.USER_SCALE: "使用人数",
    RequirementDimension.DEPLOYMENT_REQUIREMENT: "部署要求",
    RequirementDimension.DATA_SECURITY_REQUIREMENT: "数据安全要求",
    RequirementDimension.EXISTING_ENVIRONMENT: "现有环境",
    RequirementDimension.INTEGRATION_REQUIREMENT: "集成要求",
    RequirementDimension.TIMELINE: "时间要求",
    RequirementDimension.BUDGET: "预算",
    RequirementDimension.TECHNICAL_CONSTRAINTS: "技术约束",
}


class SolutionClaimTypeV2(StrEnum):
    CUSTOMER_FACT = "customer_fact"
    ENTERPRISE_FACT = "enterprise_fact"
    PROPOSAL = "proposal"
    ASSUMPTION = "assumption"
    UNRESOLVED = "unresolved"


class SolutionTopicV2(StrEnum):
    DEPLOYMENT = "deployment"
    INTEGRATION = "integration"
    DATA_SECURITY = "data_security"
    ENVIRONMENT = "environment"


class OwnerRoleV2(StrEnum):
    SALES = "sales"
    PRESALES = "presales"
    CUSTOMER = "customer"
    JOINT = "joint"
    TBD = "tbd"


class AcceptanceClassification(StrEnum):
    CUSTOMER_CONFIRMED = "customer_confirmed"
    PROPOSED = "proposed"
    UNRESOLVED = "unresolved"


class TimingClassification(StrEnum):
    CONFIRMED = "confirmed"
    PROPOSED = "proposed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class SolutionAtomicClaimV2:
    claim_id: str
    statement_type: SolutionClaimTypeV2
    text: str
    citations: tuple[str, ...] = ()
    related_requirement_fields: tuple[RequirementDimension, ...] = ()


@dataclass(frozen=True, slots=True)
class CustomerRequirementRefV2:
    field: RequirementDimension
    status: RequirementStatus
    claim_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CustomerContextV2:
    confirmed_claim_ids: tuple[str, ...]
    unresolved_claim_ids: tuple[str, ...]
    requirement_fields: tuple[CustomerRequirementRefV2, ...]


@dataclass(frozen=True, slots=True)
class CapabilityGroupV2:
    group_id: str
    title: str
    claim_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProposedSolutionV2:
    overview_claim_ids: tuple[str, ...]
    capability_groups: tuple[CapabilityGroupV2, ...]


@dataclass(frozen=True, slots=True)
class ArchitectureComponentV2:
    component_id: str
    name: str
    responsibility_claim_ids: tuple[str, ...]
    rationale_claim_ids: tuple[str, ...]
    dependency_component_ids: tuple[str, ...]
    interface_claim_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArchitectureV2:
    overview_claim_ids: tuple[str, ...]
    components: tuple[ArchitectureComponentV2, ...]


@dataclass(frozen=True, slots=True)
class SolutionTopicBlockV2:
    block_id: str
    topic: SolutionTopicV2
    title: str
    claim_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImplementationPhaseV2:
    phase_id: str
    name: str
    objective_claim_ids: tuple[str, ...]
    task_claim_ids: tuple[str, ...]
    owner_roles: tuple[OwnerRoleV2, ...]
    deliverable_claim_ids: tuple[str, ...]
    dependency_phase_ids: tuple[str, ...]
    acceptance_criterion_ids: tuple[str, ...]
    timing_claim_id: str | None
    timing_classification: TimingClassification | None


@dataclass(frozen=True, slots=True)
class ImplementationPlanV2:
    phases: tuple[ImplementationPhaseV2, ...]


@dataclass(frozen=True, slots=True)
class RiskItemV2:
    risk_id: str
    condition_claim_id: str
    impact_claim_ids: tuple[str, ...]
    mitigation_claim_ids: tuple[str, ...]
    trigger_claim_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcceptanceCriterionV2:
    criterion_id: str
    claim_id: str
    classification: AcceptanceClassification


@dataclass(frozen=True, slots=True)
class MilestoneV2:
    milestone_id: str
    name: str
    related_phase_ids: tuple[str, ...]
    outcome_claim_ids: tuple[str, ...]
    timing_claim_id: str | None
    timing_classification: TimingClassification | None


@dataclass(frozen=True, slots=True)
class OpenQuestionV2:
    question_id: str
    requirement_field: RequirementDimension
    requirement_status: RequirementStatus
    unresolved_claim_id: str


@dataclass(frozen=True, slots=True)
class ScopeItemV2:
    scope_id: str
    claim_id: str
    classification: AcceptanceClassification


@dataclass(frozen=True, slots=True)
class SolutionDraftV2:
    title: str
    claims: tuple[SolutionAtomicClaimV2, ...]
    executive_summary_claim_ids: tuple[str, ...]
    customer_context: CustomerContextV2
    proposed_solution: ProposedSolutionV2
    architecture: ArchitectureV2
    deployment_and_integration: tuple[SolutionTopicBlockV2, ...]
    implementation_plan: ImplementationPlanV2
    risks: tuple[RiskItemV2, ...]
    acceptance_criteria: tuple[AcceptanceCriterionV2, ...]
    milestones: tuple[MilestoneV2, ...]
    assumption_claim_ids: tuple[str, ...]
    open_questions: tuple[OpenQuestionV2, ...]
    out_of_scope: tuple[ScopeItemV2, ...]


@dataclass(frozen=True, slots=True)
class V2ClaimProvenanceBinding:
    claim_id: str
    citation_label: str
    fact_id: int


@dataclass(frozen=True, slots=True)
class V2DeterministicContent:
    claims: tuple[SolutionAtomicClaimV2, ...]
    customer_context: CustomerContextV2
    enterprise_claim_ids: tuple[str, ...]
    unresolved_claim_ids: tuple[str, ...]
    assumption_claim_ids: tuple[str, ...]
    open_questions: tuple[OpenQuestionV2, ...]
    provenance_bindings: tuple[V2ClaimProvenanceBinding, ...]

    def claim_by_id(self, claim_id: str) -> SolutionAtomicClaimV2:
        for claim in self.claims:
            if claim.claim_id == claim_id:
                return claim
        _invalid()


@dataclass(frozen=True, slots=True)
class V2AssemblyResult:
    draft: SolutionDraftV2
    provenance_bindings: tuple[V2ClaimProvenanceBinding, ...]


@dataclass(frozen=True, slots=True)
class _DeterministicClaimSeed:
    statement_type: SolutionClaimTypeV2
    text: str
    citations: tuple[str, ...] = ()
    related_requirement_fields: tuple[RequirementDimension, ...] = ()
    fact_ids_by_citation: tuple[tuple[str, int], ...] = ()


def build_v2_deterministic_items(analysis, admission) -> V2DeterministicContent:
    """Create all non-proposal V2 claims from typed analysis and admission only."""

    from apps.knowledge.models import EnterpriseGroundingFactStatus
    from apps.knowledge.services.grounding_facts import GROUNDING_SUBJECT_REGISTRY
    from apps.sales.services.requirement_analysis import OpportunityRequirementAnalysis
    from apps.sales.services.solution_admission import GroundingAdmission
    from apps.sales.services.solution_schema import (
        SolutionStatementType,
        build_solution_unresolved_items,
    )

    if not isinstance(analysis, OpportunityRequirementAnalysis) or not isinstance(
        admission, GroundingAdmission
    ):
        _invalid()

    seeds: list[_DeterministicClaimSeed] = []
    requirement_seed_indexes: dict[RequirementDimension, int] = {}
    unresolved_by_field = {
        item.field: item for item in build_solution_unresolved_items(analysis)
    }
    for field in RequirementDimension:
        value = getattr(analysis.requirements, field.value)
        requirement_seed_indexes[field] = len(seeds)
        if value.status is RequirementStatus.KNOWN:
            if not isinstance(value.value, str) or not value.value.strip():
                _invalid()
            seeds.append(
                _DeterministicClaimSeed(
                    statement_type=SolutionClaimTypeV2.CUSTOMER_FACT,
                    text=f"{_FIELD_LABELS[field]}：{value.value}。",
                    related_requirement_fields=(field,),
                )
            )
        else:
            unresolved = unresolved_by_field.get(field)
            if unresolved is None:
                _invalid()
            seeds.append(
                _DeterministicClaimSeed(
                    statement_type=SolutionClaimTypeV2.UNRESOLVED,
                    text=unresolved.text,
                    related_requirement_fields=(field,),
                )
            )

    provenance_by_claim_identity = {
        id(item.claim): item for item in admission.enterprise_provenance
    }
    decision_by_subject = {
        item.subject_key: item for item in admission.enterprise_decisions
    }
    if len(decision_by_subject) != len(admission.enterprise_decisions):
        _invalid()

    enterprise_seed_indexes: list[int] = []
    enterprise_unresolved_seed_indexes: list[int] = []
    seen_enterprise_fact_ids: set[int] = set()
    for v1_claim in admission.claims.claims:
        if v1_claim.statement_type is not SolutionStatementType.ENTERPRISE_FACT:
            continue
        provenance = provenance_by_claim_identity.get(id(v1_claim))
        if (
            provenance is None
            or provenance.fact_id in seen_enterprise_fact_ids
            or provenance.subject_key not in decision_by_subject
        ):
            _invalid()
        decision = decision_by_subject[provenance.subject_key]
        status = EnterpriseGroundingFactStatus(decision.status)
        if status not in {
            EnterpriseGroundingFactStatus.CONFIRMED_SUPPORTED,
            EnterpriseGroundingFactStatus.CONFIRMED_UNSUPPORTED,
        } or provenance.fact_id not in decision.enterprise_fact_ids:
            _invalid()
        seen_enterprise_fact_ids.add(provenance.fact_id)
        enterprise_seed_indexes.append(len(seeds))
        seeds.append(
            _DeterministicClaimSeed(
                statement_type=SolutionClaimTypeV2.ENTERPRISE_FACT,
                text=v1_claim.text,
                citations=v1_claim.citations,
                fact_ids_by_citation=tuple(
                    (label, provenance.fact_id) for label in v1_claim.citations
                ),
            )
        )

    if seen_enterprise_fact_ids != {
        item.fact_id for item in admission.enterprise_provenance
    }:
        _invalid()

    for decision in admission.enterprise_decisions:
        status = EnterpriseGroundingFactStatus(decision.status)
        if status not in {
            EnterpriseGroundingFactStatus.UNCONFIRMED,
            EnterpriseGroundingFactStatus.CONFLICT,
        }:
            continue
        label = GROUNDING_SUBJECT_REGISTRY.get(decision.subject_key)
        if label is None:
            _invalid()
        text = (
            f"当前企业资料对{label}存在冲突，需要人工或售前确认。"
            if status is EnterpriseGroundingFactStatus.CONFLICT
            else f"当前企业资料未确认{label}，需要进一步确认。"
        )
        enterprise_unresolved_seed_indexes.append(len(seeds))
        seeds.append(
            _DeterministicClaimSeed(
                statement_type=SolutionClaimTypeV2.UNRESOLVED,
                text=text,
            )
        )

    assumption_seed_indexes: list[int] = []
    for field in RequirementDimension:
        value = getattr(analysis.requirements, field.value)
        if value.status is RequirementStatus.KNOWN:
            continue
        assumption_seed_indexes.append(len(seeds))
        seeds.append(
            _DeterministicClaimSeed(
                statement_type=SolutionClaimTypeV2.ASSUMPTION,
                text=f"方案实施以前置确认{_FIELD_LABELS[field]}为条件。",
                related_requirement_fields=(field,),
            )
        )

    claims = tuple(
        SolutionAtomicClaimV2(
            claim_id=f"C{index:04d}",
            statement_type=seed.statement_type,
            text=seed.text,
            citations=seed.citations,
            related_requirement_fields=seed.related_requirement_fields,
        )
        for index, seed in enumerate(seeds, start=1)
    )
    claim_ids = tuple(item.claim_id for item in claims)
    requirement_refs = tuple(
        CustomerRequirementRefV2(
            field=field,
            status=getattr(analysis.requirements, field.value).status,
            claim_ids=(claim_ids[requirement_seed_indexes[field]],),
        )
        for field in RequirementDimension
    )
    open_questions = tuple(
        OpenQuestionV2(
            question_id=f"Q{index:03d}",
            requirement_field=field,
            requirement_status=getattr(analysis.requirements, field.value).status,
            unresolved_claim_id=claim_ids[requirement_seed_indexes[field]],
        )
        for index, field in enumerate(
            (
                field
                for field in RequirementDimension
                if getattr(analysis.requirements, field.value).status
                is not RequirementStatus.KNOWN
            ),
            start=1,
        )
    )
    bindings = tuple(
        V2ClaimProvenanceBinding(
            claim_id=claim_ids[seed_index],
            citation_label=label,
            fact_id=fact_id,
        )
        for seed_index in enterprise_seed_indexes
        for label, fact_id in seeds[seed_index].fact_ids_by_citation
    )
    customer_ids = tuple(
        claim_ids[index]
        for field, index in requirement_seed_indexes.items()
        if getattr(analysis.requirements, field.value).status is RequirementStatus.KNOWN
    )
    requirement_unresolved_ids = tuple(
        claim_ids[index]
        for field, index in requirement_seed_indexes.items()
        if getattr(analysis.requirements, field.value).status
        is not RequirementStatus.KNOWN
    )
    return V2DeterministicContent(
        claims=claims,
        customer_context=CustomerContextV2(
            confirmed_claim_ids=customer_ids,
            unresolved_claim_ids=requirement_unresolved_ids,
            requirement_fields=requirement_refs,
        ),
        enterprise_claim_ids=tuple(claim_ids[index] for index in enterprise_seed_indexes),
        unresolved_claim_ids=(
            requirement_unresolved_ids
            + tuple(claim_ids[index] for index in enterprise_unresolved_seed_indexes)
        ),
        assumption_claim_ids=tuple(
            claim_ids[index] for index in assumption_seed_indexes
        ),
        open_questions=open_questions,
        provenance_bindings=bindings,
    )


def assemble_solution_draft_v2(
    deterministic: V2DeterministicContent,
    proposals,
) -> V2AssemblyResult:
    """Assemble the closed V2 structure without inventing semantic content."""

    from apps.sales.services.solution_prompt_v2 import (
        AtomicSolutionProposalSetV2,
        SolutionV2ContainerKind,
        SolutionV2PlacementField,
        SolutionV2Section,
        SolutionV2StructureRelationType,
        validate_solution_v2_structure_relations,
    )

    if not isinstance(deterministic, V2DeterministicContent) or not isinstance(
        proposals, AtomicSolutionProposalSetV2
    ):
        _invalid()
    validate_solution_v2_structure_relations(proposals)

    section_priority = {value: index for index, value in enumerate(SolutionV2Section)}
    kind_priority = {
        value: index for index, value in enumerate(SolutionV2ContainerKind)
    }
    field_priority = {
        value: index for index, value in enumerate(SolutionV2PlacementField)
    }
    ordered_proposals = tuple(sorted(
        proposals.proposals,
        key=lambda proposal: (
            section_priority[proposal.placement.section],
            kind_priority[proposal.placement.container_kind],
            proposal.placement.container_key or "",
            field_priority[proposal.placement.field],
            tuple(field.value for field in proposal.related_requirement_fields),
            proposal.text,
            proposal.citations,
        ),
    ))

    claims = list(deterministic.claims)
    proposal_claims: list[tuple[SolutionAtomicClaimV2, object]] = []
    for index, proposal in enumerate(ordered_proposals, start=len(claims) + 1):
        claim = SolutionAtomicClaimV2(
            claim_id=f"C{index:04d}",
            statement_type=SolutionClaimTypeV2.PROPOSAL,
            text=proposal.text,
            citations=proposal.citations,
            related_requirement_fields=proposal.related_requirement_fields,
        )
        claims.append(claim)
        proposal_claims.append((claim, proposal.placement))

    by_label: dict[str, list[int]] = {}
    for binding in deterministic.provenance_bindings:
        by_label.setdefault(binding.citation_label, []).append(binding.fact_id)
    bindings = list(deterministic.provenance_bindings)
    for claim, _ in proposal_claims:
        for label in claim.citations:
            fact_ids = by_label.get(label, [])
            if not fact_ids:
                _invalid()
            bindings.extend(
                V2ClaimProvenanceBinding(claim.claim_id, label, fact_id)
                for fact_id in fact_ids
            )

    proposed_overview: list[str] = []
    groups: dict[str, list[str]] = {}
    architecture_overview: list[str] = []
    components: dict[str, dict[str, list[str]]] = {}
    topic_blocks: dict[str, list[str]] = {}
    phases: dict[str, dict[str, list[str]]] = {}
    risks: dict[str, dict[str, list[str]]] = {}
    criteria: dict[str, str] = {}
    milestones: dict[str, dict[str, list[str]]] = {}
    scopes: dict[str, str] = {}

    for claim, placement in proposal_claims:
        claim_id = claim.claim_id
        section = placement.section
        kind = placement.container_kind
        field = placement.field
        key = placement.container_key
        if section is SolutionV2Section.PROPOSED_SOLUTION:
            if kind is SolutionV2ContainerKind.ROOT:
                proposed_overview.append(claim_id)
            else:
                groups.setdefault(key, []).append(claim_id)
        elif section is SolutionV2Section.ARCHITECTURE:
            if kind is SolutionV2ContainerKind.ROOT:
                architecture_overview.append(claim_id)
            else:
                bucket = components.setdefault(key, {
                    "responsibilities": [], "rationale": [], "interfaces": [],
                })
                bucket[field.value].append(claim_id)
        elif section is SolutionV2Section.DEPLOYMENT_AND_INTEGRATION:
            topic_blocks.setdefault(key, []).append(claim_id)
        elif section is SolutionV2Section.IMPLEMENTATION_PLAN:
            bucket = phases.setdefault(key, {
                "objective": [], "tasks": [], "deliverables": [], "timing": [],
            })
            bucket[field.value].append(claim_id)
        elif section is SolutionV2Section.RISKS:
            bucket = risks.setdefault(key, {
                "condition": [], "impact": [], "mitigation": [], "trigger": [],
            })
            bucket[field.value].append(claim_id)
        elif section is SolutionV2Section.ACCEPTANCE_CRITERIA:
            if key in criteria:
                _invalid()
            criteria[key] = claim_id
        elif section is SolutionV2Section.MILESTONES:
            bucket = milestones.setdefault(key, {"outcome": [], "timing": []})
            bucket[field.value].append(claim_id)
        elif section is SolutionV2Section.OUT_OF_SCOPE:
            if key in scopes:
                _invalid()
            scopes[key] = claim_id
        else:
            _invalid()

    component_dependencies: dict[str, set[str]] = {
        key: set() for key in components
    }
    phase_dependencies: dict[str, set[str]] = {key: set() for key in phases}
    phase_acceptance: dict[str, set[str]] = {key: set() for key in phases}
    milestone_phases: dict[str, set[str]] = {key: set() for key in milestones}
    for relation in proposals.structure_relations:
        if relation.relation_type is SolutionV2StructureRelationType.COMPONENT_DEPENDENCY:
            component_dependencies[relation.source_container_key].add(
                relation.target_container_key
            )
        elif relation.relation_type is SolutionV2StructureRelationType.PHASE_DEPENDENCY:
            phase_dependencies[relation.source_container_key].add(
                relation.target_container_key
            )
        elif relation.relation_type is SolutionV2StructureRelationType.PHASE_ACCEPTANCE:
            phase_acceptance[relation.source_container_key].add(
                relation.target_container_key
            )
        elif relation.relation_type is SolutionV2StructureRelationType.MILESTONE_PHASE:
            milestone_phases[relation.source_container_key].add(
                relation.target_container_key
            )
        else:
            _invalid()

    if any(len(value["timing"]) > 1 for value in phases.values()) or any(
        len(value["timing"]) > 1 for value in milestones.values()
    ):
        _invalid()
    if any(len(value["condition"]) != 1 for value in risks.values()):
        _invalid()

    criterion_items = tuple(
        AcceptanceCriterionV2(key, claim_id, AcceptanceClassification.PROPOSED)
        for key, claim_id in sorted(criteria.items())
    )
    component_order = _stable_topological_order(
        components.keys(), component_dependencies
    )
    phase_order = _stable_topological_order(phases.keys(), phase_dependencies)
    component_position = {key: index for index, key in enumerate(component_order)}
    phase_position = {key: index for index, key in enumerate(phase_order)}
    phase_items = tuple(
        ImplementationPhaseV2(
            phase_id=key,
            name=f"实施阶段 {phase_index}",
            objective_claim_ids=tuple(value["objective"]),
            task_claim_ids=tuple(value["tasks"]),
            owner_roles=(OwnerRoleV2.TBD,),
            deliverable_claim_ids=tuple(value["deliverables"]),
            dependency_phase_ids=tuple(sorted(
                phase_dependencies[key], key=phase_position.__getitem__
            )),
            acceptance_criterion_ids=tuple(sorted(phase_acceptance[key])),
            timing_claim_id=value["timing"][0] if value["timing"] else None,
            timing_classification=(
                TimingClassification.PROPOSED if value["timing"] else None
            ),
        )
        for phase_index, key in enumerate(phase_order, start=1)
        for value in (phases[key],)
    )
    milestone_items = tuple(
        MilestoneV2(
            milestone_id=key,
            name=f"里程碑 {milestone_index}",
            related_phase_ids=tuple(sorted(
                milestone_phases[key], key=phase_position.__getitem__
            )),
            outcome_claim_ids=tuple(value["outcome"]),
            timing_claim_id=value["timing"][0] if value["timing"] else None,
            timing_classification=(
                TimingClassification.PROPOSED if value["timing"] else None
            ),
        )
        for milestone_index, (key, value) in enumerate(
            sorted(milestones.items()), start=1
        )
    )
    capability_groups = []
    reserved_group_ids = {
        "enterprise_capability_basis",
        "enterprise_capability_gaps",
    }
    if reserved_group_ids & groups.keys():
        _invalid()
    if deterministic.enterprise_claim_ids:
        capability_groups.append(
            CapabilityGroupV2(
                "enterprise_capability_basis",
                "企业能力依据",
                deterministic.enterprise_claim_ids,
            )
        )
    enterprise_unresolved_ids = tuple(
        claim_id
        for claim_id in deterministic.unresolved_claim_ids
        if claim_id not in deterministic.customer_context.unresolved_claim_ids
    )
    if enterprise_unresolved_ids:
        capability_groups.append(
            CapabilityGroupV2(
                "enterprise_capability_gaps",
                "企业能力待确认",
                enterprise_unresolved_ids,
            )
        )
    capability_groups.extend(
        CapabilityGroupV2(key, f"方案分组 {index}", tuple(claim_ids))
        for index, (key, claim_ids) in enumerate(sorted(groups.items()), start=1)
    )
    summary_section_priority = {
        section: priority
        for priority, section in enumerate(
            (
                SolutionV2Section.PROPOSED_SOLUTION,
                SolutionV2Section.ARCHITECTURE,
                SolutionV2Section.DEPLOYMENT_AND_INTEGRATION,
                SolutionV2Section.IMPLEMENTATION_PLAN,
                SolutionV2Section.ACCEPTANCE_CRITERIA,
                SolutionV2Section.RISKS,
                SolutionV2Section.MILESTONES,
                SolutionV2Section.OUT_OF_SCOPE,
            )
        )
    }
    summary_proposal_ids = tuple(
        claim.claim_id
        for claim, _placement in sorted(
            proposal_claims,
            key=lambda item: summary_section_priority[item[1].section],
        )[:4]
    )
    draft = SolutionDraftV2(
        title="商机需求可执行技术方案",
        claims=tuple(claims),
        executive_summary_claim_ids=tuple(
            dict.fromkeys(
                deterministic.customer_context.confirmed_claim_ids[:1]
                + summary_proposal_ids
                + deterministic.customer_context.unresolved_claim_ids[:1]
            )
        )[:8],
        customer_context=deterministic.customer_context,
        proposed_solution=ProposedSolutionV2(
            overview_claim_ids=tuple(proposed_overview),
            capability_groups=tuple(capability_groups),
        ),
        architecture=ArchitectureV2(
            overview_claim_ids=tuple(architecture_overview),
            components=tuple(
                ArchitectureComponentV2(
                    component_id=key,
                    name=f"架构组件 {index}",
                    responsibility_claim_ids=tuple(value["responsibilities"]),
                    rationale_claim_ids=tuple(value["rationale"]),
                    dependency_component_ids=tuple(sorted(
                        component_dependencies[key], key=component_position.__getitem__
                    )),
                    interface_claim_ids=tuple(value["interfaces"]),
                )
                for index, key in enumerate(component_order, start=1)
                for value in (components[key],)
            ),
        ),
        deployment_and_integration=tuple(
            SolutionTopicBlockV2(
                block_id=key,
                topic=_topic_from_key(key),
                title=_topic_label(_topic_from_key(key)),
                claim_ids=tuple(claim_ids),
            )
            for key, claim_ids in sorted(topic_blocks.items())
        ),
        implementation_plan=ImplementationPlanV2(phase_items),
        risks=tuple(
            RiskItemV2(
                risk_id=key,
                condition_claim_id=value["condition"][0],
                impact_claim_ids=tuple(value["impact"]),
                mitigation_claim_ids=tuple(value["mitigation"]),
                trigger_claim_ids=tuple(value["trigger"]),
            )
            for key, value in sorted(risks.items())
        ),
        acceptance_criteria=criterion_items,
        milestones=milestone_items,
        assumption_claim_ids=deterministic.assumption_claim_ids,
        open_questions=deterministic.open_questions,
        out_of_scope=tuple(
            ScopeItemV2(key, claim_id, AcceptanceClassification.PROPOSED)
            for key, claim_id in sorted(scopes.items())
        ),
    )
    validate_solution_draft_v2(draft)
    return V2AssemblyResult(draft, tuple(bindings))


def _stable_topological_order(
    nodes: Iterable[str],
    dependencies: dict[str, set[str]],
) -> tuple[str, ...]:
    """Order dependency targets before sources with a stable key tie-break."""

    remaining = set(nodes)
    resolved: set[str] = set()
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            node
            for node in remaining
            if dependencies.get(node, set()) <= resolved
        )
        if not ready:
            _invalid()
        ordered.extend(ready)
        resolved.update(ready)
        remaining.difference_update(ready)
    return tuple(ordered)


def _topic_label(topic: SolutionTopicV2) -> str:
    return {
        SolutionTopicV2.DEPLOYMENT: "部署",
        SolutionTopicV2.INTEGRATION: "集成",
        SolutionTopicV2.DATA_SECURITY: "数据安全",
        SolutionTopicV2.ENVIRONMENT: "现有环境",
    }[topic]


def _topic_from_key(identifier: str) -> SolutionTopicV2:
    try:
        return SolutionTopicV2(identifier)
    except ValueError:
        _invalid()


_CLAIM_ID = re.compile(r"C[0-9]{4,}")
_STRUCTURAL_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_CITATION = re.compile(r"S[1-9][0-9]*")
_INLINE_SOURCE = re.compile(r"(?<![A-Za-z0-9_])S[0-9]+(?![A-Za-z0-9_])")
_LABEL_SENTENCE_PUNCTUATION = frozenset("。！？.!?；;：:\r\n")


def validate_solution_draft_v2(draft: SolutionDraftV2) -> None:
    """Reject any V2 value that could bypass the atomic-claim authority."""

    if not isinstance(draft, SolutionDraftV2):
        _invalid()
    _label(draft.title, maximum=255)
    _tuple(draft.claims)
    if not draft.claims:
        _invalid()

    claims: dict[str, SolutionAtomicClaimV2] = {}
    for value in draft.claims:
        _validate_claim(value)
        if value.claim_id in claims:
            _invalid()
        claims[value.claim_id] = value

    references_without_summary: set[str] = set()
    _claim_refs(draft.executive_summary_claim_ids, claims)
    if len(draft.executive_summary_claim_ids) > 8:
        _invalid()

    _validate_customer_context(draft.customer_context, claims, references_without_summary)
    _validate_proposed_solution(draft.proposed_solution, claims, references_without_summary)
    _validate_architecture(draft.architecture, claims, references_without_summary)
    _validate_topic_blocks(
        draft.deployment_and_integration, claims, references_without_summary
    )

    criteria = _validate_criteria(
        draft.acceptance_criteria, claims, references_without_summary
    )
    phases = _validate_implementation_plan(
        draft.implementation_plan,
        claims,
        criteria,
        references_without_summary,
    )
    _validate_risks(draft.risks, claims, references_without_summary)
    _validate_milestones(draft.milestones, claims, phases, references_without_summary)

    _claim_refs(draft.assumption_claim_ids, claims, references_without_summary)
    if any(
        claims[claim_id].statement_type is not SolutionClaimTypeV2.ASSUMPTION
        for claim_id in draft.assumption_claim_ids
    ):
        _invalid()
    _validate_open_questions(draft.open_questions, claims, references_without_summary)
    _validate_scope(draft.out_of_scope, claims, references_without_summary)

    if not set(draft.executive_summary_claim_ids) <= references_without_summary:
        _invalid()
    if set(claims) != references_without_summary:
        _invalid()


def _validate_claim(value: object) -> None:
    if not isinstance(value, SolutionAtomicClaimV2):
        _invalid()
    if not isinstance(value.claim_id, str) or _CLAIM_ID.fullmatch(value.claim_id) is None:
        _invalid()
    if not isinstance(value.statement_type, SolutionClaimTypeV2):
        _invalid()
    if not isinstance(value.text, str) or not value.text.strip() or len(value.text) > 1000:
        _invalid()
    if value.text != value.text.strip() or _INLINE_SOURCE.search(value.text):
        _invalid()
    _tuple(value.citations)
    if (
        len(set(value.citations)) != len(value.citations)
        or any(
            not isinstance(citation, str) or _CITATION.fullmatch(citation) is None
            for citation in value.citations
        )
    ):
        _invalid()
    _tuple(value.related_requirement_fields)
    if (
        len(set(value.related_requirement_fields))
        != len(value.related_requirement_fields)
        or any(
            not isinstance(field, RequirementDimension)
            for field in value.related_requirement_fields
        )
    ):
        _invalid()

    if value.statement_type in {
        SolutionClaimTypeV2.ENTERPRISE_FACT,
        SolutionClaimTypeV2.PROPOSAL,
    }:
        if not value.citations:
            _invalid()
    elif value.citations:
        _invalid()
    if (
        value.statement_type is SolutionClaimTypeV2.ASSUMPTION
        and not value.related_requirement_fields
    ):
        _invalid()


def _validate_customer_context(
    value: CustomerContextV2,
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> None:
    if not isinstance(value, CustomerContextV2):
        _invalid()
    _claim_refs(value.confirmed_claim_ids, claims, used)
    _claim_refs(value.unresolved_claim_ids, claims, used)
    if any(
        claims[claim_id].statement_type is not SolutionClaimTypeV2.CUSTOMER_FACT
        for claim_id in value.confirmed_claim_ids
    ) or any(
        claims[claim_id].statement_type is not SolutionClaimTypeV2.UNRESOLVED
        for claim_id in value.unresolved_claim_ids
    ):
        _invalid()
    _tuple(value.requirement_fields)
    seen_fields: set[RequirementDimension] = set()
    for item in value.requirement_fields:
        if (
            not isinstance(item, CustomerRequirementRefV2)
            or not isinstance(item.field, RequirementDimension)
            or not isinstance(item.status, RequirementStatus)
            or item.field in seen_fields
        ):
            _invalid()
        seen_fields.add(item.field)
        _claim_refs(item.claim_ids, claims, used)
        expected = (
            SolutionClaimTypeV2.CUSTOMER_FACT
            if item.status is RequirementStatus.KNOWN
            else SolutionClaimTypeV2.UNRESOLVED
        )
        if any(claims[claim_id].statement_type is not expected for claim_id in item.claim_ids):
            _invalid()


def _validate_proposed_solution(
    value: ProposedSolutionV2,
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> None:
    if not isinstance(value, ProposedSolutionV2):
        _invalid()
    _claim_refs(value.overview_claim_ids, claims, used)
    _tuple(value.capability_groups)
    seen: set[str] = set()
    for group in value.capability_groups:
        if not isinstance(group, CapabilityGroupV2):
            _invalid()
        _identifier(group.group_id)
        _label(group.title)
        if group.group_id in seen or not group.claim_ids:
            _invalid()
        seen.add(group.group_id)
        _claim_refs(group.claim_ids, claims, used)


def _validate_architecture(
    value: ArchitectureV2,
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> None:
    if not isinstance(value, ArchitectureV2):
        _invalid()
    _claim_refs(value.overview_claim_ids, claims, used)
    _tuple(value.components)
    component_ids: set[str] = set()
    for component in value.components:
        if not isinstance(component, ArchitectureComponentV2):
            _invalid()
        _identifier(component.component_id)
        _label(component.name)
        if component.component_id in component_ids:
            _invalid()
        component_ids.add(component.component_id)
    for component in value.components:
        _claim_refs(component.responsibility_claim_ids, claims, used)
        _claim_refs(component.rationale_claim_ids, claims, used)
        _claim_refs(component.interface_claim_ids, claims, used)
        _tuple(component.dependency_component_ids)
        if (
            len(set(component.dependency_component_ids))
            != len(component.dependency_component_ids)
            or component.component_id in component.dependency_component_ids
            or not set(component.dependency_component_ids) <= component_ids
        ):
            _invalid()
    _stable_topological_order(
        component_ids,
        {
            component.component_id: set(component.dependency_component_ids)
            for component in value.components
        },
    )


def _validate_topic_blocks(
    values: tuple[SolutionTopicBlockV2, ...],
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> None:
    _tuple(values)
    seen: set[str] = set()
    for block in values:
        if not isinstance(block, SolutionTopicBlockV2) or not isinstance(
            block.topic, SolutionTopicV2
        ):
            _invalid()
        _identifier(block.block_id)
        _label(block.title)
        if block.block_id in seen or not block.claim_ids:
            _invalid()
        seen.add(block.block_id)
        _claim_refs(block.claim_ids, claims, used)


def _validate_criteria(
    values: tuple[AcceptanceCriterionV2, ...],
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> dict[str, AcceptanceCriterionV2]:
    _tuple(values)
    result: dict[str, AcceptanceCriterionV2] = {}
    for criterion in values:
        if not isinstance(criterion, AcceptanceCriterionV2):
            _invalid()
        _identifier(criterion.criterion_id)
        if criterion.criterion_id in result:
            _invalid()
        _claim_refs((criterion.claim_id,), claims, used)
        _validate_authority_classification(
            criterion.classification, claims[criterion.claim_id]
        )
        result[criterion.criterion_id] = criterion
    return result


def _validate_implementation_plan(
    value: ImplementationPlanV2,
    claims: dict[str, SolutionAtomicClaimV2],
    criteria: dict[str, AcceptanceCriterionV2],
    used: set[str],
) -> set[str]:
    if not isinstance(value, ImplementationPlanV2):
        _invalid()
    _tuple(value.phases)
    preceding: set[str] = set()
    for phase in value.phases:
        if not isinstance(phase, ImplementationPhaseV2):
            _invalid()
        _identifier(phase.phase_id)
        _label(phase.name)
        if phase.phase_id in preceding:
            _invalid()
        _claim_refs(phase.objective_claim_ids, claims, used)
        _claim_refs(phase.task_claim_ids, claims, used)
        _claim_refs(phase.deliverable_claim_ids, claims, used)
        _tuple(phase.owner_roles)
        if (
            not phase.owner_roles
            or len(set(phase.owner_roles)) != len(phase.owner_roles)
            or any(not isinstance(role, OwnerRoleV2) for role in phase.owner_roles)
        ):
            _invalid()
        _tuple(phase.dependency_phase_ids)
        if (
            len(set(phase.dependency_phase_ids)) != len(phase.dependency_phase_ids)
            or not set(phase.dependency_phase_ids) <= preceding
        ):
            _invalid()
        _tuple(phase.acceptance_criterion_ids)
        if (
            len(set(phase.acceptance_criterion_ids))
            != len(phase.acceptance_criterion_ids)
            or not set(phase.acceptance_criterion_ids) <= set(criteria)
        ):
            _invalid()
        _validate_timing(
            phase.timing_claim_id, phase.timing_classification, claims, used
        )
        preceding.add(phase.phase_id)
    return preceding


def _validate_risks(
    values: tuple[RiskItemV2, ...],
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> None:
    _tuple(values)
    seen: set[str] = set()
    for risk in values:
        if not isinstance(risk, RiskItemV2):
            _invalid()
        _identifier(risk.risk_id)
        if risk.risk_id in seen:
            _invalid()
        seen.add(risk.risk_id)
        _claim_refs((risk.condition_claim_id,), claims, used)
        _claim_refs(risk.impact_claim_ids, claims, used)
        _claim_refs(risk.mitigation_claim_ids, claims, used)
        _claim_refs(risk.trigger_claim_ids, claims, used)


def _validate_milestones(
    values: tuple[MilestoneV2, ...],
    claims: dict[str, SolutionAtomicClaimV2],
    phases: set[str],
    used: set[str],
) -> None:
    _tuple(values)
    seen: set[str] = set()
    for milestone in values:
        if not isinstance(milestone, MilestoneV2):
            _invalid()
        _identifier(milestone.milestone_id)
        _label(milestone.name)
        if milestone.milestone_id in seen:
            _invalid()
        seen.add(milestone.milestone_id)
        _tuple(milestone.related_phase_ids)
        if not set(milestone.related_phase_ids) <= phases:
            _invalid()
        _claim_refs(milestone.outcome_claim_ids, claims, used)
        _validate_timing(
            milestone.timing_claim_id,
            milestone.timing_classification,
            claims,
            used,
        )


def _validate_open_questions(
    values: tuple[OpenQuestionV2, ...],
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> None:
    _tuple(values)
    seen: set[str] = set()
    for question in values:
        if (
            not isinstance(question, OpenQuestionV2)
            or not isinstance(question.requirement_field, RequirementDimension)
            or question.requirement_status not in {
                RequirementStatus.UNKNOWN,
                RequirementStatus.UNCLEAR,
                RequirementStatus.CONFLICT,
            }
        ):
            _invalid()
        _identifier(question.question_id)
        if question.question_id in seen:
            _invalid()
        seen.add(question.question_id)
        _claim_refs((question.unresolved_claim_id,), claims, used)
        claim = claims[question.unresolved_claim_id]
        if (
            claim.statement_type is not SolutionClaimTypeV2.UNRESOLVED
            or question.requirement_field not in claim.related_requirement_fields
        ):
            _invalid()


def _validate_scope(
    values: tuple[ScopeItemV2, ...],
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> None:
    _tuple(values)
    seen: set[str] = set()
    for scope in values:
        if not isinstance(scope, ScopeItemV2):
            _invalid()
        _identifier(scope.scope_id)
        if scope.scope_id in seen:
            _invalid()
        seen.add(scope.scope_id)
        _claim_refs((scope.claim_id,), claims, used)
        _validate_authority_classification(scope.classification, claims[scope.claim_id])


def _validate_authority_classification(
    classification: AcceptanceClassification,
    claim: SolutionAtomicClaimV2,
) -> None:
    expected = {
        AcceptanceClassification.CUSTOMER_CONFIRMED: SolutionClaimTypeV2.CUSTOMER_FACT,
        AcceptanceClassification.PROPOSED: SolutionClaimTypeV2.PROPOSAL,
        AcceptanceClassification.UNRESOLVED: SolutionClaimTypeV2.UNRESOLVED,
    }
    if not isinstance(classification, AcceptanceClassification) or expected.get(
        classification
    ) is not claim.statement_type:
        _invalid()


def _validate_timing(
    claim_id: str | None,
    classification: TimingClassification | None,
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str],
) -> None:
    if claim_id is None:
        if classification is not None:
            _invalid()
        return
    if not isinstance(classification, TimingClassification):
        _invalid()
    _claim_refs((claim_id,), claims, used)
    claim_type = claims[claim_id].statement_type
    allowed = {
        TimingClassification.CONFIRMED: {
            SolutionClaimTypeV2.CUSTOMER_FACT,
            SolutionClaimTypeV2.ENTERPRISE_FACT,
        },
        TimingClassification.PROPOSED: {SolutionClaimTypeV2.PROPOSAL},
        TimingClassification.UNRESOLVED: {SolutionClaimTypeV2.UNRESOLVED},
    }
    if claim_type not in allowed[classification]:
        _invalid()


def _claim_refs(
    values: tuple[str, ...],
    claims: dict[str, SolutionAtomicClaimV2],
    used: set[str] | None = None,
) -> None:
    _tuple(values)
    if (
        len(set(values)) != len(values)
        or any(not isinstance(value, str) or value not in claims for value in values)
    ):
        _invalid()
    if used is not None:
        used.update(values)


def _identifier(value: object) -> None:
    if not isinstance(value, str) or _STRUCTURAL_ID.fullmatch(value) is None:
        _invalid()


def _label(value: object, *, maximum: int = 64) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or any(character in value for character in _LABEL_SENTENCE_PUNCTUATION)
        or _INLINE_SOURCE.search(value)
    ):
        _invalid()


def _tuple(value: object) -> None:
    if not isinstance(value, tuple):
        _invalid()


def _invalid() -> NoReturn:
    raise SolutionDraftError(SolutionDraftErrorCode.INVALID_RESPONSE)
