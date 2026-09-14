"""Strict contracts for the structured Solution Domain V2."""

from dataclasses import FrozenInstanceError, replace

import pytest

from apps.sales.services.requirement_analysis import (
    RequirementDimension,
    RequirementStatus,
)
from apps.sales.services.solution_errors import SolutionDraftError
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


def claim(
    claim_id: str,
    claim_type: SolutionClaimTypeV2,
    text: str,
    *,
    citations: tuple[str, ...] = (),
    fields: tuple[RequirementDimension, ...] = (),
) -> SolutionAtomicClaimV2:
    return SolutionAtomicClaimV2(
        claim_id=claim_id,
        statement_type=claim_type,
        text=text,
        citations=citations,
        related_requirement_fields=fields,
    )


def valid_draft() -> SolutionDraftV2:
    claims = (
        claim("C0001", SolutionClaimTypeV2.CUSTOMER_FACT, "客户需要企业知识查询。"),
        claim(
            "C0002",
            SolutionClaimTypeV2.ENTERPRISE_FACT,
            "系统支持私有化部署。",
            citations=("S1",),
        ),
        claim(
            "C0003",
            SolutionClaimTypeV2.PROPOSAL,
            "建议采用分层服务架构。",
            citations=("S1",),
        ),
        claim(
            "C0004",
            SolutionClaimTypeV2.ASSUMPTION,
            "实施周期需在客户确认窗口后安排。",
            fields=(RequirementDimension.TIMELINE,),
        ),
        claim(
            "C0005",
            SolutionClaimTypeV2.UNRESOLVED,
            "具体上线日期待客户确认。",
            fields=(RequirementDimension.TIMELINE,),
        ),
    )
    criterion = AcceptanceCriterionV2(
        criterion_id="AC01",
        claim_id="C0003",
        classification=AcceptanceClassification.PROPOSED,
    )
    phase = ImplementationPhaseV2(
        phase_id="phase_discovery",
        name="确认阶段",
        objective_claim_ids=("C0005",),
        task_claim_ids=("C0003",),
        owner_roles=(OwnerRoleV2.JOINT,),
        deliverable_claim_ids=("C0003",),
        dependency_phase_ids=(),
        acceptance_criterion_ids=("AC01",),
        timing_claim_id="C0005",
        timing_classification=TimingClassification.UNRESOLVED,
    )
    return SolutionDraftV2(
        title="企业知识查询技术方案",
        claims=claims,
        executive_summary_claim_ids=("C0001", "C0003", "C0005"),
        customer_context=CustomerContextV2(
            confirmed_claim_ids=("C0001",),
            unresolved_claim_ids=("C0005",),
            requirement_fields=(
                CustomerRequirementRefV2(
                    field=RequirementDimension.BUSINESS_GOAL,
                    status=RequirementStatus.KNOWN,
                    claim_ids=("C0001",),
                ),
                CustomerRequirementRefV2(
                    field=RequirementDimension.TIMELINE,
                    status=RequirementStatus.UNKNOWN,
                    claim_ids=("C0005",),
                ),
            ),
        ),
        proposed_solution=ProposedSolutionV2(
            overview_claim_ids=("C0002", "C0003"),
            capability_groups=(
                CapabilityGroupV2(
                    group_id="private_deployment",
                    title="私有化部署",
                    claim_ids=("C0002", "C0003"),
                ),
            ),
        ),
        architecture=ArchitectureV2(
            overview_claim_ids=("C0003",),
            components=(
                ArchitectureComponentV2(
                    component_id="knowledge_service",
                    name="知识服务层",
                    responsibility_claim_ids=("C0003",),
                    rationale_claim_ids=("C0002",),
                    dependency_component_ids=(),
                    interface_claim_ids=(),
                ),
            ),
        ),
        deployment_and_integration=(
            SolutionTopicBlockV2(
                block_id="private_deployment",
                topic=SolutionTopicV2.DEPLOYMENT,
                title="部署方式",
                claim_ids=("C0002",),
            ),
        ),
        implementation_plan=ImplementationPlanV2(phases=(phase,)),
        risks=(
            RiskItemV2(
                risk_id="R01",
                condition_claim_id="C0005",
                impact_claim_ids=(),
                mitigation_claim_ids=("C0003",),
                trigger_claim_ids=(),
            ),
        ),
        acceptance_criteria=(criterion,),
        milestones=(
            MilestoneV2(
                milestone_id="M01",
                name="范围确认",
                related_phase_ids=("phase_discovery",),
                outcome_claim_ids=("C0003",),
                timing_claim_id="C0005",
                timing_classification=TimingClassification.UNRESOLVED,
            ),
        ),
        assumption_claim_ids=("C0004",),
        open_questions=(
            OpenQuestionV2(
                question_id="Q01",
                requirement_field=RequirementDimension.TIMELINE,
                requirement_status=RequirementStatus.UNKNOWN,
                unresolved_claim_id="C0005",
            ),
        ),
        out_of_scope=(
            ScopeItemV2(
                scope_id="OS01",
                claim_id="C0005",
                classification=AcceptanceClassification.UNRESOLVED,
            ),
        ),
    )


def test_v2_claim_types_are_closed_and_claims_are_frozen():
    assert set(SolutionClaimTypeV2) == {
        SolutionClaimTypeV2.CUSTOMER_FACT,
        SolutionClaimTypeV2.ENTERPRISE_FACT,
        SolutionClaimTypeV2.PROPOSAL,
        SolutionClaimTypeV2.ASSUMPTION,
        SolutionClaimTypeV2.UNRESOLVED,
    }
    value = valid_draft().claims[0]
    with pytest.raises(FrozenInstanceError):
        value.text = "changed"


