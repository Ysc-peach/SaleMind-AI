"""Strict, versioned JSON mapping for immutable Solution domain values."""

import re
from dataclasses import dataclass
from typing import NoReturn

from apps.sales.services.requirement_analysis import (
    RequirementDimension,
    RequirementStatus,
)
from apps.sales.services.solution_schema import (
    SECTION_DEFINITIONS,
    SolutionAssumption,
    SolutionDraft,
    SolutionSection,
    SolutionStatement,
    SolutionStatementType,
)
from apps.sales.services.solution_schema_v2 import (
    AcceptanceClassification,
    AcceptanceCriterionV2,
    ArchitectureComponentV2,
    ArchitectureV2,
    CapabilityGroupV2,
    CustomerContextV2,
    CustomerRequirementRefV2,
    ImplementationPhaseV2,
    ImplementationPlanV2,
    MilestoneV2,
    OpenQuestionV2,
    OwnerRoleV2,
    ProposedSolutionV2,
    RiskItemV2,
    ScopeItemV2,
    SolutionAtomicClaimV2,
    SolutionClaimTypeV2,
    SolutionDraftV2,
    SolutionTopicBlockV2,
    SolutionTopicV2,
    TimingClassification,
    validate_solution_draft_v2,
)


class SolutionPayloadError(Exception):
    """Stable error for an unsupported or malformed persisted payload."""

    def __init__(self):
        super().__init__("The Solution Draft payload is invalid.")


@dataclass(frozen=True, slots=True)
class SerializedSolutionDraft:
    schema_version: int
    payload: dict


def serialize_solution_domain(
    draft: SolutionDraft | SolutionDraftV2,
) -> SerializedSolutionDraft:
    if isinstance(draft, SolutionDraft):
        return SerializedSolutionDraft(1, solution_draft_v1_to_payload(draft))
    if isinstance(draft, SolutionDraftV2):
        return SerializedSolutionDraft(2, solution_draft_v2_to_payload(draft))
    _invalid()


def deserialize_solution_payload(
    schema_version: object,
    payload: object,
) -> SolutionDraft | SolutionDraftV2:
    if schema_version == 1 and type(schema_version) is int:
        return solution_draft_v1_from_payload(payload)
    if schema_version == 2 and type(schema_version) is int:
        return solution_draft_v2_from_payload(payload)
    _invalid()


def solution_draft_v1_to_payload(draft: SolutionDraft) -> dict:
    if not isinstance(draft, SolutionDraft):
        _invalid()
    payload = {
        "title": draft.title,
        "executive_summary": [_statement_to_payload(item) for item in draft.executive_summary],
        "solution_sections": [
            {
                "key": section.key,
                "title": section.title,
                "statements": [_statement_to_payload(item) for item in section.statements],
            }
            for section in draft.solution_sections
        ],
        "assumptions": [
            {
                "text": item.text,
                "related_fields": [field.value for field in item.related_fields],
            }
            for item in draft.assumptions
        ],
    }
    if solution_draft_v1_from_payload(payload) != draft:
        _invalid()
    return payload


def solution_draft_v1_from_payload(payload: object) -> SolutionDraft:
    _object(payload, {"title", "executive_summary", "solution_sections", "assumptions"})
    title = _text(payload["title"])
    summary = _v1_statements(payload["executive_summary"], maximum=8)
    sections_payload = payload["solution_sections"]
    if not isinstance(sections_payload, list) or len(sections_payload) != len(
        SECTION_DEFINITIONS
    ):
        _invalid()
    sections = []
    for value, (expected_key, expected_title) in zip(
        sections_payload, SECTION_DEFINITIONS, strict=True
    ):
        _object(value, {"key", "title", "statements"})
        if value["key"] != expected_key or value["title"] != expected_title:
            _invalid()
        sections.append(
            SolutionSection(
                key=expected_key,
                title=expected_title,
                statements=_v1_statements(value["statements"], maximum=12),
            )
        )
    assumptions_payload = payload["assumptions"]
    if not isinstance(assumptions_payload, list) or len(assumptions_payload) > 10:
        _invalid()
    assumptions = []
    for value in assumptions_payload:
        _object(value, {"text", "related_fields"})
        fields = value["related_fields"]
        if (
            not isinstance(fields, list)
            or not fields
            or len(fields) != len(set(fields))
            or any(
                not isinstance(field, str)
                or field not in RequirementDimension._value2member_map_
                for field in fields
            )
        ):
            _invalid()
        assumptions.append(
            SolutionAssumption(
                text=_text(value["text"]),
                related_fields=tuple(RequirementDimension(field) for field in fields),
            )
        )
    return SolutionDraft(
        title=title,
        executive_summary=summary,
        solution_sections=tuple(sections),
        assumptions=tuple(assumptions),
    )


