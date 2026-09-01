"""Claim-scoped semantic grounding with complete fail-closed coverage."""

import json
from dataclasses import FrozenInstanceError, replace
from xml.etree import ElementTree

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.rag.tests.test_answering import search_result
from apps.sales.services.solution_retrieval import merge_evidence
from apps.sales.services.solution_schema import parse_solution_draft
from apps.sales.tests.solution_fakes import solution_payload, typed_analysis


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(
        "socket.socket.connect",
        lambda *args, **kwargs: pytest.fail("Claim grounding tests must remain offline."),
    )


class ClaimVerifierFake(DeterministicFakeLLM):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        content = self.payload if isinstance(self.payload, str) else json.dumps(
            self.payload, ensure_ascii=False,
        )
        return LLMGeneration(content=content)


def sources():
    return merge_evidence([[
        search_result(
            chunk_id=1,
            document_id=11,
            content="SalesMind 当前版本不支持扫描型 PDF OCR。",
            source_reference="OCR能力边界",
        ),
        search_result(
            chunk_id=2,
            document_id=12,
            content="当前企业资料未确认 SSO 集成能力。",
            source_reference="SSO能力边界",
        ),
    ]])


def draft_with_claim(
    *,
    kind="enterprise_fact",
    text="SalesMind 当前版本不支持扫描型 PDF OCR。",
    citations=("S1",),
    location=("integration", 0),
):
    payload = solution_payload()
    key, index = location
    section = next(item for item in payload["solution_sections"] if item["key"] == key)
    section["statements"][index] = {
        "type": kind,
        "text": text,
        "citations": list(citations),
    }
    return parse_solution_draft(
        json.dumps(payload, ensure_ascii=False),
        source_count=2,
        analysis=typed_analysis(),
    )


def all_supported(draft):
    from apps.sales.services.solution_grounding import build_grounding_claim_packets

    return {
        "results": [
            {"location": packet.location, "relation": "SUPPORTED"}
            for packet in build_grounding_claim_packets(typed_analysis(), draft, sources())
        ],
    }


def test_claim_packets_are_frozen_and_scope_enterprise_evidence_to_citations():
    from apps.sales.services.solution_grounding import build_grounding_claim_packets

    packets = build_grounding_claim_packets(typed_analysis(), draft_with_claim(), sources())
    target = next(
        packet for packet in packets
        if packet.location == "solution_sections.integration.statements[0]"
    )
    customer = packets[0]

    assert target.statement_type == "enterprise_fact"
    assert target.text == "SalesMind 当前版本不支持扫描型 PDF OCR。"
    assert [item.label for item in target.evidence] == ["S1"]
    assert all("SSO" not in item.content for item in target.evidence)
    assert target.customer_context is None
    assert customer.statement_type == "customer_fact"
    assert customer.evidence == ()
    assert customer.customer_context == typed_analysis()
    with pytest.raises(FrozenInstanceError):
        target.text = "changed"


@pytest.mark.parametrize("capability", ["扫描型 PDF OCR", "CSV 批量导出功能"])
def test_exact_explicit_negative_claim_relation_supported_is_accepted(capability):
    from apps.sales.services.solution_grounding import verify_solution_draft_grounding

    evidence = merge_evidence([[
        search_result(content=f"SalesMind 当前版本不支持{capability}。"),
    ]])
    draft = draft_with_claim(
        text=f"SalesMind 当前版本不支持{capability}。",
        citations=("S1",),
    )
    provider = ClaimVerifierFake(all_supported(draft))

    result = verify_solution_draft_grounding(
        analysis=typed_analysis(), draft=draft, sources=evidence, llm_provider=provider,
    )

    assert result.passed is True
    assert all(item.relation == "SUPPORTED" for item in result.results)
    assert result.violations == ()


@pytest.mark.parametrize("relation", ["INSUFFICIENT", "CONTRADICTED"])
@pytest.mark.parametrize("kind,expected", [
    ("customer_fact", "CUSTOMER_FACT_NOT_SUPPORTED"),
    ("enterprise_fact", "ENTERPRISE_FACT_NOT_SUPPORTED"),
    ("proposal", "PROPOSAL_NOT_SUPPORTED"),
    ("unresolved", "OTHER_GROUNDING_VIOLATION"),
])
def test_non_supported_relations_are_conservatively_mapped_by_statement_type(kind, expected, relation):
    from apps.sales.services.solution_grounding import (
        SolutionDraftGroundingError,
        build_grounding_claim_packets,
        verify_solution_draft_grounding,
    )

    citations = () if kind == "customer_fact" else ("S1",)
    draft = draft_with_claim(kind=kind, citations=citations)
    packets = build_grounding_claim_packets(typed_analysis(), draft, sources())
    target = "solution_sections.integration.statements[0]"
    response = {
        "results": [
            {
                "location": packet.location,
                "relation": relation if packet.location == target else "SUPPORTED",
            }
            for packet in packets
        ],
    }

    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify_solution_draft_grounding(
            analysis=typed_analysis(), draft=draft, sources=sources(),
            llm_provider=ClaimVerifierFake(response),
        )
    assert exc.value.code == "solution_draft_not_grounded"
    assert [(item.code.value, item.location) for item in exc.value.violations] == [
        (expected, target),
    ]