@pytest.mark.parametrize(
    "invalid_claim",
    [
        claim("not-stable", SolutionClaimTypeV2.CUSTOMER_FACT, "客户需要查询。"),
        claim(
            "C0001",
            SolutionClaimTypeV2.CUSTOMER_FACT,
            "客户需要查询。",
            citations=("S1",),
        ),
        claim("C0001", SolutionClaimTypeV2.ENTERPRISE_FACT, "系统支持部署。"),
        claim("C0001", SolutionClaimTypeV2.PROPOSAL, "建议部署。"),
        claim(
            "C0001",
            SolutionClaimTypeV2.UNRESOLVED,
            "协议待确认。",
            citations=("S1",),
        ),
        claim("C0001", SolutionClaimTypeV2.ASSUMPTION, "环境条件待确认。"),
        claim(
            "C0001",
            SolutionClaimTypeV2.PROPOSAL,
            "建议使用来源 S1 的能力。",
            citations=("S1",),
        ),
    ],
)
def test_invalid_atomic_claim_authority_is_rejected(invalid_claim):
    draft = replace(valid_draft(), claims=(invalid_claim,) + valid_draft().claims[1:])
    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(draft)


def test_duplicate_claim_ids_are_rejected_even_when_text_differs():
    draft = valid_draft()
    duplicate = replace(draft.claims[-1], claim_id="C0001")
    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(replace(draft, claims=draft.claims[:-1] + (duplicate,)))


def test_same_text_claims_keep_distinct_stable_ids():
    draft = valid_draft()
    duplicate_text = replace(draft.claims[2], claim_id="C0006", text=draft.claims[1].text)
    changed = replace(
        draft,
        claims=draft.claims + (duplicate_text,),
        proposed_solution=replace(
            draft.proposed_solution,
            overview_claim_ids=draft.proposed_solution.overview_claim_ids + ("C0006",),
        ),
    )
    validate_solution_draft_v2(changed)
    assert changed.claims[1].claim_id != changed.claims[-1].claim_id


def test_dangling_claim_reference_is_rejected():
    draft = valid_draft()
    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(
            replace(draft, executive_summary_claim_ids=("C9999",))
        )


def test_structural_label_cannot_hide_a_business_sentence():
    draft = valid_draft()
    component = replace(
        draft.architecture.components[0],
        name="数据库层。采用 PostgreSQL 双节点高可用部署。",
    )
    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(
            replace(draft, architecture=replace(draft.architecture, components=(component,)))
        )


def test_component_dependency_must_exist_and_cannot_reference_self():
    draft = valid_draft()
    component = draft.architecture.components[0]
    for dependency in ("missing_component", component.component_id):
        with pytest.raises(SolutionDraftError):
            validate_solution_draft_v2(
                replace(
                    draft,
                    architecture=replace(
                        draft.architecture,
                        components=(
                            replace(component, dependency_component_ids=(dependency,)),
                        ),
                    ),
                )
            )


def test_component_dependency_graph_must_be_acyclic():
    draft = valid_draft()
    first = replace(
        draft.architecture.components[0],
        dependency_component_ids=("retrieval_service",),
    )
    second = replace(
        first,
        component_id="retrieval_service",
        name="检索服务层",
        dependency_component_ids=(first.component_id,),
    )

    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(
            replace(
                draft,
                architecture=replace(
                    draft.architecture,
                    components=(first, second),
                ),
            )
        )


def test_phase_dependencies_must_reference_an_earlier_phase():
    draft = valid_draft()
    first = draft.implementation_plan.phases[0]
    second = replace(first, phase_id="phase_delivery", dependency_phase_ids=(first.phase_id,))
    validate_solution_draft_v2(
        replace(draft, implementation_plan=ImplementationPlanV2((first, second)))
    )

    forward = replace(first, dependency_phase_ids=(second.phase_id,))
    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(
            replace(draft, implementation_plan=ImplementationPlanV2((forward, second)))
        )


@pytest.mark.parametrize(
    ("classification", "claim_id"),
    [
        (AcceptanceClassification.CUSTOMER_CONFIRMED, "C0003"),
        (AcceptanceClassification.PROPOSED, "C0001"),
        (AcceptanceClassification.UNRESOLVED, "C0002"),
    ],
)
def test_acceptance_classification_must_match_claim_authority(classification, claim_id):
    draft = valid_draft()
    invalid = replace(
        draft.acceptance_criteria[0],
        classification=classification,
        claim_id=claim_id,
    )
    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(replace(draft, acceptance_criteria=(invalid,)))


def test_open_question_is_only_a_reference_to_deterministic_unresolved_claim():
    draft = valid_draft()
    invalid = replace(draft.open_questions[0], unresolved_claim_id="C0003")
    with pytest.raises(SolutionDraftError):
        validate_solution_draft_v2(replace(draft, open_questions=(invalid,)))


def test_valid_v2_draft_has_no_nested_free_form_solution_paragraph_fields():
    draft = valid_draft()
    validate_solution_draft_v2(draft)
    nested = (
        draft.architecture.components[0],
        draft.implementation_plan.phases[0],
        draft.risks[0],
        draft.acceptance_criteria[0],
        draft.milestones[0],
        draft.open_questions[0],
        draft.out_of_scope[0],
    )
    assert all("text" not in value.__dataclass_fields__ for value in nested)
    assert all("description" not in value.__dataclass_fields__ for value in nested)