def solution_draft_v2_to_payload(draft: SolutionDraftV2) -> dict:
    try:
        validate_solution_draft_v2(draft)
    except Exception as exc:
        raise SolutionPayloadError() from exc
    payload = {
        "title": draft.title,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "statement_type": claim.statement_type.value,
                "text": claim.text,
                "citations": list(claim.citations),
                "related_requirement_fields": [
                    field.value for field in claim.related_requirement_fields
                ],
            }
            for claim in draft.claims
        ],
        "executive_summary": list(draft.executive_summary_claim_ids),
        "customer_context": {
            "confirmed_claim_ids": list(draft.customer_context.confirmed_claim_ids),
            "unresolved_claim_ids": list(draft.customer_context.unresolved_claim_ids),
            "requirement_fields": [
                {
                    "field": item.field.value,
                    "status": item.status.value,
                    "claim_ids": list(item.claim_ids),
                }
                for item in draft.customer_context.requirement_fields
            ],
        },
        "proposed_solution": {
            "overview_claim_ids": list(draft.proposed_solution.overview_claim_ids),
            "capability_groups": [
                {
                    "group_id": group.group_id,
                    "title": group.title,
                    "claim_ids": list(group.claim_ids),
                }
                for group in draft.proposed_solution.capability_groups
            ],
        },
        "architecture": {
            "overview_claim_ids": list(draft.architecture.overview_claim_ids),
            "components": [
                {
                    "component_id": component.component_id,
                    "name": component.name,
                    "responsibility_claim_ids": list(
                        component.responsibility_claim_ids
                    ),
                    "rationale_claim_ids": list(component.rationale_claim_ids),
                    "dependency_component_ids": list(
                        component.dependency_component_ids
                    ),
                    "interface_claim_ids": list(component.interface_claim_ids),
                }
                for component in draft.architecture.components
            ],
        },
        "deployment_and_integration": [
            {
                "block_id": block.block_id,
                "topic": block.topic.value,
                "title": block.title,
                "claim_ids": list(block.claim_ids),
            }
            for block in draft.deployment_and_integration
        ],
        "implementation_plan": {
            "phases": [
                {
                    "phase_id": phase.phase_id,
                    "name": phase.name,
                    "objective_claim_ids": list(phase.objective_claim_ids),
                    "task_claim_ids": list(phase.task_claim_ids),
                    "owner_roles": [role.value for role in phase.owner_roles],
                    "deliverable_claim_ids": list(phase.deliverable_claim_ids),
                    "dependency_phase_ids": list(phase.dependency_phase_ids),
                    "acceptance_criterion_ids": list(
                        phase.acceptance_criterion_ids
                    ),
                    "timing_claim_id": phase.timing_claim_id,
                    "timing_classification": _enum_value(
                        phase.timing_classification
                    ),
                }
                for phase in draft.implementation_plan.phases
            ]
        },
        "risks": [
            {
                "risk_id": risk.risk_id,
                "condition_claim_id": risk.condition_claim_id,
                "impact_claim_ids": list(risk.impact_claim_ids),
                "mitigation_claim_ids": list(risk.mitigation_claim_ids),
                "trigger_claim_ids": list(risk.trigger_claim_ids),
            }
            for risk in draft.risks
        ],
        "acceptance_criteria": [
            {
                "criterion_id": criterion.criterion_id,
                "claim_id": criterion.claim_id,
                "classification": criterion.classification.value,
            }
            for criterion in draft.acceptance_criteria
        ],
        "milestones": [
            {
                "milestone_id": milestone.milestone_id,
                "name": milestone.name,
                "related_phase_ids": list(milestone.related_phase_ids),
                "outcome_claim_ids": list(milestone.outcome_claim_ids),
                "timing_claim_id": milestone.timing_claim_id,
                "timing_classification": _enum_value(
                    milestone.timing_classification
                ),
            }
            for milestone in draft.milestones
        ],
        "assumptions": list(draft.assumption_claim_ids),
        "open_questions": [
            {
                "question_id": question.question_id,
                "requirement_field": question.requirement_field.value,
                "requirement_status": question.requirement_status.value,
                "unresolved_claim_id": question.unresolved_claim_id,
            }
            for question in draft.open_questions
        ],
        "out_of_scope": [
            {
                "scope_id": item.scope_id,
                "claim_id": item.claim_id,
                "classification": item.classification.value,
            }
            for item in draft.out_of_scope
        ],
    }
    if solution_draft_v2_from_payload(payload) != draft:
        _invalid()
    return payload


