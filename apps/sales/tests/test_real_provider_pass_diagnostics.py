"""Evaluation-only attribution of real-provider V2 pass failures."""

import importlib
import json
from types import SimpleNamespace

import pytest

from apps.llm.base import LLMGeneration
from apps.sales.models import SolutionDraftRecord
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode
from apps.sales.services.solution_prompt_v2 import parse_solution_v2_core_output
from apps.sales.tests.test_solution_semantic_ir_v2 import core_ir


def _subject():
    return importlib.import_module("apps.sales.services.real_provider_benchmark")


def _reject(_content):
    raise SolutionDraftError(SolutionDraftErrorCode.INVALID_RESPONSE)


def _diagnose_core_ir(payload):
    subject = _subject()
    return subject.diagnose_generation_pass(
        pass_name="core",
        generate=lambda: LLMGeneration(json.dumps(payload)),
        parse=lambda content: parse_solution_v2_core_output(
            content, allowed_source_labels=("S1",),
        ),
        allowed_source_labels=("S1",),
        max_proposals=46,
    )


def test_valid_core_semantic_ir_passes_evaluation_diagnostics():
    result = _diagnose_core_ir(core_ir())
    assert result.diagnostic.strict_parse_succeeded is True
    assert result.diagnostic.category is None


@pytest.mark.parametrize(("field", "category"), (
    ("dependencies", "dangling_dependency"),
    ("request_flows", "dangling_request_flow"),
    ("data_flows", "dangling_data_flow"),
))
def test_core_semantic_ir_dangling_edge_uses_actual_parser_rejection(field, category):
    payload = core_ir()
    payload["architecture"][field][0]["to"] = "missing"
    with pytest.raises(_subject().EvaluationPassFailure) as caught:
        _diagnose_core_ir(payload)
    diagnostic = caught.value.diagnostic
    assert diagnostic.category == category
    assert diagnostic.json_path == f"$.architecture.{field}[0].to"
    assert diagnostic.expected == "existing architecture component ref"
    assert diagnostic.actual == "unknown local ref"


def test_core_semantic_ir_invalid_local_ref_has_own_category():
    payload = core_ir()
    payload["architecture"]["components"][0]["ref"] = "Bad Ref"
    with pytest.raises(_subject().EvaluationPassFailure) as caught:
        _diagnose_core_ir(payload)
    assert caught.value.diagnostic.category == "invalid_local_ref"
    assert caught.value.diagnostic.json_path == "$.architecture.components[0].ref"


def test_core_semantic_ir_invalid_citation_is_attributed_to_claim_path():
    payload = core_ir()
    payload["architecture"]["components"][0]["identity"]["citations"] = ["S9"]
    with pytest.raises(_subject().EvaluationPassFailure) as caught:
        _diagnose_core_ir(payload)
    diagnostic = caught.value.diagnostic
    assert diagnostic.category == "invalid_citation"
    assert diagnostic.json_path == "$.architecture.components[0].identity.citations"
    assert diagnostic.citation_failure.subtype == "not_in_allowlist"


def test_core_semantic_ir_missing_field_is_not_misreported_as_legacy_proposals():
    payload = core_ir()
    del payload["architecture"]["components"][0]["identity"]
    with pytest.raises(_subject().EvaluationPassFailure) as caught:
        _diagnose_core_ir(payload)
    diagnostic = caught.value.diagnostic
    assert diagnostic.category == "missing_required_key"
    assert diagnostic.json_path == "$.architecture.components[0].identity"
    assert diagnostic.expected == "required key present"
    assert diagnostic.actual == "missing"


def test_core_semantic_ir_missing_version_is_attributed_to_semantic_contract():
    payload = core_ir()
    del payload["ir_version"]
    with pytest.raises(_subject().EvaluationPassFailure) as caught:
        _diagnose_core_ir(payload)
    assert caught.value.diagnostic.category == "missing_required_key"
    assert caught.value.diagnostic.json_path == "$.ir_version"


@pytest.mark.parametrize(("mutate", "category", "path"), (
    (lambda p: p["architecture"]["components"][0].update({"unexpected": 1}),
     "unknown_key", "$.architecture.components[0].unexpected"),
    (lambda p: p["architecture"]["components"][0].update({"responsibilities": "not-an-array"}),
     "wrong_type", "$.architecture.components[0].responsibilities"),
    (lambda p: p["architecture"]["components"][0]["identity"].update(
        {"related_requirement_fields": ["not_a_dimension"]}),
     "invalid_requirement_link", "$.architecture.components[0].identity.related_requirement_fields"),
    (lambda p: p["architecture"]["components"][0].update({"rationale": []}),
     "component_cardinality", "$.architecture.components[0].rationale"),
    (lambda p: p["proposed_solution"].extend(
        {"text": f"Proposal {n}", "citations": ["S1"],
         "related_requirement_fields": []} for n in range(37)),
     "local_cardinality", "$.proposed_solution"),
))
def test_core_semantic_ir_failure_categories_follow_rejecting_branch(mutate, category, path):
    payload = core_ir()
    mutate(payload)
    with pytest.raises(_subject().EvaluationPassFailure) as caught:
        _diagnose_core_ir(payload)
    assert caught.value.diagnostic.category == category
    assert caught.value.diagnostic.json_path == path


