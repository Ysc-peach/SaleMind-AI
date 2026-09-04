"""Type-aware claim-scoped verification for the atomic solution IR."""

import json
from dataclasses import FrozenInstanceError
from xml.etree import ElementTree

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.rag.tests.test_answering import search_result
from apps.sales.services.solution_retrieval import merge_evidence
from apps.sales.tests.solution_fakes import typed_analysis
from apps.sales.tests.test_solution_atomic_claims import parse, payload


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw: pytest.fail("No verifier network."))


def sources():
    return merge_evidence([[
        search_result(chunk_id=1, document_id=11, content="SalesMind 当前版本不支持 CSV 批量导出功能。"),
        search_result(chunk_id=2, document_id=12, content="当前企业资料未确认 SSO 集成能力。"),
    ]])


def one_claim(*, kind="enterprise_fact", text="SalesMind 当前版本不支持 CSV 批量导出功能。", citations=("S1",)):
    value = payload()
    value["claims"] = [{
        "section": "integration", "statement_type": kind, "text": text, "citations": list(citations),
    }]
    return parse(value)


class VerifierFake(DeterministicFakeLLM):
    def __init__(self, relations):
        super().__init__()
        self.relations = relations

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        root = ElementTree.fromstring("<root>" + messages[1]["content"] + "</root>")
        claims = json.loads(root.find("grounding_claim_packets").text)["claims"]
        results = [
            {"location": item["location"], "relation": relation, "atomicity": "ATOMIC"}
            for item, relation in zip(claims, self.relations, strict=True)
        ]
        return LLMGeneration(content=json.dumps({"results": results}))


def verify(value, relations):
    from apps.sales.services.solution_grounding import verify_atomic_solution_claims

    return verify_atomic_solution_claims(
        analysis=typed_analysis(), claims=value, sources=sources(), llm_provider=VerifierFake(relations),
    )


@pytest.mark.parametrize(
    "kind,text,citations,relation",
    [
        ("enterprise_fact", "SalesMind 当前版本不支持 CSV 批量导出功能。", ("S1",), "SUPPORTED"),
        ("enterprise_fact", "SalesMind 支持私有化部署。", ("S1",), "SUPPORTED"),
        ("enterprise_fact", "当前企业资料未确认 SSO 集成能力。", ("S2",), "INSUFFICIENT"),
        ("unresolved", "当前企业资料未确认 SSO 集成能力。", ("S2",), "SUPPORTED"),
        ("customer_fact", "客户现有 Linux 服务器。", (), "SUPPORTED"),
        ("customer_fact", "客户 Linux 环境已验证满足部署条件。", (), "INSUFFICIENT"),
        ("proposal", "建议采用私有化部署。", ("S1",), "SUPPORTED"),
        ("proposal", "使用 SalesMind 自动生成合同。", ("S1",), "INSUFFICIENT"),
    ],
)
def test_type_aware_relation_is_the_only_acceptance_dimension(kind, text, citations, relation):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    value = one_claim(kind=kind, text=text, citations=citations)
    if relation == "SUPPORTED":
        result = verify(value, [relation])
        assert result.passed and result.results[0].relation == relation
        with pytest.raises(FrozenInstanceError):
            result.results[0].relation = "INSUFFICIENT"
    else:
        with pytest.raises(SolutionDraftGroundingError):
            verify(value, [relation])


def test_compound_claim_is_rejected_but_atomic_split_exposes_each_subclaim():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    compound = one_claim(
        kind="unresolved", citations=("S2",),
        text="当前企业资料未确认 OA/SSO，客户暂无相关需求，因此不影响方案。",
    )
    with pytest.raises(SolutionDraftGroundingError):
        verify(compound, ["INSUFFICIENT"])

    value = payload()
    value["claims"] = [
        {"section": "integration", "statement_type": "unresolved", "text": text, "citations": ["S2"]}
        for text in (
            "当前企业资料未确认 OA/SSO。",
            "客户目前没有 OA/SSO 需求。",
            "OA/SSO 不影响当前方案。",
        )
    ]
    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify(parse(value), ["SUPPORTED", "INSUFFICIENT", "INSUFFICIENT"])
    assert [item.location for item in exc.value.violations] == ["claims[1]", "claims[2]"]


