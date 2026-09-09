"""Deterministic and probabilistic assembly boundaries for Solution V2."""

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
from apps.sales.services.solution_schema import (
    AtomicSolutionClaim,
    AtomicSolutionClaimSet,
    SolutionSectionKey,
    SolutionStatementType,
)


def field(status, value=None):
    return RequirementFieldAnalysis(status=status, value=value, evidence=value)


def analysis_fixture():
    return OpportunityRequirementAnalysis(
        summary="客户需要企业知识查询，时间与集成协议待确认。",
        requirements=RequirementDimensions(
            business_goal=field(RequirementStatus.KNOWN, "企业知识查询"),
            use_scenario=field(RequirementStatus.KNOWN, "员工查询企业资料"),
            user_scale=field(RequirementStatus.KNOWN, "约 300 人"),
            deployment_requirement=field(RequirementStatus.KNOWN, "私有化部署"),
            data_security_requirement=field(RequirementStatus.KNOWN, "数据留在内网"),
            existing_environment=field(RequirementStatus.KNOWN, "Linux"),
            integration_requirement=field(RequirementStatus.UNCLEAR),
            timeline=field(RequirementStatus.UNKNOWN),
            budget=field(RequirementStatus.CONFLICT),
            technical_constraints=field(RequirementStatus.KNOWN, "PostgreSQL"),
        ),
        conflicts=(),
        clarifying_questions=(
            ClarifyingQuestion(
                RequirementDimension.INTEGRATION_REQUIREMENT,
                "请确认需要接入的身份协议。",
            ),
            ClarifyingQuestion(
                RequirementDimension.TIMELINE,
                "请确认期望上线日期。",
            ),
            ClarifyingQuestion(
                RequirementDimension.BUDGET,
                "请确认最终预算口径。",
            ),
        ),
    )


def admission_fixture():
    private = AtomicSolutionClaim(
        section=SolutionSectionKey.DEPLOYMENT,
        statement_type=SolutionStatementType.ENTERPRISE_FACT,
        text="SalesMind 支持私有化部署。",
        citations=("S1",),
    )
    unresolved = AtomicSolutionClaim(
        section=SolutionSectionKey.INTEGRATION,
        statement_type=SolutionStatementType.UNRESOLVED,
        text="当前企业资料未确认 SSO 集成，需要进一步确认。",
        citations=(),
    )
    return GroundingAdmission(
        claims=AtomicSolutionClaimSet((private, unresolved)),
        enterprise_decisions=(
            EnterpriseAdmissionDecision(
                subject_key="private_deployment",
                status="confirmed_supported",
                enterprise_fact_ids=(41,),
                needs_attention=False,
            ),
            EnterpriseAdmissionDecision(
                subject_key="sso_integration",
                status="unconfirmed",
                enterprise_fact_ids=(),
                needs_attention=False,
            ),
        ),
        enterprise_provenance=(
            EnterpriseClaimProvenance(
                claim=private,
                subject_key="private_deployment",
                fact_id=41,
            ),
        ),
        allowed_proposal_source_labels=("S1",),
    )


def test_deterministic_v2_content_owns_customer_enterprise_and_unresolved_claims():
    from apps.sales.services.solution_schema_v2 import (
        SolutionClaimTypeV2,
        build_v2_deterministic_items,
    )

    result = build_v2_deterministic_items(analysis_fixture(), admission_fixture())
    by_type = {}
    for item in result.claims:
        by_type.setdefault(item.statement_type, []).append(item)

    assert len(by_type[SolutionClaimTypeV2.CUSTOMER_FACT]) == 7
    assert any(
        item.text == "部署要求：私有化部署。"
        for item in by_type[SolutionClaimTypeV2.CUSTOMER_FACT]
    )
    assert [item.text for item in by_type[SolutionClaimTypeV2.ENTERPRISE_FACT]] == [
        "SalesMind 支持私有化部署。"
    ]
    assert len(by_type[SolutionClaimTypeV2.UNRESOLVED]) == 4
    assert any("SSO 集成" in item.text for item in by_type[SolutionClaimTypeV2.UNRESOLVED])


def test_every_nonknown_requirement_maps_once_to_open_question_and_assumption():
    from apps.sales.services.solution_schema_v2 import build_v2_deterministic_items

    result = build_v2_deterministic_items(analysis_fixture(), admission_fixture())

    assert [item.requirement_field for item in result.open_questions] == [
        RequirementDimension.INTEGRATION_REQUIREMENT,
        RequirementDimension.TIMELINE,
        RequirementDimension.BUDGET,
    ]
    assert len(result.assumption_claim_ids) == 3
    question_claims = {
        item.requirement_field: result.claim_by_id(item.unresolved_claim_id)
        for item in result.open_questions
    }
    assert question_claims[RequirementDimension.TIMELINE].text.endswith(
        "请确认期望上线日期。"
    )
    assert question_claims[RequirementDimension.BUDGET].text.startswith(
        "预算存在冲突"
    )


def test_stable_claim_ids_follow_canonical_order_and_are_not_text_hashes():
    from apps.sales.services.solution_schema_v2 import build_v2_deterministic_items

    first = build_v2_deterministic_items(analysis_fixture(), admission_fixture())
    second = build_v2_deterministic_items(analysis_fixture(), admission_fixture())

    assert [item.claim_id for item in first.claims] == [
        f"C{index:04d}" for index in range(1, len(first.claims) + 1)
    ]
    assert first.claims == second.claims


def test_enterprise_claim_binding_uses_exact_admission_fact_identity():
    from apps.sales.services.solution_schema_v2 import build_v2_deterministic_items

    result = build_v2_deterministic_items(analysis_fixture(), admission_fixture())
    enterprise = next(item for item in result.claims if item.citations == ("S1",))

    assert result.provenance_bindings == (
        type(result.provenance_bindings[0])(
            claim_id=enterprise.claim_id,
            citation_label="S1",
            fact_id=41,
        ),
    )


def test_unconfirmed_enterprise_decision_never_becomes_enterprise_fact():
    from apps.sales.services.solution_schema_v2 import (
        SolutionClaimTypeV2,
        build_v2_deterministic_items,
    )

    result = build_v2_deterministic_items(analysis_fixture(), admission_fixture())

    assert not any(
        item.statement_type is SolutionClaimTypeV2.ENTERPRISE_FACT
        and "SSO" in item.text
        for item in result.claims
    )
    assert any(
        item.statement_type is SolutionClaimTypeV2.UNRESOLVED and "SSO" in item.text
        for item in result.claims
    )
