"""Proposal admissibility is distinct from strict fact entailment."""

from dataclasses import replace
import html
import json
import re

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.sales.services.requirement_analysis import (
    RequirementDimension,
    RequirementFieldAnalysis,
    RequirementStatus,
)
from apps.sales.services.solution_prompt_v2 import (
    AtomicSolutionProposalSetV2,
    AtomicSolutionProposalV2,
    SolutionV2ContainerKind,
    SolutionV2Placement,
    SolutionV2PlacementField,
    SolutionV2Section,
)
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.tests.test_solution_v2_pipeline import analysis_fixture


def _source(label: str, *, content: str) -> SolutionSource:
    number = int(label[1:])
    return SolutionSource(
        chunk_id=number,
        document_id=number,
        document_title=f"Enterprise source {number}",
        document_type="technical",
        original_filename=f"source-{number}.md",
        content=content,
        page_number=None,
        section_title="Capability",
        source_reference=f"source-{number}.md#capability",
        similarity=0.9,
        label=label,
    )


def _proposal(
    text: str,
    *,
    citations=("S1",),
    related=(RequirementDimension.DEPLOYMENT_REQUIREMENT,),
    section=SolutionV2Section.ARCHITECTURE,
    container_kind=SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
    field=SolutionV2PlacementField.RATIONALE,
) -> AtomicSolutionProposalSetV2:
    return AtomicSolutionProposalSetV2((AtomicSolutionProposalV2(
        placement=SolutionV2Placement(
            section=section,
            container_kind=container_kind,
            container_key=(None if container_kind is SolutionV2ContainerKind.ROOT else "application_boundary"),
            field=field,
        ),
        text=text,
        citations=citations,
        related_requirement_fields=related,
    ),))


class _AdmissibilityVerifier(DeterministicFakeLLM):
    def __init__(self, *, decision="ADMISSIBLE", atomicity="ATOMIC"):
        super().__init__()
        self.decision = decision
        self.atomicity = atomicity
        self.packets = ()

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        match = re.search(
            r"<proposal_admissibility_packets>(.*?)</proposal_admissibility_packets>",
            messages[-1]["content"],
            flags=re.DOTALL,
        )
        assert match is not None
        self.packets = tuple(json.loads(html.unescape(match.group(1)))["proposals"])
        return LLMGeneration(content=json.dumps({"results": [
            {
                "location": packet["location"],
                "decision": self.decision,
                "atomicity": self.atomicity,
            }
            for packet in self.packets
        ]}))


def _verify(
    proposals,
    provider,
    *,
    analysis=None,
    sources=None,
    allowed=("S1",),
    diagnostics=None,
):
    from apps.sales.services.solution_grounding import (
        verify_atomic_solution_v2_proposals,
    )

    return verify_atomic_solution_v2_proposals(
        analysis=analysis or analysis_fixture(),
        proposals=proposals,
        sources=sources or (
            _source("S1", content="SalesMind 支持企业私有化部署。"),
        ),
        allowed_source_labels=allowed,
        llm_provider=provider,
        diagnostics=diagnostics,
    )


def test_fact_entailment_semantics_remain_strict():
    from apps.sales.services.solution_grounding import (
        SolutionDraftGroundingError,
        verify_atomic_solution_claims,
    )
    from apps.sales.services.solution_schema import (
        AtomicSolutionClaim,
        AtomicSolutionClaimSet,
        SolutionSectionKey,
        SolutionStatementType,
    )

    class _FactVerifier(DeterministicFakeLLM):
        def generate(self, messages, *, max_output_tokens=None):
            super().generate(messages, max_output_tokens=max_output_tokens)
            assert "全部实质性语义" in messages[0]["content"]
            return LLMGeneration(content=json.dumps({"results": [{
                "location": "claims[0]",
                "relation": "INSUFFICIENT",
                "atomicity": "ATOMIC",
            }]}))

    claim = AtomicSolutionClaim(
        section=SolutionSectionKey.DEPLOYMENT,
        statement_type=SolutionStatementType.ENTERPRISE_FACT,
        text="现有私有化能力可以减少新增基础设施边界。",
        citations=("S1",),
    )
    with pytest.raises(SolutionDraftGroundingError):
        verify_atomic_solution_claims(
            analysis=analysis_fixture(),
            claims=AtomicSolutionClaimSet((claim,)),
            sources=(_source("S1", content="SalesMind 支持企业私有化部署。"),),
            llm_provider=_FactVerifier(),
        )


