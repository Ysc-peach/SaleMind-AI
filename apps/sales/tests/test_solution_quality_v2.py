"""Evaluation-only quality benchmark for newly assembled Solution V2 drafts.

This rubric is deliberately test-only.  Runtime validation continues to own
safety and schema integrity; the benchmark measures whether a valid draft is
also useful as an executable presales solution.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from apps.knowledge.models import EnterpriseGroundingFactStatus
from apps.llm.base import LLMMessage
from apps.sales.demo_fixtures import (
    DEMO_KNOWLEDGE,
    DEMO_SCENARIOS,
    DemoSolutionProposalProvider,
)
from apps.sales.services.requirement_analysis import (
    ClarifyingQuestion,
    OpportunityRequirementAnalysis,
    RequirementDimension,
    RequirementDimensions,
    RequirementFieldAnalysis,
    RequirementStatus,
)
from apps.sales.services.solution_admission import (
    EnterpriseAdmissionDecision,
    EnterpriseClaimProvenance,
    GroundingAdmission,
)
from apps.sales.services.solution_prompt_v2 import (
    AtomicSolutionProposalSetV2,
    SolutionV2Section,
    parse_atomic_solution_v2_proposals,
)
from apps.sales.services.solution_schema import (
    AtomicSolutionClaim,
    AtomicSolutionClaimSet,
    SolutionSectionKey,
    SolutionStatementType,
)
from apps.sales.services.solution_schema_v2 import (
    SolutionClaimTypeV2,
    V2AssemblyResult,
    assemble_solution_draft_v2,
    build_v2_deterministic_items,
)


_ENTERPRISE_CAPABILITY_BASIS_ID = "enterprise_capability_basis"
_ENTERPRISE_CAPABILITY_GAPS_ID = "enterprise_capability_gaps"
_PRECISE_COMMITMENT = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:周|天|人天|节点|QPS|TPS|%|％|秒|分钟|万元|元)|SLA)",
    flags=re.IGNORECASE,
)
_TRADEOFF_TERMS = ("取舍", "代价", "权衡", "重新评估", "但会", "相较")
_OBSERVABLE_ACCEPTANCE_TERMS = ("确认", "验证", "能够", "无法", "展示", "返回")
_VAGUE_ACCEPTANCE_TERMS = ("满足客户需求", "系统运行正常")

_SUBJECT_SECTIONS = {
    "enterprise_knowledge_query": SolutionSectionKey.OVERALL_APPROACH,
    "scanned_pdf_ocr": SolutionSectionKey.OVERALL_APPROACH,
    "contract_generation": SolutionSectionKey.OVERALL_APPROACH,
    "oa_integration": SolutionSectionKey.INTEGRATION,
    "sso_integration": SolutionSectionKey.INTEGRATION,
    "csv_bulk_export": SolutionSectionKey.INTEGRATION,
    "jwt_authentication": SolutionSectionKey.DATA_SECURITY,
    "private_deployment": SolutionSectionKey.DEPLOYMENT,
    "intranet_data_residency": SolutionSectionKey.DATA_SECURITY,
    "postgresql": SolutionSectionKey.DEPLOYMENT,
    "pgvector": SolutionSectionKey.DEPLOYMENT,
    "kubernetes_deployment": SolutionSectionKey.DEPLOYMENT,
    "server_compatibility": SolutionSectionKey.DEPLOYMENT,
}


@dataclass(frozen=True, slots=True)
class QualityEvaluation:
    hard_gates: dict[str, bool]
    section_scores: dict[str, int]
    fact_repeat_count: int
    summary_proposal_ratio: float
    proposed_solution_proposal_ratio: float

    @property
    def score(self) -> int:
        return sum(self.section_scores.values())

    @property
    def passed(self) -> bool:
        return (
            all(self.hard_gates.values())
            and self.score >= 80
            and self.section_scores["architecture"] >= 12
            and self.section_scores["implementation_plan"] >= 9
            and self.section_scores["acceptance_criteria"] >= 6
        )


def _known(value: str) -> RequirementFieldAnalysis:
    return RequirementFieldAnalysis(
        status=RequirementStatus.KNOWN,
        value=value,
        evidence=value,
    )


def _approved_demo_analysis() -> OpportunityRequirementAnalysis:
    scenario = next(
        item for item in DEMO_SCENARIOS if item.key == "enterprise_service_approved"
    )
    return OpportunityRequirementAnalysis(
        summary=(
            f"{scenario.customer_name}计划{scenario.business_goal}；"
            "实施时间和预算仍待客户确认。"
        ),
        requirements=RequirementDimensions(
            business_goal=_known(scenario.business_goal),
            use_scenario=_known(scenario.use_scenario),
            user_scale=_known(scenario.user_scale),
            deployment_requirement=_known(scenario.deployment_requirement),
            data_security_requirement=_known(scenario.data_security_requirement),
            existing_environment=_known(scenario.existing_environment),
            integration_requirement=_known(scenario.integration_requirement),
            timeline=RequirementFieldAnalysis(RequirementStatus.UNKNOWN, None, None),
            budget=RequirementFieldAnalysis(RequirementStatus.UNKNOWN, None, None),
            technical_constraints=_known(scenario.technical_constraints),
        ),
        conflicts=(),
        clarifying_questions=(
            ClarifyingQuestion(
                RequirementDimension.TIMELINE,
                "客户期望何时完成首批业务上线？",
            ),
            ClarifyingQuestion(
                RequirementDimension.BUDGET,
                "本项目可用于软件与实施的预算范围是多少？",
            ),
        ),
    )


def _approved_demo_admission() -> GroundingAdmission:
    claims = []
    decisions = []
    provenance = []
    fact_id = 100
    for source_index, fixture in enumerate(DEMO_KNOWLEDGE, start=1):
        citation = f"S{source_index}"
        for subject_key, statement in fixture.facts:
            claim = AtomicSolutionClaim(
                section=_SUBJECT_SECTIONS[subject_key],
                statement_type=SolutionStatementType.ENTERPRISE_FACT,
                text=statement,
                citations=(citation,),
            )
            claims.append(claim)
            decisions.append(
                EnterpriseAdmissionDecision(
                    subject_key=subject_key,
                    status=EnterpriseGroundingFactStatus.CONFIRMED_SUPPORTED,
                    enterprise_fact_ids=(fact_id,),
                    needs_attention=False,
                )
            )
            provenance.append(
                EnterpriseClaimProvenance(
                    claim=claim,
                    subject_key=subject_key,
                    fact_id=fact_id,
                )
            )
            fact_id += 1
    return GroundingAdmission(
        claims=AtomicSolutionClaimSet(tuple(claims)),
        enterprise_decisions=tuple(decisions),
        enterprise_provenance=tuple(provenance),
        allowed_proposal_source_labels=("S1", "S2", "S3"),
    )


def _approved_demo_proposals():
    scenario = next(
        item for item in DEMO_SCENARIOS if item.key == "enterprise_service_approved"
    )
    sources = "\n".join(
        f'<source id="S{index}">\n文档：{fixture.title}\n{fixture.content}\n</source>'
        for index, fixture in enumerate(DEMO_KNOWLEDGE, start=1)
    )
    messages: list[LLMMessage] = [
        {
            "role": "user",
            "content": (
                "<allowed_enterprise_capabilities>\n"
                f"{sources}\n"
                "</allowed_enterprise_capabilities>"
            ),
        }
    ]
    generated = DemoSolutionProposalProvider(scenario).generate(messages)
    return parse_atomic_solution_v2_proposals(
        generated.content,
        allowed_source_labels=("S1", "S2", "S3"),
    )


def approved_demo_assembly() -> V2AssemblyResult:
    deterministic = build_v2_deterministic_items(
        _approved_demo_analysis(),
        _approved_demo_admission(),
    )
    return assemble_solution_draft_v2(deterministic, _approved_demo_proposals())


def _claim_ids_by_section(draft) -> dict[str, tuple[str, ...]]:
    proposed = list(draft.proposed_solution.overview_claim_ids)
    for group in draft.proposed_solution.capability_groups:
        if group.group_id != _ENTERPRISE_CAPABILITY_BASIS_ID:
            proposed.extend(group.claim_ids)
    architecture = list(draft.architecture.overview_claim_ids)
    for component in draft.architecture.components:
        architecture.extend(component.responsibility_claim_ids)
        architecture.extend(component.rationale_claim_ids)
        architecture.extend(component.interface_claim_ids)
    deployment = [
        claim_id
        for block in draft.deployment_and_integration
        for claim_id in block.claim_ids
    ]
    implementation = []
    for phase in draft.implementation_plan.phases:
        implementation.extend(phase.objective_claim_ids)
        implementation.extend(phase.task_claim_ids)
        implementation.extend(phase.deliverable_claim_ids)
        if phase.timing_claim_id:
            implementation.append(phase.timing_claim_id)
    risks = []
    for risk in draft.risks:
        risks.append(risk.condition_claim_id)
        risks.extend(risk.impact_claim_ids)
        risks.extend(risk.mitigation_claim_ids)
        risks.extend(risk.trigger_claim_ids)
    return {
        "executive_summary": draft.executive_summary_claim_ids,
        "proposed_solution": tuple(proposed),
        "architecture": tuple(architecture),
        "deployment_and_integration": tuple(deployment),
        "implementation_plan": tuple(implementation),
        "risks": tuple(risks),
        "acceptance_criteria": tuple(
            item.claim_id for item in draft.acceptance_criteria
        ),
        "milestones": tuple(
            claim_id
            for milestone in draft.milestones
            for claim_id in milestone.outcome_claim_ids
        ),
        "assumptions": draft.assumption_claim_ids,
        "open_questions": tuple(
            item.unresolved_claim_id for item in draft.open_questions
        ),
        "out_of_scope": tuple(item.claim_id for item in draft.out_of_scope),
    }


def evaluate_solution_quality(assembly: V2AssemblyResult) -> QualityEvaluation:
    draft = assembly.draft
    claims = {claim.claim_id: claim for claim in draft.claims}
    sections = _claim_ids_by_section(draft)
    scenario = next(
        item for item in DEMO_SCENARIOS if item.key == "enterprise_service_approved"
    )
    expected_customer_facts = {
        f"业务目标：{scenario.business_goal}。",
        f"使用场景：{scenario.use_scenario}。",
        f"使用人数：{scenario.user_scale}。",
        f"部署要求：{scenario.deployment_requirement}。",
        f"数据安全要求：{scenario.data_security_requirement}。",
        f"现有环境：{scenario.existing_environment}。",
        f"集成要求：{scenario.integration_requirement}。",
        f"技术约束：{scenario.technical_constraints}。",
    }
    expected_enterprise_facts = {
        statement for fixture in DEMO_KNOWLEDGE for _, statement in fixture.facts
    }
    customer_facts = {
        claim.text
        for claim in draft.claims
        if claim.statement_type is SolutionClaimTypeV2.CUSTOMER_FACT
    }
    enterprise_facts = {
        claim.text
        for claim in draft.claims
        if claim.statement_type is SolutionClaimTypeV2.ENTERPRISE_FACT
    }
    proposal_claims = [
        claim
        for claim in draft.claims
        if claim.statement_type is SolutionClaimTypeV2.PROPOSAL
    ]
    expected_fact_bindings = {
        (claim.claim_id, citation)
        for claim in draft.claims
        if claim.statement_type is SolutionClaimTypeV2.ENTERPRISE_FACT
        for citation in claim.citations
    }
    actual_fact_bindings = {
        (binding.claim_id, binding.citation_label)
        for binding in assembly.provenance_bindings
        if claims[binding.claim_id].statement_type
        is SolutionClaimTypeV2.ENTERPRISE_FACT
    }
    hard_gates = {
        "facts_not_fabricated": (
            customer_facts == expected_customer_facts
            and enterprise_facts == expected_enterprise_facts
        ),
        "no_unsupported_precise_commitment": not any(
            _PRECISE_COMMITMENT.search(claim.text) for claim in proposal_claims
        ),
        "fact_provenance_binding_exact": actual_fact_bindings
        == expected_fact_bindings,
        "proposals_do_not_conflict": not any(
            (
                "公网" in claim.text
                and not any(word in claim.text for word in ("不", "不得", "禁止", "避免"))
            )
            or "Oracle" in claim.text
            for claim in proposal_claims
        ),
    }

    proposal_ids = {
        claim.claim_id
        for claim in proposal_claims
    }
    proposed_ids = sections["proposed_solution"]
    summary_ids = sections["executive_summary"]
    summary_ratio = (
        sum(claim_id in proposal_ids for claim_id in summary_ids) / len(summary_ids)
        if summary_ids
        else 0.0
    )
    proposed_ratio = (
        sum(claim_id in proposal_ids for claim_id in proposed_ids) / len(proposed_ids)
        if proposed_ids
        else 0.0
    )

    fact_ids = {
        claim.claim_id
        for claim in draft.claims
        if claim.statement_type
        in {SolutionClaimTypeV2.CUSTOMER_FACT, SolutionClaimTypeV2.ENTERPRISE_FACT}
    }
    referenced_outside_canonical = {
        claim_id
        for claim_ids in sections.values()
        for claim_id in claim_ids
        if claim_id in fact_ids
    }
    fact_repeat_count = len(referenced_outside_canonical)

    proposed_claim_values = [claims[item] for item in proposed_ids]
    component_count = len(draft.architecture.components)
    complete_component_fields = {
        "responsibility": all(
            item.responsibility_claim_ids for item in draft.architecture.components
        ),
        "rationale": all(item.rationale_claim_ids for item in draft.architecture.components),
        "interface": all(item.interface_claim_ids for item in draft.architecture.components),
    }
    architecture_score = (
        (3 if draft.architecture.overview_claim_ids else 0)
        + (5 if component_count >= 5 else 3 if component_count >= 3 else 2 if component_count >= 2 else 1 if component_count else 0)
        + (3 if component_count >= 3 and complete_component_fields["responsibility"] else 1 if complete_component_fields["responsibility"] and component_count else 0)
        + (3 if component_count >= 3 and complete_component_fields["rationale"] else 1 if complete_component_fields["rationale"] and component_count else 0)
        + (3 if component_count >= 3 and complete_component_fields["interface"] else 1 if complete_component_fields["interface"] and component_count else 0)
        + (3 if any(item.dependency_component_ids for item in draft.architecture.components) else 0)
    )
    topic_names = {block.topic.value for block in draft.deployment_and_integration}
    deployment_claims = [claims[item] for item in sections["deployment_and_integration"]]
    deployment_score = (
        (4 if {"deployment", "integration"} <= topic_names else 2 if topic_names else 0)
        + min(4, sum(item.statement_type is SolutionClaimTypeV2.PROPOSAL for item in deployment_claims))
        + (3 if any("受控网络" in item.text or "内网" in item.text for item in deployment_claims) else 0)
        + (2 if any("如果" in item.text or "若" in item.text for item in deployment_claims) else 0)
        + (2 if any("应用" in item.text and "数据" in item.text and "分" in item.text for item in deployment_claims) else 0)
    )
    phases = draft.implementation_plan.phases
    implementation_score = (
        (3 if len(phases) >= 4 else 1 if len(phases) >= 2 else 0)
        + (3 if phases and all(item.objective_claim_ids for item in phases) else 0)
        + (3 if phases and all(item.task_claim_ids for item in phases) else 0)
        + (3 if phases and all(item.deliverable_claim_ids for item in phases) else 0)
        + (2 if any(item.dependency_phase_ids for item in phases) else 0)
        + (1 if any(item.acceptance_criterion_ids for item in phases) else 0)
    )
    risks = draft.risks
    risk_score = (
        (2 if len(risks) >= 2 else len(risks))
        + (2 if risks and all(item.condition_claim_id for item in risks) else 0)
        + (2 if risks and all(item.impact_claim_ids for item in risks) else 0)
        + (2 if risks and all(item.mitigation_claim_ids for item in risks) else 0)
        + (2 if risks and all(item.trigger_claim_ids for item in risks) else 0)
    )
    criteria = [claims[item.claim_id] for item in draft.acceptance_criteria]
    acceptance_score = (
        min(3, len(criteria))
        + min(4, sum(any(term in item.text for term in _OBSERVABLE_ACCEPTANCE_TERMS) for item in criteria) * 2)
        + (2 if criteria and not any(any(term in item.text for term in _VAGUE_ACCEPTANCE_TERMS) for item in criteria) else 0)
        + (1 if any(item.related_requirement_fields for item in criteria) or any(item.acceptance_criterion_ids for item in phases) else 0)
    )
    proposal_score = (
        (4 if sum(item.statement_type is SolutionClaimTypeV2.PROPOSAL for item in proposed_claim_values) >= 2 else 0)
        + (4 if any(item.responsibility_claim_ids for item in draft.architecture.components) else 0)
        + (4 if any(item.rationale_claim_ids for item in draft.architecture.components) else 0)
        + (4 if any(item.related_requirement_fields for item in proposal_claims) else 0)
        + (4 if any(any(term in item.text for term in _TRADEOFF_TERMS) for item in proposal_claims) else 0)
    )
    repetition_score = 5 if fact_repeat_count == 0 else 4 if fact_repeat_count == 1 else 2 if fact_repeat_count <= 3 else 0
    key_sections = (
        "proposed_solution",
        "architecture",
        "deployment_and_integration",
        "implementation_plan",
        "risks",
        "acceptance_criteria",
        "milestones",
        "out_of_scope",
    )
    consistency_score = (
        (2 if all(sections[name] for name in key_sections) else 0)
        + (1 if fact_repeat_count <= 1 else 0)
        + (2 if summary_ratio > 0.5 else 0)
    )
    return QualityEvaluation(
        hard_gates=hard_gates,
        section_scores={
            "recommendation_rationale_constraint_tradeoff": proposal_score,
            "architecture": architecture_score,
            "deployment_integration": deployment_score,
            "implementation_plan": implementation_score,
            "risks_mitigation": risk_score,
            "acceptance_criteria": acceptance_score,
            "fact_repetition_control": repetition_score,
            "section_consistency_readability": consistency_score,
        },
        fact_repeat_count=fact_repeat_count,
        summary_proposal_ratio=summary_ratio,
        proposed_solution_proposal_ratio=proposed_ratio,
    )


def test_current_approved_demo_quality_is_a_safe_but_low_value_baseline():
    evaluation = evaluate_solution_quality(approved_demo_assembly())

    assert evaluation.hard_gates == {
        "facts_not_fabricated": True,
        "no_unsupported_precise_commitment": True,
        "fact_provenance_binding_exact": True,
        "proposals_do_not_conflict": True,
    }
    assert evaluation.score < 80
    assert evaluation.passed is False


def test_assembler_makes_summary_proposal_led_and_separates_capability_basis():
    assembly = approved_demo_assembly()
    draft = assembly.draft
    claims = {claim.claim_id: claim for claim in draft.claims}
    evaluation = evaluate_solution_quality(assembly)

    assert evaluation.summary_proposal_ratio > 0.5
    assert evaluation.proposed_solution_proposal_ratio == 1.0
    assert evaluation.fact_repeat_count <= 1
    capability_basis = next(
        group
        for group in draft.proposed_solution.capability_groups
        if group.group_id == _ENTERPRISE_CAPABILITY_BASIS_ID
    )
    assert capability_basis.title == "企业能力依据"
    assert capability_basis.claim_ids
    assert all(
        claims[claim_id].statement_type is SolutionClaimTypeV2.ENTERPRISE_FACT
        for claim_id in capability_basis.claim_ids
    )


def test_assembler_preserves_every_atomic_claim_and_provenance_binding():
    assembly = approved_demo_assembly()
    draft = assembly.draft
    claim_ids = {claim.claim_id for claim in draft.claims}

    assert len(claim_ids) == len(draft.claims) == 53
    assert len(assembly.provenance_bindings) > 13
    assert all(binding.claim_id in claim_ids for binding in assembly.provenance_bindings)
    assert {
        claim.statement_type for claim in draft.claims
    } == set(SolutionClaimTypeV2)


def test_assembler_keeps_unconfirmed_enterprise_capability_out_of_proposal_body():
    admission = _approved_demo_admission()
    admission = replace(
        admission,
        enterprise_decisions=admission.enterprise_decisions
        + (
            EnterpriseAdmissionDecision(
                subject_key="oracle_compatibility",
                status=EnterpriseGroundingFactStatus.UNCONFIRMED,
                enterprise_fact_ids=(),
                needs_attention=False,
            ),
        ),
    )
    deterministic = build_v2_deterministic_items(
        _approved_demo_analysis(),
        admission,
    )

    draft = assemble_solution_draft_v2(
        deterministic,
        _approved_demo_proposals(),
    ).draft

    gaps = next(
        group
        for group in draft.proposed_solution.capability_groups
        if group.group_id == _ENTERPRISE_CAPABILITY_GAPS_ID
    )
    claims = {claim.claim_id: claim for claim in draft.claims}
    assert gaps.title == "企业能力待确认"
    assert gaps.claim_ids
    assert all(
        claims[claim_id].statement_type is SolutionClaimTypeV2.UNRESOLVED
        for claim_id in gaps.claim_ids
    )
    assert not set(gaps.claim_ids) & set(draft.proposed_solution.overview_claim_ids)


def test_summary_priority_comes_from_solution_structure_not_model_array_order():
    proposals = _approved_demo_proposals()
    reordered = AtomicSolutionProposalSetV2(tuple(reversed(proposals.proposals)))

    draft = assemble_solution_draft_v2(
        build_v2_deterministic_items(
            _approved_demo_analysis(),
            _approved_demo_admission(),
        ),
        reordered,
    ).draft

    core_texts = {
        proposal.text
        for proposal in proposals.proposals
        if proposal.placement.section
        in {SolutionV2Section.PROPOSED_SOLUTION, SolutionV2Section.ARCHITECTURE}
    }
    summary_proposals = [
        claim.text
        for claim_id in draft.executive_summary_claim_ids
        if (claim := next(item for item in draft.claims if item.claim_id == claim_id)).statement_type
        is SolutionClaimTypeV2.PROPOSAL
    ]
    assert summary_proposals
    assert set(summary_proposals) <= core_texts


def test_stage_two_improves_assembly_without_pretending_quality_is_complete():
    evaluation = evaluate_solution_quality(approved_demo_assembly())

    assert evaluation.score < 80
    assert evaluation.passed is False


def test_generation_ir_round_trip_preserves_proposal_requirement_linkage():
    payload = {
        "proposals": [
            {
                "placement": {
                    "section": "architecture",
                    "container_kind": "architecture_component",
                    "container_key": "identity_boundary",
                    "field": "rationale",
                },
                "text": "建议将身份校验集中在受控入口边界。",
                "citations": ["S1"],
                "related_requirement_fields": [
                    "integration_requirement",
                    "data_security_requirement",
                ],
            }
        ]
    }
    proposals = parse_atomic_solution_v2_proposals(
        json.dumps(payload, ensure_ascii=False),
        allowed_source_labels=("S1", "S2", "S3"),
    )

    draft = assemble_solution_draft_v2(
        build_v2_deterministic_items(
            _approved_demo_analysis(),
            _approved_demo_admission(),
        ),
        proposals,
    ).draft
    proposal_claim = next(
        claim
        for claim in draft.claims
        if claim.statement_type is SolutionClaimTypeV2.PROPOSAL
    )

    assert proposal_claim.related_requirement_fields == (
        RequirementDimension.INTEGRATION_REQUIREMENT,
        RequirementDimension.DATA_SECURITY_REQUIREMENT,
    )