def solution_draft_v2_from_payload(payload: object) -> SolutionDraftV2:
    _object(
        payload,
        {
            "title",
            "claims",
            "executive_summary",
            "customer_context",
            "proposed_solution",
            "architecture",
            "deployment_and_integration",
            "implementation_plan",
            "risks",
            "acceptance_criteria",
            "milestones",
            "assumptions",
            "open_questions",
            "out_of_scope",
        },
    )
    claims = tuple(_claim_from_payload(value) for value in _list(payload["claims"]))

    context_payload = payload["customer_context"]
    _object(
        context_payload,
        {"confirmed_claim_ids", "unresolved_claim_ids", "requirement_fields"},
    )
    context = CustomerContextV2(
        confirmed_claim_ids=_string_tuple(context_payload["confirmed_claim_ids"]),
        unresolved_claim_ids=_string_tuple(context_payload["unresolved_claim_ids"]),
        requirement_fields=tuple(
            _requirement_ref_from_payload(value)
            for value in _list(context_payload["requirement_fields"])
        ),
    )

    proposed_payload = payload["proposed_solution"]
    _object(proposed_payload, {"overview_claim_ids", "capability_groups"})
    proposed = ProposedSolutionV2(
        overview_claim_ids=_string_tuple(proposed_payload["overview_claim_ids"]),
        capability_groups=tuple(
            _capability_group_from_payload(value)
            for value in _list(proposed_payload["capability_groups"])
        ),
    )

    architecture_payload = payload["architecture"]
    _object(architecture_payload, {"overview_claim_ids", "components"})
    architecture = ArchitectureV2(
        overview_claim_ids=_string_tuple(architecture_payload["overview_claim_ids"]),
        components=tuple(
            _component_from_payload(value)
            for value in _list(architecture_payload["components"])
        ),
    )

    implementation_payload = payload["implementation_plan"]
    _object(implementation_payload, {"phases"})
    draft = SolutionDraftV2(
        title=_text(payload["title"]),
        claims=claims,
        executive_summary_claim_ids=_string_tuple(payload["executive_summary"]),
        customer_context=context,
        proposed_solution=proposed,
        architecture=architecture,
        deployment_and_integration=tuple(
            _topic_block_from_payload(value)
            for value in _list(payload["deployment_and_integration"])
        ),
        implementation_plan=ImplementationPlanV2(
            phases=tuple(
                _phase_from_payload(value)
                for value in _list(implementation_payload["phases"])
            )
        ),
        risks=tuple(_risk_from_payload(value) for value in _list(payload["risks"])),
        acceptance_criteria=tuple(
            _criterion_from_payload(value)
            for value in _list(payload["acceptance_criteria"])
        ),
        milestones=tuple(
            _milestone_from_payload(value) for value in _list(payload["milestones"])
        ),
        assumption_claim_ids=_string_tuple(payload["assumptions"]),
        open_questions=tuple(
            _question_from_payload(value)
            for value in _list(payload["open_questions"])
        ),
        out_of_scope=tuple(
            _scope_from_payload(value) for value in _list(payload["out_of_scope"])
        ),
    )
    try:
        validate_solution_draft_v2(draft)
    except Exception as exc:
        raise SolutionPayloadError() from exc
    return draft


