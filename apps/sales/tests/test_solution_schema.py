"""Strict solution JSON and real-source-only citation contracts."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from apps.sales.tests.solution_fakes import solution_payload, typed_analysis


def parse(payload, source_count=3):
    from apps.sales.services.solution_schema import parse_solution_draft

    return parse_solution_draft(json.dumps(payload, ensure_ascii=False), source_count=source_count,
                                analysis=typed_analysis(existing_environment="unclear"))


def test_valid_result_is_typed_immutable_and_preserves_five_sections():
    result = parse(solution_payload())
    assert result.title == "企业知识服务内部草稿"
    assert isinstance(result.solution_sections, tuple)
    assert [s.key for s in result.solution_sections] == ["overall_approach","deployment","data_security","integration","implementation"]
    assert result.assumptions == ()
    assert isinstance(result.executive_summary, tuple)
    assert isinstance(result.solution_sections[0].statements, tuple)
    with pytest.raises(FrozenInstanceError):
        result.title = "changed"


def invalid_payloads():
    original = solution_payload()
    cases = []
    for name in original:
        item = deepcopy(original)
        del item[name]
        cases.append(item)
    for name in ("sources", "confidence", "quotation", "hidden_reasoning"):
        cases.append({**deepcopy(original), name: "forbidden"})
    for field in ("title", "executive_summary"):
        for value in (None, 123, [], " \n"):
            cases.append({**deepcopy(original), field: value})
    for sections in ([], original["solution_sections"][:-1], original["solution_sections"]*2,
                     list(reversed(original["solution_sections"])), {}, None):
        cases.append({**deepcopy(original), "solution_sections": sections})
    for field, value in (("key", "unknown"), ("title", "错误标题"), ("statements", " \n"),
                         ("statements", {}), ("content", "旧版自由文本"), ("source", "S1")):
        item = deepcopy(original)
        item["solution_sections"][0][field] = value
        cases.append(item)
    item = deepcopy(original)
    item["solution_sections"][1] = deepcopy(item["solution_sections"][0])
    cases.append(item)
    assumption = {"text": "环境未确认，不承诺配置。", "related_fields": ["existing_environment"]}
    for value in (None, "text", {}, [""], [None], [1], [assumption]*11,
                  [{"text": ""}], [{"text": " ", "related_fields": ["existing_environment"]}],
                  [{**assumption, "extra": True}]):
        cases.append({**deepcopy(original), "assumptions": value})
    return cases


@pytest.mark.parametrize("payload", invalid_payloads())
def test_schema_rejects_missing_extra_or_malformed_fields(payload):
    from apps.sales.services.solution_errors import SolutionDraftError

    with pytest.raises(SolutionDraftError) as exc:
        parse(payload)
    assert exc.value.code == "solution_draft_invalid_response"


@pytest.mark.parametrize("content", [None, 42, "", " \n", "not JSON secret-api-key", "{} trailing",
    "["*5000, '{"title":NaN}', '{"title":"a","title":"b"}', "正文\n{}",
    "```json\n{}\n```\n说明", "```\n{}\n```"])
def test_json_errors_are_safe_and_not_repaired(content, caplog):
    from apps.sales.services.solution_errors import SolutionDraftError
    from apps.sales.services.solution_schema import parse_solution_draft

    with pytest.raises(SolutionDraftError) as exc:
        parse_solution_draft(content, source_count=3, analysis=typed_analysis())
    assert exc.value.code == "solution_draft_invalid_response"
    assert "secret-api-key" not in str(exc.value) + caplog.text
    assert exc.value.__cause__ is None


def test_single_whole_response_json_fence_and_empty_lists_are_supported():
    from apps.sales.services.solution_schema import parse_solution_draft

    payload = solution_payload()
    result = parse_solution_draft("```json\n"+json.dumps(payload, ensure_ascii=False)+"\n```", source_count=1,
                                  analysis=typed_analysis())
    assert result.assumptions == ()


@pytest.mark.parametrize("citation,expected", [
    ("[S1]", "[S1]"), ("[S1][S2]", "[S1][S2]"), ("（S1）", "[S1]"), ("(S1)", "[S1]"),
    ("[S1, S2]", "[S1][S2]"), ("（S1、S2）", "[S1][S2]"), ("(S1, S2)", "[S1][S2]"),
])
def test_phase4_real_citations_still_normalize_without_changing_prose(citation, expected):
    from apps.rag.services.answering import normalize_citations

    assert normalize_citations("普通正文（部署待确认）。"+citation, source_count=3) == "普通正文（部署待确认）。"+expected


@pytest.mark.parametrize("location", ["executive_summary", "section", "assumptions", "title"])
@pytest.mark.parametrize("citation", ["[S9]", "（S9）", "(S1, S9)", "[S01]", "[S1, S9]"])
def test_unknown_citation_in_any_text_field_is_rejected(location, citation):
    from apps.sales.services.solution_errors import SolutionDraftError

    payload = solution_payload()
    if location == "section":
        payload["solution_sections"][2]["statements"][0]["text"] += citation
    elif location == "assumptions":
        payload[location].append({"text": "测试"+citation, "related_fields": ["existing_environment"]})
    elif location == "executive_summary":
        payload[location][0]["text"] += citation
    else:
        payload[location] += citation
    with pytest.raises(SolutionDraftError) as exc:
        parse(payload)
    assert exc.value.code == "solution_draft_invalid_response"


def test_leading_zero_is_not_silently_converted_to_valid_source():
    from apps.rag.services.answering import normalize_citations

    assert normalize_citations("[S01] （S01） S01", source_count=3) == "[S01] （S01） S01"


def test_shared_normalization_preserves_unbounded_unknown_label_without_integer_parsing():
    from apps.rag.services.answering import normalize_citations

    text = "[S" + "9"*5000 + "]"
    assert normalize_citations(text, source_count=3) == text


@pytest.mark.parametrize("citation", ["[S9 ]", "[ S9]", "(S1, S9 )", "[S1，S9]", "（ S01 ）"])
def test_complete_citation_groups_cannot_hide_unknown_labels_with_spacing(citation):
    from apps.sales.services.solution_errors import SolutionDraftError

    payload = solution_payload()
    payload["executive_summary"][0]["text"] += citation
    with pytest.raises(SolutionDraftError):
        parse(payload)


@pytest.mark.parametrize("citation,expected", [("[ S1 ]", "[S1]"), ("（ S1、S2 ）", "[S1][S2]"), ("[S1，S2]", "[S1][S2]")])
def test_phase4_complete_real_groups_with_spacing_preserve_authority(citation, expected):
    from apps.rag.services.answering import normalize_citations

    assert normalize_citations("有证据。"+citation, source_count=3) == "有证据。"+expected