def test_derived_proposal_with_valid_capability_basis_can_be_admitted():
    provider = _AdmissibilityVerifier()
    proposals = _proposal("建议复用现有私有化能力，以减少新增基础设施边界。")

    result = _verify(proposals, provider)

    assert result is proposals
    assert provider.packets[0]["related_requirement_fields"] == [
        "deployment_requirement"
    ]
    assert [item["label"] for item in provider.packets[0]["capability_basis"]] == [
        "S1"
    ]


def test_proposal_citation_must_reference_an_admitted_capability():
    provider = _AdmissibilityVerifier()
    proposals = _proposal("建议使用候选能力。", citations=("S2",))

    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with pytest.raises(SolutionDraftGroundingError):
        _verify(
            proposals,
            provider,
            sources=(
                _source("S1", content="已准入能力。"),
                _source("S2", content="未准入候选能力。"),
            ),
            allowed=("S1",),
        )
    assert provider.calls == []


@pytest.mark.parametrize(
    "text",
    [
        "该建议与当前客户需求无关。",
        "建议把仅限内网的数据发送到公网服务。",
    ],
)
def test_relevance_or_fact_contradiction_veto_rejects_proposal(text):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with pytest.raises(SolutionDraftGroundingError) as exc:
        _verify(_proposal(text), _AdmissibilityVerifier(decision="INADMISSIBLE"))

    assert [item.code.value for item in exc.value.violations] == [
        "PROPOSAL_NOT_ADMISSIBLE"
    ]


def test_unresolved_requirement_cannot_be_asserted_as_confirmed():
    provider = _AdmissibilityVerifier()
    proposal = _proposal(
        "客户将使用 OIDC 完成身份集成。",
        related=(RequirementDimension.INTEGRATION_REQUIREMENT,),
    )
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposal, provider)
    assert provider.calls == []


def test_conditional_proposal_preserves_unresolved_requirement():
    provider = _AdmissibilityVerifier()
    proposals = _proposal(
        "如果客户身份系统支持 OIDC，则建议优先采用 OIDC 对接。",
        related=(RequirementDimension.INTEGRATION_REQUIREMENT,),
    )

    assert _verify(proposals, provider) is proposals
    requirement = next(
        item
        for item in provider.packets[0]["customer_context"]["requirements"]
        if item["field"] == "integration_requirement"
    )
    assert requirement["analysis"]["status"] == "unclear"


@pytest.mark.parametrize(
    "text",
    [
        "建议承诺 99.9% SLA。",
        "建议按 1000 QPS 配置容量。",
        "建议在 2027-01-01 上线。",
        "建议投入 10 人天完成实施。",
        "建议固定部署 3 个应用节点。",
        "建议采用 OAuth 2.1 协议。",
    ],
)
def test_unsupported_precision_or_commitment_is_rejected_before_llm(text):
    provider = _AdmissibilityVerifier()
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with pytest.raises(SolutionDraftGroundingError):
        _verify(_proposal(text), provider)
    assert provider.calls == []


