"""Citation diagnostics must observe the strict parser's actual rejection."""

import json

import pytest

from apps.llm.base import LLMGeneration
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode
from apps.sales.services.real_provider_benchmark import (
    EvaluationPassFailure,
    diagnose_generation_pass,
)
from apps.sales.services.solution_prompt_v2 import (
    parse_solution_v2_implementation_output,
)


def _implementation_payload(citations):
    return json.dumps({
        "proposals": [{
            "placement": {
                "section": "implementation_plan",
                "container_kind": "implementation_phase",
                "container_key": "phase_one",
                "field": "objective",
            },
            "text": "Sensitive customer text must not enter diagnostics.",
            "citations": citations,
        }],
        "structure_relations": [],
    })


def _diagnose(citations, *, allowed=("S1", "S2")):
    with pytest.raises(EvaluationPassFailure) as caught:
        diagnose_generation_pass(
            pass_name="implementation",
            generate=lambda: LLMGeneration(_implementation_payload(citations)),
            parse=lambda content: parse_solution_v2_implementation_output(
                content, allowed_source_labels=allowed,
            ),
            allowed_source_labels=allowed,
            max_proposals=16,
        )
    return caught.value.diagnostic


def _unrelated_rejection(_content):
    raise SolutionDraftError(SolutionDraftErrorCode.INVALID_RESPONSE)


@pytest.mark.parametrize(("citations", "subtype", "offending"), [
    ([], "empty", ()),
    (["S1", "S1"], "duplicate", ("S1",)),
    (["S99"], "not_in_allowlist", ("S99",)),
    ([4], "wrong_type", ("<int>",)),
    (["S 99"], "malformed", ("<redacted>",)),
])
def test_actual_parser_citation_rejection_has_safe_detail(citations, subtype, offending):
    diagnostic = _diagnose(citations)

    assert diagnostic.pass_name == "implementation"
    assert diagnostic.category == "invalid_citation"
    assert diagnostic.citation_failure is not None
    assert diagnostic.citation_failure.allowed_ids == ("S1", "S2")
    assert diagnostic.citation_failure.offending_ids == offending
    assert diagnostic.citation_failure.subtype == subtype
    assert "Sensitive customer text" not in repr(diagnostic)


def test_non_citation_rejection_has_no_citation_detail():
    payload = _implementation_payload(["S1"]).replace('"objective"', '"bogus"')
    with pytest.raises(EvaluationPassFailure) as caught:
        diagnose_generation_pass(
            pass_name="implementation",
            generate=lambda: LLMGeneration(payload),
            parse=lambda content: parse_solution_v2_implementation_output(
                content, allowed_source_labels=("S1", "S2"),
            ),
            allowed_source_labels=("S1", "S2"),
            max_proposals=16,
        )
    assert caught.value.diagnostic.citation_failure is None


def test_valid_citation_does_not_emit_failure():
    result = diagnose_generation_pass(
        pass_name="implementation",
        generate=lambda: LLMGeneration(_implementation_payload(["S1"])),
        parse=lambda content: parse_solution_v2_implementation_output(
            content, allowed_source_labels=("S1", "S2"),
        ),
        allowed_source_labels=("S1", "S2"),
        max_proposals=16,
    )
    assert result.diagnostic.citation_failure is None


def test_citation_detail_is_not_inferred_when_another_parser_rejects():
    with pytest.raises(EvaluationPassFailure) as caught:
        diagnose_generation_pass(
            pass_name="implementation",
            generate=lambda: LLMGeneration(_implementation_payload(["S99"])),
            parse=_unrelated_rejection,
            allowed_source_labels=("S1", "S2"),
            max_proposals=16,
        )
    assert caught.value.diagnostic.citation_failure is None
    assert caught.value.diagnostic.category != "invalid_citation"