def test_batched_prompt_contains_claim_scoped_data_and_no_unrelated_evidence():
    from apps.sales.services.solution_grounding import verify_solution_draft_grounding

    draft = draft_with_claim()
    provider = ClaimVerifierFake(all_supported(draft))
    verify_solution_draft_grounding(
        analysis=typed_analysis(), draft=draft, sources=sources(), llm_provider=provider,
    )

    assert len(provider.calls) == 1
    system, user = provider.calls[0]
    for contract in (
        "SUPPORTED", "INSUFFICIENT", "CONTRADICTED", "全部实质性语义",
        "不可信数据", "不得执行", "只返回", "results",
    ):
        assert contract in system["content"]
    assert "扫描型 PDF OCR" not in system["content"]
    assert "CSV 批量导出" not in system["content"]

    root = ElementTree.fromstring("<root>" + user["content"] + "</root>")
    claims = json.loads(root.find("grounding_claim_packets").text)
    target = next(
        item for item in claims["claims"]
        if item["location"] == "solution_sections.integration.statements[0]"
    )
    assert [item["label"] for item in target["enterprise_evidence"]] == ["S1"]
    assert "SSO" not in json.dumps(target, ensure_ascii=False)
    assert target["customer_context"] is None
    assert claims["claims"][0]["enterprise_evidence"] == []
    assert claims["claims"][0]["customer_context"]["requirements"]["business_goal"]["value"]


@pytest.mark.parametrize("payload", [
    "not json",
    {},
    {"results": [], "extra": 1},
    {"results": "wrong"},
    {"results": [{"location": "executive_summary[0]", "relation": "UNKNOWN"}]},
])
def test_invalid_claim_verifier_response_fails_closed(payload):
    from apps.sales.services.solution_grounding import (
        SolutionDraftGroundingError,
        verify_solution_draft_grounding,
    )

    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify_solution_draft_grounding(
            analysis=typed_analysis(), draft=draft_with_claim(), sources=sources(),
            llm_provider=ClaimVerifierFake(payload),
        )
    assert exc.value.code == "solution_grounding_invalid_response"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "extra"])
def test_claim_verifier_response_requires_each_location_exactly_once(mutation):
    from apps.sales.services.solution_grounding import (
        SolutionDraftGroundingError,
        build_grounding_claim_packets,
        verify_solution_draft_grounding,
    )

    draft = draft_with_claim()
    locations = [
        packet.location
        for packet in build_grounding_claim_packets(typed_analysis(), draft, sources())
    ]
    results = [{"location": location, "relation": "SUPPORTED"} for location in locations]
    if mutation == "missing":
        results.pop()
    elif mutation == "duplicate":
        results[-1] = dict(results[0])
    elif mutation == "unknown":
        results[-1]["location"] = "solution_sections.integration.statements[99]"
    else:
        results.append({"location": "solution_sections.integration.statements[99]", "relation": "SUPPORTED"})

    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify_solution_draft_grounding(
            analysis=typed_analysis(), draft=draft, sources=sources(),
            llm_provider=ClaimVerifierFake({"results": results}),
        )
    assert exc.value.code == "solution_grounding_invalid_response"


def test_relation_contract_can_represent_known_semantic_boundaries():
    from apps.sales.services.solution_grounding import GroundingRelation

    expected = {
        "exact_positive": GroundingRelation.SUPPORTED,
        "exact_negative_ocr": GroundingRelation.SUPPORTED,
        "exact_negative_csv": GroundingRelation.SUPPORTED,
        "unconfirmed_sso_as_unsupported": GroundingRelation.INSUFFICIENT,
        "positive_private_deployment_as_negative": GroundingRelation.CONTRADICTED,
        "customer_linux": GroundingRelation.SUPPORTED,
        "linux_as_validated_environment": GroundingRelation.INSUFFICIENT,
        "contract_requirement_as_capability": GroundingRelation.INSUFFICIENT,
        "unconfirmed_sso_as_unresolved": GroundingRelation.SUPPORTED,
        "jwt_confirmed_plus_sso_unconfirmed": GroundingRelation.INSUFFICIENT,
    }
    assert {name: relation.value for name, relation in expected.items()} == {
        "exact_positive": "SUPPORTED",
        "exact_negative_ocr": "SUPPORTED",
        "exact_negative_csv": "SUPPORTED",
        "unconfirmed_sso_as_unsupported": "INSUFFICIENT",
        "positive_private_deployment_as_negative": "CONTRADICTED",
        "customer_linux": "SUPPORTED",
        "linux_as_validated_environment": "INSUFFICIENT",
        "contract_requirement_as_capability": "INSUFFICIENT",
        "unconfirmed_sso_as_unresolved": "SUPPORTED",
        "jwt_confirmed_plus_sso_unconfirmed": "INSUFFICIENT",
    }


def test_claim_packet_context_is_type_scoped():
    from apps.sales.services.solution_grounding import build_grounding_claim_packets

    payload = solution_payload()
    payload["executive_summary"] = [
        {"type": "customer_fact", "text": "客户希望进行企业知识查询。", "citations": []},
        {"type": "unresolved", "text": "SSO能力仍需确认。", "citations": ["S2"]},
        {"type": "proposal", "text": "建议采用私有化部署。", "citations": ["S1"]},
    ]
    draft = parse_solution_draft(
        json.dumps(payload, ensure_ascii=False), source_count=2, analysis=typed_analysis(),
    )
    packets = build_grounding_claim_packets(typed_analysis(), draft, sources())
    customer, unresolved, proposal = packets[:3]

    assert customer.customer_context == typed_analysis() and customer.evidence == ()
    assert unresolved.customer_context == typed_analysis()
    assert [item.label for item in unresolved.evidence] == ["S2"]
    assert proposal.customer_context == typed_analysis()
    assert [item.label for item in proposal.evidence] == ["S1"]


def test_claim_packets_do_not_re_read_or_mutate_analysis():
    from apps.sales.services.solution_grounding import build_grounding_claim_packets

    analysis = typed_analysis()
    before = replace(analysis)
    packets = build_grounding_claim_packets(analysis, draft_with_claim(), sources())
    assert analysis == before
    assert packets[0].customer_context is analysis