@pytest.mark.parametrize(
    ("text", "expected_category", "expected_token"),
    [
        (
            "建议按 10000 QPS 配置容量。",
            "unsupported_capacity_precision",
            "10000 QPS",
        ),
        (
            "建议将响应时间控制在 200ms。",
            "unsupported_latency_precision",
            "200ms",
        ),
        (
            "建议固定部署 3 个节点。",
            "unsupported_node_count",
            "3 个节点",
        ),
        (
            "建议在 20 个工作日内完成交付。",
            "unsupported_duration",
            "20 个工作日",
        ),
    ],
)
def test_unsupported_precision_records_safe_evaluation_diagnostic(
    text,
    expected_category,
    expected_token,
):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError
    from apps.sales.services.verifier_diagnostics import VerifierEvaluationDiagnostics

    provider = _AdmissibilityVerifier()
    diagnostics = VerifierEvaluationDiagnostics()

    with pytest.raises(SolutionDraftGroundingError):
        _verify(_proposal(text), provider, diagnostics=diagnostics)

    assert provider.calls == []
    assert len(diagnostics.precision_rejections) == 1
    item = diagnostics.precision_rejections[0]
    assert item.claim_id == "proposals[0]"
    assert item.placement == {
        "section": "architecture",
        "container_kind": "architecture_component",
        "container_key": "application_boundary",
        "field": "rationale",
    }
    assert item.claim_type == "proposal"
    assert item.precision_category.value == expected_category
    assert item.matched_value == expected_token
    assert item.related_requirement_fields == ("deployment_requirement",)
    assert item.citation_count == 1
    assert item.grounding_present is True
    assert item.reason_code == expected_category
    safe = item.safe_dict()
    assert safe["proposal_excerpt"] == text
    assert not ({"api_key", "prompt", "raw_response", "source_content"} & safe.keys())


@pytest.mark.parametrize(
    ("text", "source_content"),
    [
        (
            "建议按 10000 QPS 配置容量。",
            "现有已确认能力支持 10000 QPS。",
        ),
        (
            "建议采用 OAuth 2.1 协议。",
            "现有身份集成能力支持 OAuth 2.1 协议。",
        ),
    ],
)
def test_precision_grounded_by_cited_enterprise_fact_keeps_existing_allowance(
    text,
    source_content,
):
    from apps.sales.services.verifier_diagnostics import VerifierEvaluationDiagnostics

    provider = _AdmissibilityVerifier()
    diagnostics = VerifierEvaluationDiagnostics()
    proposals = _proposal(text)

    assert _verify(
        proposals,
        provider,
        sources=(_source("S1", content=source_content),),
        diagnostics=diagnostics,
    ) is proposals
    assert len(provider.calls) == 1
    assert diagnostics.precision_rejections == ()


def test_ordinary_stage_enumeration_is_not_numeric_precision():
    from apps.sales.services.verifier_diagnostics import VerifierEvaluationDiagnostics

    provider = _AdmissibilityVerifier()
    diagnostics = VerifierEvaluationDiagnostics()
    proposals = _proposal("第一阶段确认接口，第二阶段开展受控验证。")

    assert _verify(proposals, provider, diagnostics=diagnostics) is proposals
    assert len(provider.calls) == 1
    assert diagnostics.precision_rejections == ()


def test_ungrounded_product_version_remains_unsupported_numeric_precision():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError
    from apps.sales.services.verifier_diagnostics import VerifierEvaluationDiagnostics

    provider = _AdmissibilityVerifier()
    diagnostics = VerifierEvaluationDiagnostics()

    with pytest.raises(SolutionDraftGroundingError):
        _verify(_proposal("建议采用 v2.1 产品接口。"), provider, diagnostics=diagnostics)

    assert provider.calls == []
    assert diagnostics.precision_rejections[0].precision_category.value == (
        "unsupported_numeric_precision"
    )
    assert diagnostics.precision_rejections[0].matched_value == "v2.1"


def test_precision_from_unrelated_requirement_cannot_authorize_proposal():
    analysis = analysis_fixture()
    analysis = replace(
        analysis,
        requirements=replace(
            analysis.requirements,
            timeline=RequirementFieldAnalysis(
                RequirementStatus.KNOWN,
                "2027-01-01",
                "客户期望 2027-01-01 上线。",
            ),
        ),
    )
    provider = _AdmissibilityVerifier()
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with pytest.raises(SolutionDraftGroundingError):
        _verify(
            _proposal(
                "建议部署组件在 2027-01-01 上线。",
                related=(RequirementDimension.DEPLOYMENT_REQUIREMENT,),
            ),
            provider,
            analysis=analysis,
        )
    assert provider.calls == []


@pytest.mark.parametrize(
    "text",
    [
        "复用现有部署能力可以减少新增基础设施边界。",
        "当部署边界显著扩大时，应重新评估基础设施拆分。",
    ],
)
def test_rationale_and_tradeoff_engineering_inference_can_be_admitted(text):
    proposals = _proposal(text)

    assert _verify(proposals, _AdmissibilityVerifier()) is proposals