def _claim_from_payload(value: object) -> SolutionAtomicClaimV2:
    _object(
        value,
        {
            "claim_id",
            "statement_type",
            "text",
            "citations",
            "related_requirement_fields",
        },
    )
    return SolutionAtomicClaimV2(
        claim_id=_text(value["claim_id"]),
        statement_type=_enum(SolutionClaimTypeV2, value["statement_type"]),
        text=_text(value["text"]),
        citations=_string_tuple(value["citations"]),
        related_requirement_fields=tuple(
            _enum(RequirementDimension, field)
            for field in _list(value["related_requirement_fields"])
        ),
    )


def _requirement_ref_from_payload(value: object) -> CustomerRequirementRefV2:
    _object(value, {"field", "status", "claim_ids"})
    return CustomerRequirementRefV2(
        field=_enum(RequirementDimension, value["field"]),
        status=_enum(RequirementStatus, value["status"]),
        claim_ids=_string_tuple(value["claim_ids"]),
    )


def _capability_group_from_payload(value: object) -> CapabilityGroupV2:
    _object(value, {"group_id", "title", "claim_ids"})
    return CapabilityGroupV2(
        group_id=_text(value["group_id"]),
        title=_text(value["title"]),
        claim_ids=_string_tuple(value["claim_ids"]),
    )


def _component_from_payload(value: object) -> ArchitectureComponentV2:
    _object(
        value,
        {
            "component_id",
            "name",
            "responsibility_claim_ids",
            "rationale_claim_ids",
            "dependency_component_ids",
            "interface_claim_ids",
        },
    )
    return ArchitectureComponentV2(
        component_id=_text(value["component_id"]),
        name=_text(value["name"]),
        responsibility_claim_ids=_string_tuple(value["responsibility_claim_ids"]),
        rationale_claim_ids=_string_tuple(value["rationale_claim_ids"]),
        dependency_component_ids=_string_tuple(value["dependency_component_ids"]),
        interface_claim_ids=_string_tuple(value["interface_claim_ids"]),
    )


def _topic_block_from_payload(value: object) -> SolutionTopicBlockV2:
    _object(value, {"block_id", "topic", "title", "claim_ids"})
    return SolutionTopicBlockV2(
        block_id=_text(value["block_id"]),
        topic=_enum(SolutionTopicV2, value["topic"]),
        title=_text(value["title"]),
        claim_ids=_string_tuple(value["claim_ids"]),
    )


def _phase_from_payload(value: object) -> ImplementationPhaseV2:
    _object(
        value,
        {
            "phase_id",
            "name",
            "objective_claim_ids",
            "task_claim_ids",
            "owner_roles",
            "deliverable_claim_ids",
            "dependency_phase_ids",
            "acceptance_criterion_ids",
            "timing_claim_id",
            "timing_classification",
        },
    )
    return ImplementationPhaseV2(
        phase_id=_text(value["phase_id"]),
        name=_text(value["name"]),
        objective_claim_ids=_string_tuple(value["objective_claim_ids"]),
        task_claim_ids=_string_tuple(value["task_claim_ids"]),
        owner_roles=tuple(
            _enum(OwnerRoleV2, role) for role in _list(value["owner_roles"])
        ),
        deliverable_claim_ids=_string_tuple(value["deliverable_claim_ids"]),
        dependency_phase_ids=_string_tuple(value["dependency_phase_ids"]),
        acceptance_criterion_ids=_string_tuple(value["acceptance_criterion_ids"]),
        timing_claim_id=_optional_text(value["timing_claim_id"]),
        timing_classification=_optional_enum(
            TimingClassification, value["timing_classification"]
        ),
    )