def test_core_semantic_ir_malformed_json_is_distinct_from_contract_failure():
    subject = _subject()
    with pytest.raises(subject.EvaluationPassFailure) as caught:
        subject.diagnose_generation_pass(
            pass_name="core", generate=lambda: LLMGeneration('{"ir_version":"semantic_v1",'),
            parse=lambda content: parse_solution_v2_core_output(
                content, allowed_source_labels=("S1",)),
            allowed_source_labels=("S1",), max_proposals=28,
        )
    assert caught.value.diagnostic.category == "malformed_json"
    assert caught.value.diagnostic.json_path == "$"


@pytest.mark.parametrize("pass_name", ("core", "implementation", "assurance"))
def test_strict_parser_failure_is_attributed_to_its_pass(pass_name):
    subject = _subject()
    payload = ('{"proposals":[{"placement":{"section":"proposed_solution",'
               '"container_kind":"root","container_key":null,"field":"overview"},'
               '"text":"safe fixture","citations":["S1"],"unexpected":true}],'
               '"structure_relations":[]}')

    with pytest.raises(subject.EvaluationPassFailure) as caught:
        subject.diagnose_generation_pass(
            pass_name=pass_name,
            generate=lambda: LLMGeneration(payload),
            parse=_reject,
            allowed_source_labels=("S1",),
            max_proposals={"core": 28, "implementation": 16, "assurance": 20}[pass_name],
        )

    diagnostic = caught.value.diagnostic
    assert diagnostic.pass_name == pass_name
    assert diagnostic.provider_completed is True
    assert diagnostic.json_parse_succeeded is True
    assert diagnostic.strict_parse_succeeded is False
    assert diagnostic.proposal_count == 1
    assert diagnostic.category == "unknown_key"


def test_malformed_json_preserves_safe_category_without_leaking_raw(capsys):
    subject = _subject()
    raw = '{"private_marker":"DO_NOT_LOG","proposals":['

    with pytest.raises(subject.EvaluationPassFailure) as caught:
        subject.diagnose_generation_pass(
            pass_name="core",
            generate=lambda: LLMGeneration(raw),
            parse=_reject,
            allowed_source_labels=("S1",),
            max_proposals=28,
        )

    diagnostic = caught.value.diagnostic
    assert diagnostic.category == "malformed_json"
    assert diagnostic.json_parse_succeeded is False
    assert diagnostic.proposal_count is None
    assert "DO_NOT_LOG" not in repr(caught.value)
    assert "DO_NOT_LOG" not in repr(diagnostic)
    assert "DO_NOT_LOG" not in capsys.readouterr().out


@pytest.mark.django_db
def test_rejected_evaluation_pass_creates_no_solution():
    subject = _subject()
    before = SolutionDraftRecord.objects.count()

    with pytest.raises(subject.EvaluationPassFailure):
        subject.diagnose_generation_pass(
            pass_name="assurance",
        generate=lambda: LLMGeneration('{"proposals":[{"unexpected":true}]}'),
            parse=_reject,
            allowed_source_labels=("S1",),
            max_proposals=20,
        )

    assert SolutionDraftRecord.objects.count() == before


def test_valid_evaluation_pass_returns_value_and_safe_timing():
    subject = _subject()
    payload = '{"proposals":[],"structure_relations":[]}'
    sentinel = object()

    result = subject.diagnose_generation_pass(
        pass_name="core",
        generate=lambda: LLMGeneration(payload),
        parse=lambda _content: sentinel,
        allowed_source_labels=("S1",),
        max_proposals=28,
    )

    assert result.value is sentinel
    assert result.diagnostic.pass_name == "core"
    assert result.diagnostic.provider_completed is True
    assert result.diagnostic.json_parse_succeeded is True
    assert result.diagnostic.strict_parse_succeeded is True
    assert result.diagnostic.proposal_count == 0
    assert result.diagnostic.category is None
    assert result.diagnostic.latency_seconds >= 0


def test_missing_required_proposal_key_has_distinct_safe_category():
    subject = _subject()
    payload = '{"proposals":[{"text":"safe fixture"}],"structure_relations":[]}'

    with pytest.raises(subject.EvaluationPassFailure) as caught:
        subject.diagnose_generation_pass(
            pass_name="core",
            generate=lambda: LLMGeneration(payload),
            parse=_reject,
            allowed_source_labels=("S1",),
            max_proposals=28,
        )

    assert caught.value.diagnostic.category == "missing_required_key"


def test_unknown_placement_enum_has_distinct_safe_category():
    subject = _subject()
    payload = ('{"proposals":[{"placement":{"section":"not_a_section",'
               '"container_kind":"root","container_key":null,"field":"overview"},'
               '"text":"safe fixture","citations":["S1"]}],'
               '"structure_relations":[]}')

    with pytest.raises(subject.EvaluationPassFailure) as caught:
        subject.diagnose_generation_pass(
            pass_name="core",
            generate=lambda: LLMGeneration(payload),
            parse=_reject,
            allowed_source_labels=("S1",),
            max_proposals=28,
        )

    assert caught.value.diagnostic.category == "invalid_enum"


def test_length_finish_distinguishes_truncation_from_generic_malformed_json():
    subject = _subject()

    with pytest.raises(subject.EvaluationPassFailure) as caught:
        subject.diagnose_generation_pass(
            pass_name="assurance",
            generate=lambda: SimpleNamespace(
                content='{"proposals":[', finish_reason="length",
                prompt_tokens=700, completion_tokens=6000,
            ),
            parse=_reject,
            allowed_source_labels=("S1",),
            max_proposals=20,
        )

    diagnostic = caught.value.diagnostic
    assert diagnostic.category == "truncation_or_length_finish"
    assert diagnostic.finish_reason == "length"
    assert diagnostic.prompt_tokens == 700
    assert diagnostic.completion_tokens == 6000
