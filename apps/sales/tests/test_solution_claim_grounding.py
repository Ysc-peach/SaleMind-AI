"""Regression coverage for atomic claim scoping and relation aggregation."""

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


def source_set():
    return merge_evidence([[
        search_result(chunk_id=1, document_id=11, content="SalesMind 当前版本不支持 CSV 批量导出功能。"),
        search_result(chunk_id=2, document_id=12, content="当前资料未确认 SSO 集成能力。"),
    ]])


def claims(*items):
    value = payload()
    value["claims"] = list(items)
    return parse(value)


def item(kind, text, citations, section="integration"):
    return {"section": section, "statement_type": kind, "text": text, "citations": list(citations)}


class ClaimVerifierFake(DeterministicFakeLLM):
    def __init__(self, relations):
        super().__init__()
        self.relations = relations

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        root = ElementTree.fromstring("<root>" + messages[1]["content"] + "</root>")
        packets = json.loads(root.find("grounding_claim_packets").text)["claims"]
        return LLMGeneration(content=json.dumps({"results": [
            {"location": packet["location"], "relation": relation}
            for packet, relation in zip(packets, self.relations, strict=True)
        ]}))


def test_packets_are_frozen_and_scope_each_claim_to_its_own_authority():
    from apps.sales.services.solution_grounding import build_atomic_grounding_claim_packets

    value = claims(
        item("enterprise_fact", "SalesMind 当前版本不支持 CSV 批量导出功能。", ("S1",)),
        item("unresolved", "当前资料未确认 SSO 集成能力。", ("S2",)),
        item("customer_fact", "客户现有 Linux 环境。", ()),
    )
    packets = build_atomic_grounding_claim_packets(typed_analysis(), value, source_set())
    assert [source.label for source in packets[0].evidence] == ["S1"]
    assert all("SSO" not in source.content for source in packets[0].evidence)
    assert packets[0].customer_context is None
    assert [source.label for source in packets[1].evidence] == ["S2"]
    assert tuple(item.field.value for item in packets[1].customer_context.requirements) == (
        "integration_requirement", "existing_environment", "use_scenario", "technical_constraints",
    )
    assert packets[2].evidence == ()
    assert packets[2].customer_context == packets[1].customer_context
    with pytest.raises(FrozenInstanceError):
        packets[0].text = "changed"


@pytest.mark.parametrize("capability", ["扫描型 PDF OCR", "CSV 批量导出功能"])
def test_explicit_negative_claims_are_representable_as_supported(capability):
    from apps.sales.services.solution_grounding import verify_atomic_solution_claims

    value = claims(item("enterprise_fact", f"SalesMind 当前版本不支持{capability}。", ("S1",)))
    result = verify_atomic_solution_claims(
        analysis=typed_analysis(), claims=value, sources=source_set(),
        llm_provider=ClaimVerifierFake(["SUPPORTED"]),
    )
    assert result.passed and result.results[0].relation == "SUPPORTED"


@pytest.mark.parametrize("kind,expected", [
    ("customer_fact", "CUSTOMER_FACT_NOT_SUPPORTED"),
    ("enterprise_fact", "ENTERPRISE_FACT_NOT_SUPPORTED"),
    ("proposal", "PROPOSAL_NOT_SUPPORTED"),
    ("unresolved", "OTHER_GROUNDING_VIOLATION"),
])
@pytest.mark.parametrize("relation", ["INSUFFICIENT", "CONTRADICTED"])
def test_non_supported_relation_is_conservatively_mapped_by_type(kind, expected, relation):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError, verify_atomic_solution_claims

    citations = () if kind == "customer_fact" else ("S1",)
    value = claims(item(kind, "一个受控原子命题。", citations))
    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify_atomic_solution_claims(
            analysis=typed_analysis(), claims=value, sources=source_set(),
            llm_provider=ClaimVerifierFake([relation]),
        )
    assert [(violation.code.value, violation.location) for violation in exc.value.violations] == [
        (expected, "claims[0]"),
    ]


def test_prompt_is_type_aware_atomic_and_has_no_capability_specific_examples():
    from apps.sales.services.solution_grounding import verify_atomic_solution_claims

    provider = ClaimVerifierFake(["SUPPORTED"])
    verify_atomic_solution_claims(
        analysis=typed_analysis(),
        claims=claims(item("enterprise_fact", "企业资料确认一项能力。", ("S1",))),
        sources=source_set(), llm_provider=provider,
    )
    system = provider.calls[0][0]["content"]
    for contract in (
        "全部实质性语义", "statement_type 是 SUPPORTED 的必要条件", "enterprise_fact",
        "unresolved", "customer_fact", "proposal", "含多个可独立验证的命题", "必须是 INSUFFICIENT",
    ):
        assert contract in system
    assert "扫描型 PDF OCR" not in system and "CSV 批量导出" not in system
