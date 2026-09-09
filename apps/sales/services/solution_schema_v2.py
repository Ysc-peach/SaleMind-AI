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