def _risk_from_payload(value: object) -> RiskItemV2:
    _object(
        value,
        {
            "risk_id",
            "condition_claim_id",
            "impact_claim_ids",
            "mitigation_claim_ids",
            "trigger_claim_ids",
        },
    )
    return RiskItemV2(
        risk_id=_text(value["risk_id"]),
        condition_claim_id=_text(value["condition_claim_id"]),
        impact_claim_ids=_string_tuple(value["impact_claim_ids"]),
        mitigation_claim_ids=_string_tuple(value["mitigation_claim_ids"]),
        trigger_claim_ids=_string_tuple(value["trigger_claim_ids"]),
    )


def _criterion_from_payload(value: object) -> AcceptanceCriterionV2:
    _object(value, {"criterion_id", "claim_id", "classification"})
    return AcceptanceCriterionV2(
        criterion_id=_text(value["criterion_id"]),
        claim_id=_text(value["claim_id"]),
        classification=_enum(AcceptanceClassification, value["classification"]),
    )


def _milestone_from_payload(value: object) -> MilestoneV2:
    _object(
        value,
        {
            "milestone_id",
            "name",
            "related_phase_ids",
            "outcome_claim_ids",
            "timing_claim_id",
            "timing_classification",
        },
    )
    return MilestoneV2(
        milestone_id=_text(value["milestone_id"]),
        name=_text(value["name"]),
        related_phase_ids=_string_tuple(value["related_phase_ids"]),
        outcome_claim_ids=_string_tuple(value["outcome_claim_ids"]),
        timing_claim_id=_optional_text(value["timing_claim_id"]),
        timing_classification=_optional_enum(
            TimingClassification, value["timing_classification"]
        ),
    )


def _question_from_payload(value: object) -> OpenQuestionV2:
    _object(
        value,
        {
            "question_id",
            "requirement_field",
            "requirement_status",
            "unresolved_claim_id",
        },
    )
    return OpenQuestionV2(
        question_id=_text(value["question_id"]),
        requirement_field=_enum(RequirementDimension, value["requirement_field"]),
        requirement_status=_enum(RequirementStatus, value["requirement_status"]),
        unresolved_claim_id=_text(value["unresolved_claim_id"]),
    )


def _scope_from_payload(value: object) -> ScopeItemV2:
    _object(value, {"scope_id", "claim_id", "classification"})
    return ScopeItemV2(
        scope_id=_text(value["scope_id"]),
        claim_id=_text(value["claim_id"]),
        classification=_enum(AcceptanceClassification, value["classification"]),
    )


def _statement_to_payload(statement: SolutionStatement) -> dict:
    if not isinstance(statement, SolutionStatement):
        _invalid()
    return {
        "type": statement.type.value,
        "text": statement.text,
        "citations": list(statement.citations),
    }


def _v1_statements(value: object, *, maximum: int) -> tuple[SolutionStatement, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        _invalid()
    result = []
    for item in value:
        _object(item, {"type", "text", "citations"})
        kind = _enum(SolutionStatementType, item["type"])
        citations = _string_tuple(item["citations"])
        if (
            len(set(citations)) != len(citations)
            or any(re.fullmatch(r"S[1-9][0-9]*", label) is None for label in citations)
        ):
            _invalid()
        if kind is SolutionStatementType.CUSTOMER_FACT and citations:
            _invalid()
        if kind in {
            SolutionStatementType.ENTERPRISE_FACT,
            SolutionStatementType.PROPOSAL,
        } and not citations:
            _invalid()
        result.append(SolutionStatement(kind, _text(item["text"]), citations))
    return tuple(result)


def _object(value: object, expected_keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected_keys:
        _invalid()


def _list(value: object) -> list:
    if not isinstance(value, list):
        _invalid()
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    items = _list(value)
    if any(not isinstance(item, str) for item in items):
        _invalid()
    return tuple(items)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _invalid()
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _enum(enum_type, value: object):
    if not isinstance(value, str) or value not in enum_type._value2member_map_:
        _invalid()
    return enum_type(value)


def _optional_enum(enum_type, value: object):
    return None if value is None else _enum(enum_type, value)


def _enum_value(value) -> str | None:
    return None if value is None else value.value


def _invalid() -> NoReturn:
    raise SolutionPayloadError()