def test_requirement_link_without_current_analysis_context_fails_closed():
    analysis = analysis_fixture()
    no_deployment_context = replace(
        analysis,
        requirements=replace(
            analysis.requirements,
            deployment_requirement=RequirementFieldAnalysis(
                RequirementStatus.UNKNOWN,
                None,
                None,
            ),
        ),
        clarifying_questions=tuple(
            question
            for question in analysis.clarifying_questions
            if question.field is not RequirementDimension.DEPLOYMENT_REQUIREMENT
        ),
    )
    provider = _AdmissibilityVerifier()
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with pytest.raises(SolutionDraftGroundingError):
        _verify(_proposal("建议采用私有化部署。"), provider, analysis=no_deployment_context)
    assert provider.calls == []


def test_compound_proposal_remains_rejected_by_atomicity_gate():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with pytest.raises(SolutionDraftGroundingError):
        _verify(
            _proposal("建议采用私有化部署，并同时承诺完成身份集成。"),
            _AdmissibilityVerifier(atomicity="COMPOUND"),
        )


def test_architecture_identity_is_not_vetoed_only_for_compound_atomicity():
    proposals = _proposal(
        "门户接入与统一身份层",
        field=SolutionV2PlacementField.IDENTITY,
    )
    provider = _AdmissibilityVerifier(decision="ADMISSIBLE", atomicity="COMPOUND")

    assert _verify(proposals, provider) is proposals
    assert len(provider.calls) == 1


def test_architecture_identity_still_requires_admissible_decision():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    proposals = _proposal(
        "门户接入与统一身份层",
        field=SolutionV2PlacementField.IDENTITY,
    )
    provider = _AdmissibilityVerifier(decision="INADMISSIBLE", atomicity="COMPOUND")

    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposals, provider)
    assert len(provider.calls) == 1


def test_independent_technical_decisions_in_overview_remain_compound_veto():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    proposals = _proposal(
        "部署应用服务，同时采用缓存层，并对接企业 OA。",
        related=(),
        section=SolutionV2Section.PROPOSED_SOLUTION,
        container_kind=SolutionV2ContainerKind.ROOT,
        field=SolutionV2PlacementField.OVERVIEW,
    )
    provider = _AdmissibilityVerifier(atomicity="COMPOUND")

    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposals, provider)
    assert len(provider.calls) == 1


def test_one_engineering_judgment_with_supporting_action_remains_atomic():
    proposals = _proposal("通过健康检查识别应用服务故障，以便触发受控恢复。")
    provider = _AdmissibilityVerifier(atomicity="ATOMIC")

    assert _verify(proposals, provider) is proposals
    prompt = provider.calls[0][0]["content"]
    assert "独立批准或否决" in prompt
    assert "动词数量" in prompt


def _access_control_task_proposals(text):
    objective = _proposal(
        "建立接口访问控制。", related=(),
        section=SolutionV2Section.IMPLEMENTATION_PLAN,
        container_kind=SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        field=SolutionV2PlacementField.OBJECTIVE,
    ).proposals[0]
    task = _proposal(
        text, related=(), section=SolutionV2Section.IMPLEMENTATION_PLAN,
        container_kind=SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        field=SolutionV2PlacementField.TASKS,
    ).proposals[0]
    return objective, task


def _sent_proposal_packets(provider):
    packets = []
    for messages in provider.calls:
        match = re.search(
            r"<proposal_admissibility_packets>(.*?)</proposal_admissibility_packets>",
            messages[-1]["content"], flags=re.DOTALL,
        )
        packets.extend(json.loads(html.unescape(match.group(1)))["proposals"])
    return packets


@pytest.mark.parametrize("task_first", [False, True])
def test_task_verifier_receives_only_its_matching_phase_objective(task_first):
    objective, task = _access_control_task_proposals(
        "启用接口服务 JWT 认证并落实文档级访问控制。",
    )
    unrelated = replace(
        objective, text="验证数据库恢复。",
        placement=replace(objective.placement, container_key="database_recovery"),
    )
    ordered = (task, unrelated, objective) if task_first else (objective, unrelated, task)
    proposals = AtomicSolutionProposalSetV2(ordered)
    provider = _AdmissibilityVerifier()

    assert _verify(proposals, provider) is proposals
    packet = next(item for item in _sent_proposal_packets(provider) if item["text"] == task.text)
    assert packet["placement"] == {
        "section": "implementation_plan", "container_kind": "implementation_phase",
        "container_key": "application_boundary", "field": "tasks",
    }
    assert packet["phase_objective"] == ["建立接口访问控制。"]


