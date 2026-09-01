"""Prompt contracts at the provider boundary, not semantic validation by a fake."""

import json
from xml.etree import ElementTree

import pytest

from apps.rag.tests.test_answering import search_result
from apps.sales.services import solution_draft
from apps.sales.services.solution_schema import render_solution_statement
from apps.sales.tests.solution_fakes import analysis_record, SolutionFakeLLM, solution_payload


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw: pytest.fail("Offline semantic contract tests."))


def generate_with_evidence(monkeypatch, evidence, statement, *, customer_request="企业知识查询"):
    source = search_result(content=evidence)
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kw: [source])
    record = analysis_record(integration_requirement="unclear")
    record.requirements["use_scenario"]["value"] = customer_request
    payload = solution_payload()
    payload["executive_summary"] = [statement]
    provider = SolutionFakeLLM(content=json.dumps(payload, ensure_ascii=False))
    result = solution_draft.generate_grounded_solution_draft(record, llm_provider=provider)
    system, user = provider.calls[0]
    root = ElementTree.fromstring("<root>" + user["content"] + "</root>")
    assert evidence in root.find("enterprise_evidence/source").text
    assert root.find("enterprise_evidence/source").attrib == {"id": "S1"}
    assert result.sources[0].content == evidence
    assert provider.requested_output_budgets == [4000, None]
    return result, system["content"], root


@pytest.mark.parametrize("evidence,incorrect", [
    ("当前未确认 OA 的具体集成协议和适配能力。", "当前未提供OA集成能力"),
    ("当前资料未确认企业 SSO 集成能力。", "系统不提供SSO"),
    ("当前资料未声明 Kubernetes 部署支持。", "不支持Kubernetes"),
    ("现有资料不足以判断是否具备跨机房灾备能力。", "资料不足"),
    ("当前资料未确认高可用集群或自动扩缩容能力。", "未提供高可用集群或自动扩缩容的现成能力"),
])
def test_unconfirmed_evidence_requires_unresolved_not_negative_capability(monkeypatch, evidence, incorrect):
    _, system, _ = generate_with_evidence(monkeypatch, evidence, {
        "type": "unresolved", "text": "当前资料不足以确认该能力，需进一步确认。", "citations": ["S1"],
    })
    # The real service must send these distinctions to the model. A canned
    # response cannot prove that a real model follows them; smoke tests do that.
    for contract in (
        '"not confirmed" does NOT mean "unsupported"',
        '"not stated" does NOT mean "not provided"',
        '"insufficient evidence" does NOT mean "unavailable"',
        "“未确认”不等于“不支持”", "“未声明”不等于“未提供”", "“资料不足”不等于“不具备”",
        "未确认能力必须使用 type=unresolved", "不得以 enterprise_fact 或 proposal 把未知改写为否定能力",
        "不支持、未提供、不具备、无法、不能、没有该能力、不接入", incorrect,
    ):
        assert contract in system


def test_explicit_negative_evidence_remains_expressible_and_is_not_rewritten(monkeypatch):
    text = "当前版本不支持扫描型 PDF OCR。"
    result, system, _ = generate_with_evidence(monkeypatch, text, {
        "type": "enterprise_fact", "text": text, "citations": ["S1"],
    })
    assert "只有企业证据明确写明不支持、不提供、当前无法或明确不可用" in system
    assert "允许 enterprise_fact 如实表达该限制，并必须引用对应的明确负面证据" in system
    assert "当前版本不支持扫描型 PDF OCR" in system
    statement = result.draft.executive_summary[0]
    assert statement.type == "enterprise_fact"
    assert statement.text == text and statement.citations == ("S1",)
    assert render_solution_statement(statement) == "当前版本不支持扫描型 PDF OCR。[S1]"


def test_confirmed_evidence_still_permits_positive_enterprise_claims(monkeypatch):
    result, system, _ = generate_with_evidence(monkeypatch, "企业资料确认支持私有化部署。", {
        "type": "enterprise_fact", "text": "系统支持私有化部署。", "citations": ["S1"],
    })
    assert "只有企业证据明确证明支持、具备或可提供" in system
    assert "才允许 enterprise_fact / proposal 对该能力作正向陈述" in system
    assert render_solution_statement(result.draft.executive_summary[0]) == "系统支持私有化部署。[S1]"


def test_customer_request_cannot_prove_either_support_or_non_support(monkeypatch):
    _, system, root = generate_with_evidence(
        monkeypatch, "企业资料仅确认知识查询，未确认采购合同生成功能。",
        {"type": "unresolved", "text": "当前企业资料未确认合同生成功能。", "citations": ["S1"]},
        customer_request="客户希望系统自动生成采购合同草案",
    )
    assert "采购合同草案" in root.find("customer_requirements").text
    assert "客户要求某项能力而企业证据未确认时" in system
    assert "不能反推支持，也不能反推不支持" in system
    assert "customer_fact 只记录客户需求；unresolved 记录企业能力仍待确认" in system
