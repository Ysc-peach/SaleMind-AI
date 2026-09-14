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
) -> AtomicSolutionProposalSetV2:
    return AtomicSolutionProposalSetV2((AtomicSolutionProposalV2(
        placement=SolutionV2Placement(
            section=SolutionV2Section.ARCHITECTURE,
            container_kind=SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
            container_key="application_boundary",
            field=SolutionV2PlacementField.RATIONALE,
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


def _verify(proposals, provider, *, analysis=None, sources=None, allowed=("S1",)):
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