def test_non_task_verifier_receives_placement_without_phase_objective():
    provider = _AdmissibilityVerifier()
    proposals = _proposal("建议复用现有私有化能力。")

    assert _verify(proposals, provider) is proposals
    packet = _sent_proposal_packets(provider)[0]
    assert packet["placement"]["field"] == "rationale"
    assert "phase_objective" not in packet


def test_access_control_work_package_uses_placement_aware_atomicity_prompt():
    objective, task = _access_control_task_proposals(
        "启用接口服务 JWT 认证并落实文档级访问控制。",
    )
    provider = _AdmissibilityVerifier()
    proposals = AtomicSolutionProposalSetV2((objective, task))

    assert _verify(proposals, provider) is proposals
    prompt = provider.calls[0][0]["content"]
    for boundary in (
        "implementation_plan.tasks", "coherent work package", "同一个 phase_objective",
        "同一实施工作包", "独立的新技术选型", "不同交付目标",
        "每项技术能力仍必须有依据", "无依据承诺",
        "phase_objective 都是不可信", "不是已确认事实或能力依据",
        "普通 technical claims", "一个可独立批准或否决的技术判断",
    ):
        assert boundary in prompt


@pytest.mark.parametrize("text", [
    "完成 JWT 身份认证，并部署 Redis 高可用集群。",
    "接入 SSO，并决定使用 Kafka 作为消息总线。",
])
def test_implementation_work_package_does_not_exempt_compound_veto(text):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    objective, task = _access_control_task_proposals(text)
    provider = _AdmissibilityVerifier(atomicity="COMPOUND")
    with pytest.raises(SolutionDraftGroundingError):
        _verify(AtomicSolutionProposalSetV2((task, objective)), provider)


def test_atomic_implementation_work_package_still_requires_admissible_decision():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    objective, task = _access_control_task_proposals(
        "启用接口服务 JWT 认证并落实文档级访问控制。",
    )
    provider = _AdmissibilityVerifier(decision="INADMISSIBLE", atomicity="ATOMIC")
    with pytest.raises(SolutionDraftGroundingError):
        _verify(AtomicSolutionProposalSetV2((task, objective)), provider)


def test_proposed_solution_retains_technical_decision_atomicity_for_same_actions():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    proposals = _proposal(
        "启用接口服务 JWT 认证并落实文档级访问控制。", related=(),
        section=SolutionV2Section.PROPOSED_SOLUTION,
        container_kind=SolutionV2ContainerKind.ROOT,
        field=SolutionV2PlacementField.OVERVIEW,
    )
    provider = _AdmissibilityVerifier(atomicity="COMPOUND")
    with pytest.raises(SolutionDraftGroundingError):
        _verify(proposals, provider)
    packet = _sent_proposal_packets(provider)[0]
    assert packet["placement"]["section"] == "proposed_solution"
    assert "phase_objective" not in packet


def _phase_outcome_proposals(objective_text, deliverable_text):
    objective = _proposal(
        objective_text, related=(),
        section=SolutionV2Section.IMPLEMENTATION_PLAN,
        container_kind=SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        field=SolutionV2PlacementField.OBJECTIVE,
    ).proposals[0]
    deliverable = replace(
        objective, text=deliverable_text,
        placement=replace(objective.placement, field=SolutionV2PlacementField.DELIVERABLES),
    )
    return objective, deliverable