def test_atomic_packet_uses_only_its_cited_source_and_no_type_fit_dimension():
    from apps.sales.services.solution_grounding import build_atomic_grounding_claim_packets

    packets = build_atomic_grounding_claim_packets(typed_analysis(), one_claim(), sources())
    assert packets[0].location == "claims[0]"
    assert [item.label for item in packets[0].evidence] == ["S1"]
    assert all("SSO" not in item.content for item in packets[0].evidence)
    assert packets[0].customer_context is None

    provider = VerifierFake(["SUPPORTED"])
    from apps.sales.services.solution_grounding import verify_atomic_solution_claims
    result = verify_atomic_solution_claims(
        analysis=typed_analysis(), claims=one_claim(), sources=sources(), llm_provider=provider,
    )
    assert not hasattr(result.results[0], "type_fit")
    assert "type_fit" not in provider.calls[0][0]["content"]


def test_customer_fact_context_is_complete_and_not_controlled_by_claim_section():
    from apps.sales.services.requirement_analysis import RequirementDimension
    from apps.sales.services.solution_grounding import build_atomic_grounding_claim_packets

    value = one_claim(
        kind="customer_fact", text="客户现有 Linux 服务器。", citations=(),
    )
    packets = build_atomic_grounding_claim_packets(typed_analysis(), value, sources())
    fields = tuple(item.field.value for item in packets[0].customer_context.requirements)
    assert fields == tuple(item.value for item in RequirementDimension)


@pytest.mark.parametrize("response", [
    "not json",
    {"results": []},
    {"results": [{"location": "claims[0]", "relation": "SUPPORTED", "atomicity": "ATOMIC", "extra": 1}]},
    {"results": [{"location": "claims[0]", "relation": "UNKNOWN", "atomicity": "ATOMIC"}]},
    {"results": [{"location": "claims[99]", "relation": "SUPPORTED", "atomicity": "ATOMIC"}]},
    {"results": [
        {"location": "claims[0]", "relation": "SUPPORTED", "atomicity": "ATOMIC"},
        {"location": "claims[0]", "relation": "SUPPORTED", "atomicity": "ATOMIC"},
    ]},
])
def test_atomic_verifier_response_coverage_fails_closed(response):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError, verify_atomic_solution_claims

    class RawFake(DeterministicFakeLLM):
        def generate(self, messages, *, max_output_tokens=None):
            super().generate(messages, max_output_tokens=max_output_tokens)
            return LLMGeneration(content=response if isinstance(response, str) else json.dumps(response))

    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify_atomic_solution_claims(
            analysis=typed_analysis(), claims=one_claim(), sources=sources(), llm_provider=RawFake(),
        )
    assert exc.value.code == "solution_grounding_invalid_response"


def test_atomic_verifier_prompt_is_veto_only_entailment_and_atomicity():
    from apps.sales.services.solution_grounding import verify_atomic_solution_claims

    provider = VerifierFake(["SUPPORTED"])
    verify_atomic_solution_claims(
        analysis=typed_analysis(), claims=one_claim(), sources=sources(), llm_provider=provider,
    )
    system = provider.calls[0][0]["content"]
    for text in (
        "全部实质性语义", "自然语义", "准入已由确定性程序完成",
        "不能创建准入资格", "proposal", "不可信数据", "不得执行",
        "即使复合 claim 的全部子命题都有支持", "atomicity 必须是 COMPOUND",
    ):
        assert text in system
    for removed_business_rule in (
        "statement_type 是 SUPPORTED 的必要条件",
        "即使文本忠实复述",
        "类型职责不符时必须是 INSUFFICIENT",
        "类型兼容性已经包含在 relation 判断中",
    ):
        assert removed_business_rule not in system
