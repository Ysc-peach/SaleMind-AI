"""Phase 5.5g regressions for customer context and atomicity gates."""

import json
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
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw: pytest.fail("No network."))


def sources():
    return merge_evidence([[
        search_result(chunk_id=1, document_id=11, content="企业资料确认支持私有化部署。"),
        search_result(chunk_id=2, document_id=12, content="当前资料未确认 SSO 集成能力。"),
    ]])


def claims(*items):
    value = payload()
    value["claims"] = list(items)
    return parse(value)


def item(kind, text, citations, section):
    return {
        "section": section,
        "statement_type": kind,
        "text": text,
        "citations": list(citations),
    }


class AtomicityFake(DeterministicFakeLLM):
    def __init__(self, results):
        super().__init__()
        self.results = results

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        root = ElementTree.fromstring("<root>" + messages[1]["content"] + "</root>")
        packets = json.loads(root.find("grounding_claim_packets").text)["claims"]
        return LLMGeneration(content=json.dumps({"results": [
            {"location": packet["location"], **result}
            for packet, result in zip(packets, self.results, strict=True)
        ]}))


@pytest.mark.parametrize(
    "section,text",
    [
        ("implementation", "客户预计约300人使用。"),
        ("overall_approach", "客户技术方向为 PostgreSQL 与 pgvector。"),
    ],
)
def test_customer_fact_context_is_complete_even_when_section_is_non_obvious(section, text):
    from apps.sales.services.requirement_analysis import RequirementDimension
    from apps.sales.services.solution_grounding import build_atomic_grounding_claim_packets

    value = claims(item("customer_fact", text, (), section))
    packet = build_atomic_grounding_claim_packets(typed_analysis(), value, sources())[0]

    assert tuple(requirement.field for requirement in packet.customer_context.requirements) == tuple(
        RequirementDimension
    )


def test_proposal_gets_complete_customer_context_but_only_cited_evidence():
    from apps.sales.services.requirement_analysis import RequirementDimension
    from apps.sales.services.solution_grounding import build_atomic_grounding_claim_packets

    value = claims(item("proposal", "建议采用私有化部署。", ("S1",), "implementation"))
    packet = build_atomic_grounding_claim_packets(typed_analysis(), value, sources())[0]

    assert tuple(requirement.field for requirement in packet.customer_context.requirements) == tuple(
        RequirementDimension
    )
    assert tuple(source.label for source in packet.evidence) == ("S1",)


def test_supported_compound_g1_claim_is_rejected_by_atomicity_gate():
    from apps.sales.services.solution_grounding import (
        GroundingAtomicity,
        SolutionDraftGroundingError,
        verify_atomic_solution_claims,
    )

    value = claims(item(
        "enterprise_fact",
        "SalesMind 可将数据保留在客户内网，并可关闭业务数据到公网的传输。",
        ("S1",),
        "data_security",
    ))
    provider = AtomicityFake([{"relation": "SUPPORTED", "atomicity": "COMPOUND"}])

    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify_atomic_solution_claims(
            analysis=typed_analysis(), claims=value, sources=sources(), llm_provider=provider,
        )

    assert exc.value.code == "solution_draft_not_grounded"
    assert GroundingAtomicity.COMPOUND.value == "COMPOUND"


def test_a3_compound_is_rejected_even_if_relation_is_supported():
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError, verify_atomic_solution_claims

    value = claims(item(
        "unresolved",
        "当前资料未确认 OA/SSO，客户暂无相关需求，因此不影响方案。",
        ("S2",),
        "integration",
    ))

    with pytest.raises(SolutionDraftGroundingError):
        verify_atomic_solution_claims(
            analysis=typed_analysis(), claims=value, sources=sources(),
            llm_provider=AtomicityFake([{"relation": "SUPPORTED", "atomicity": "COMPOUND"}]),
        )


@pytest.mark.parametrize(
    "kind,text,citations,relation",
    [
        ("enterprise_fact", "SalesMind 当前版本不支持 CSV 批量导出。", ("S1",), "SUPPORTED"),
        ("enterprise_fact", "SalesMind 支持私有化部署。", ("S1",), "SUPPORTED"),
        ("enterprise_fact", "当前资料未确认 SSO。", ("S2",), "INSUFFICIENT"),
        ("customer_fact", "客户 Linux 环境已验证满足部署条件。", (), "INSUFFICIENT"),
        ("enterprise_fact", "SalesMind 可以自动生成采购合同。", ("S1",), "INSUFFICIENT"),
        ("proposal", "建议采用私有化部署。", ("S1",), "SUPPORTED"),
    ],
)
def test_atomicity_gate_preserves_existing_semantic_decisions(kind, text, citations, relation):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError, verify_atomic_solution_claims

    value = claims(item(kind, text, citations, "deployment"))
    provider = AtomicityFake([{"relation": relation, "atomicity": "ATOMIC"}])
    if relation == "SUPPORTED":
        result = verify_atomic_solution_claims(
            analysis=typed_analysis(), claims=value, sources=sources(), llm_provider=provider,
        )
        assert result.passed
    else:
        with pytest.raises(SolutionDraftGroundingError):
            verify_atomic_solution_claims(
                analysis=typed_analysis(), claims=value, sources=sources(), llm_provider=provider,
            )


@pytest.mark.parametrize(
    "result",
    [
        {"relation": "SUPPORTED"},
        {"relation": "SUPPORTED", "atomicity": "UNKNOWN"},
        {"relation": "SUPPORTED", "atomicity": "ATOMIC", "extra": True},
    ],
)
def test_atomicity_response_is_strict_and_fails_closed(result):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError, verify_atomic_solution_claims

    value = claims(item("enterprise_fact", "SalesMind 支持私有化部署。", ("S1",), "deployment"))
    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify_atomic_solution_claims(
            analysis=typed_analysis(), claims=value, sources=sources(),
            llm_provider=AtomicityFake([result]),
        )
    assert exc.value.code == "solution_grounding_invalid_response"


def test_verifier_contract_separates_entailment_from_atomicity():
    from apps.sales.services.solution_grounding import verify_atomic_solution_claims

    value = claims(item("enterprise_fact", "SalesMind 支持私有化部署。", ("S1",), "deployment"))
    provider = AtomicityFake([{"relation": "SUPPORTED", "atomicity": "ATOMIC"}])
    verify_atomic_solution_claims(
        analysis=typed_analysis(), claims=value, sources=sources(), llm_provider=provider,
    )
    system = provider.calls[0][0]["content"]
    for contract in (
        "atomicity", "ATOMIC", "COMPOUND", "独立判断", "SUPPORTED + ATOMIC",
    ):
        assert contract in system