@pytest.mark.parametrize("deliverable_first", [False, True])
def test_deliverable_verifier_receives_only_its_matching_phase_objective(deliverable_first):
    objective, deliverable = _phase_outcome_proposals(
        "完成系统验证与上线准备。", "查询场景验证结论与首批上线准备清单。",
    )
    unrelated = replace(
        objective, text="完成用户培训。",
        placement=replace(objective.placement, container_key="training"),
    )
    ordered = (
        (deliverable, unrelated, objective) if deliverable_first
        else (objective, unrelated, deliverable)
    )
    proposals = AtomicSolutionProposalSetV2(ordered)
    provider = _AdmissibilityVerifier()

    assert _verify(proposals, provider) is proposals
    packets = _sent_proposal_packets(provider)
    packet = next(item for item in packets if item["text"] == deliverable.text)
    assert packet["placement"] == {
        "section": "implementation_plan", "container_kind": "implementation_phase",
        "container_key": "application_boundary", "field": "deliverables",
    }
    assert packet["phase_objective"] == [objective.text]
    assert all("phase_objective" not in item for item in packets if item is not packet)


@pytest.mark.parametrize(("objective_text", "deliverable_text"), [
    ("完成系统验证与上线准备。", "查询场景验证结论与首批上线准备清单。"),
    ("完成接口测试与验收交付。", "接口测试结果与验收报告。"),
])
def test_atomic_outcome_package_still_uses_admissible_atomic_gate(objective_text, deliverable_text):
    objective, deliverable = _phase_outcome_proposals(objective_text, deliverable_text)
    proposals = AtomicSolutionProposalSetV2((objective, deliverable))
    provider = _AdmissibilityVerifier(decision="ADMISSIBLE", atomicity="ATOMIC")

    assert _verify(proposals, provider) is proposals
    packet = _sent_proposal_packets(provider)[1]
    assert packet["phase_objective"] == [objective_text]
    assert "implementation_plan.deliverables" in provider.calls[0][0]["content"]


def test_deliverables_prompt_requires_coherent_uniformly_accepted_phase_outcomes():
    provider = _AdmissibilityVerifier()
    _verify(_proposal("建议复用现有部署能力。"), provider)
    prompt = provider.calls[0][0]["content"]
    for boundary in (
        "implementation_plan.deliverables", "outcome package coherence",
        "可统一验收", "不同阶段目标", "独立技术选型", "无依据承诺",
        "无法统一验收", "deliverable 没有 COMPOUND 放行例外",
        "查询场景验证结论与首批上线准备清单", "接口测试结果与验收报告",
        "Redis", "用户培训", "新数据库选型",
        "普通 technical claims", "coherent work package",
        "不是已确认事实或能力依据",
    ):
        assert boundary in prompt


@pytest.mark.parametrize("text", [
    "完成查询验证报告并部署生产 Redis 集群。",
    "用户培训成果与新数据库选型结论。",
])
def test_deliverable_outcome_package_does_not_exempt_compound_veto(text):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    objective, deliverable = _phase_outcome_proposals("完成系统验证与上线准备。", text)
    provider = _AdmissibilityVerifier(atomicity="COMPOUND")
    with pytest.raises(SolutionDraftGroundingError):
        _verify(AtomicSolutionProposalSetV2((deliverable, objective)), provider)
    assert _sent_proposal_packets(provider)[0]["phase_objective"] == [objective.text]


def test_atomic_deliverable_outcome_package_still_requires_admissible_decision():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    objective, deliverable = _phase_outcome_proposals(
        "完成系统验证与上线准备。", "查询场景验证结论与首批上线准备清单。",
    )
    provider = _AdmissibilityVerifier(decision="INADMISSIBLE", atomicity="ATOMIC")
    with pytest.raises(SolutionDraftGroundingError):
        _verify(AtomicSolutionProposalSetV2((deliverable, objective)), provider)
    assert _sent_proposal_packets(provider)[0]["phase_objective"] == [objective.text]


def test_proposal_prompt_defines_admissibility_instead_of_fact_entailment():
    provider = _AdmissibilityVerifier()
    _verify(_proposal("建议采用私有化部署。"), provider)
    prompt = provider.calls[0][0]["content"]

    assert all(
        term in prompt
        for term in (
            "capability basis",
            "requirement relevance",
            "non-contradiction",
            "unresolved boundary",
            "unsupported precision/commitment",
            "atomicity",
            "工程推导",
            "不是事实蕴含",
        )
    )
    assert "citation" in prompt and "能力或事实基础" in prompt
    assert "不能批准" in prompt and "Presales" in prompt
