"""Atomic solution claim IR and deterministic draft assembly."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from apps.sales.services.solution_errors import SolutionDraftError


def payload():
    return {
        "claims": [
            {
                "section": "overall_approach",
                "statement_type": "customer_fact",
                "text": "客户计划建设企业知识服务。",
                "citations": [],
            },
            {
                "section": "deployment",
                "statement_type": "enterprise_fact",
                "text": "企业资料确认支持私有化部署。",
                "citations": ["S1"],
            },
            {
                "section": "implementation",
                "statement_type": "proposal",
                "text": "建议采用私有化部署方向。",
                "citations": ["S1"],
            },
            {
                "section": "integration",
                "statement_type": "unresolved",
                "text": "OA 集成范围仍需确认。",
                "citations": ["S2"],
            },
        ],
    }


def parse(value=None, *, source_count=2):
    from apps.sales.services.solution_schema import parse_atomic_solution_claims

    return parse_atomic_solution_claims(
        json.dumps(payload() if value is None else value, ensure_ascii=False),
        source_count=source_count,
    )


def test_atomic_ir_is_strict_typed_and_immutable():
    from apps.sales.services.solution_schema import (
        AtomicSolutionClaimSet,
        SolutionSectionKey,
        SolutionStatementType,
    )

    result = parse()
    assert isinstance(result, AtomicSolutionClaimSet)
    assert isinstance(result.claims, tuple)
    assert result.claims[1].section is SolutionSectionKey.DEPLOYMENT
    assert result.claims[1].statement_type is SolutionStatementType.ENTERPRISE_FACT
    assert result.claims[1].citations == ("S1",)
    with pytest.raises(FrozenInstanceError):
        result.claims[0].text = "changed"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(extra=True),
        lambda value: value.update(title="LLM 不得控制最终标题"),
        lambda value: value.update(claims=[]),
        lambda value: value["claims"][0].update(extra=True),
        lambda value: value["claims"][0].update(section="unknown"),
        lambda value: value["claims"][0].update(statement_type="unknown"),
        lambda value: value["claims"][0].update(text="  "),
        lambda value: value["claims"][0].update(citations="S1"),
    ],
)
def test_atomic_ir_rejects_missing_extra_or_invalid_schema(mutator):
    value = deepcopy(payload())
    mutator(value)
    with pytest.raises(SolutionDraftError):
        parse(value)


@pytest.mark.parametrize(
    "kind,citations,valid",
    [
        ("customer_fact", [], True),
        ("customer_fact", ["S1"], False),
        ("enterprise_fact", ["S1"], True),
        ("enterprise_fact", [], False),
        ("proposal", ["S1"], True),
        ("proposal", [], False),
        ("unresolved", [], True),
        ("unresolved", ["S1"], True),
        ("unresolved", ["S3"], False),
        ("unresolved", ["S1", "S1"], False),
    ],
)
def test_atomic_ir_preserves_structural_citation_authority(kind, citations, valid):
    value = payload()
    value["claims"] = [{
        "section": "overall_approach",
        "statement_type": kind,
        "text": "单一、可独立验证的命题。",
        "citations": citations,
    }]
    if valid:
        assert parse(value).claims[0].citations == tuple(citations)
    else:
        with pytest.raises(SolutionDraftError):
            parse(value)


@pytest.mark.parametrize("content", ["", "not json", "{}", '{"title":"x","claims":NaN}'])
def test_atomic_ir_rejects_malformed_json(content):
    from apps.sales.services.solution_schema import parse_atomic_solution_claims

    with pytest.raises(SolutionDraftError):
        parse_atomic_solution_claims(content, source_count=2)


def test_atomic_ir_rejects_inline_or_unknown_source_tokens():
    for text in ("企业资料确认支持部署。[S1]", "企业资料确认支持部署（S1）。"):
        value = payload()
        value["claims"][1]["text"] = text
        with pytest.raises(SolutionDraftError):
            parse(value)


def test_atomic_ir_preserves_public_per_section_size_bound():
    value = payload()
    value["claims"] = [
        {
            "section": "deployment",
            "statement_type": "enterprise_fact",
            "text": f"企业资料确认部署能力 {index}。",
            "citations": ["S1"],
        }
        for index in range(13)
    ]
    with pytest.raises(SolutionDraftError):
        parse(value)


def test_deterministic_assembly_builds_fixed_sections_without_llm_structure():
    from apps.sales.services.solution_schema import SECTION_DEFINITIONS, assemble_solution_draft
    from apps.sales.tests.solution_fakes import typed_analysis

    result = assemble_solution_draft(parse(), typed_analysis())
    assert [(item.key, item.title) for item in result.solution_sections] == list(SECTION_DEFINITIONS)
    assert [statement.text for statement in result.solution_sections[1].statements] == [
        "企业资料确认支持私有化部署。",
    ]
    assert result.solution_sections[2].statements == ()
    assert result.assumptions == ()
    assert 1 <= len(result.executive_summary) <= 8
    assert result.executive_summary == result.solution_sections[0].statements


def test_assembly_uses_server_title_and_derives_gap_assumptions():
    from apps.sales.services.solution_schema import SOLUTION_DRAFT_TITLE, assemble_solution_draft
    from apps.sales.tests.solution_fakes import typed_analysis

    result = assemble_solution_draft(
        parse(),
        typed_analysis(existing_environment="unclear", integration_requirement="unknown"),
    )
    assert result.title == SOLUTION_DRAFT_TITLE
    assert [item.related_fields for item in result.assumptions] == [
        ("existing_environment",), ("integration_requirement",),
    ]
    assert all("Oracle" not in item.text for item in result.assumptions)


def test_assembly_summary_falls_back_to_first_claim_of_each_nonempty_section():
    from apps.sales.services.solution_schema import assemble_solution_draft
    from apps.sales.tests.solution_fakes import typed_analysis

    value = payload()
    value["claims"] = [claim for claim in value["claims"] if claim["section"] != "overall_approach"]
    result = assemble_solution_draft(parse(value), typed_analysis())
    assert result.solution_sections[0].statements == ()
    assert tuple(item.text for item in result.executive_summary) == (
        "企业资料确认支持私有化部署。",
        "OA 集成范围仍需确认。",
        "建议采用私有化部署方向。",
    )
