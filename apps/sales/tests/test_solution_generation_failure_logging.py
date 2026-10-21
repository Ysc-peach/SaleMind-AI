"""Failure logs describe real rejections, never model text or exception causes."""

import json
import logging

import pytest

from apps.llm.base import LLMGeneration, LLMProvider
from apps.llm.exceptions import LLMErrorCode, LLMProviderError, LLMProviderFailureKind
from apps.sales.services.solution_draft import _generate_and_parse_v2_pass
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services.solution_prompt_v2 import parse_solution_v2_core_output
from apps.sales.tests.test_solution_semantic_ir_v2 import core_ir


class JSONFixtureProvider(LLMProvider):
    provider_name = "fixture"
    model_name = "fixture"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0

    def generate(self, messages, *, max_output_tokens=None):
        raise AssertionError("Expected the production JSON request path")

    def generate_json(self, messages, *, max_output_tokens=None):
        self.calls += 1
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return output


def parse_core(content):
    return parse_solution_v2_core_output(content, allowed_source_labels=("S1",))


@pytest.mark.parametrize("phase", ("core", "implementation", "assurance"))
def test_actual_parser_rejection_logs_phase_attempt_and_metadata_without_raw(caplog, phase):
    provider = JSONFixtureProvider([
        LLMGeneration('{"private-customer-output":', finish_reason="length",
                      prompt_tokens=200, completion_tokens=6000),
        LLMGeneration(json.dumps(core_ir())),
    ])
    with caplog.at_level(logging.WARNING):
        result = _generate_and_parse_v2_pass(provider, (), parse_core, pass_name=phase)
    failures = [r.solution_generation_failure for r in caplog.records
                if hasattr(r, "solution_generation_failure")]
    assert len(failures) == 1
    assert failures[0] == {
        "phase": phase, "attempt": 1, "exception_class": "SolutionContractError",
        "code": "solution_draft_invalid_response", "category": "malformed_json",
        "json_path": "$", "expected": "complete unique-key JSON", "actual": "malformed JSON",
        "finish_reason": "length", "prompt_tokens": 200, "completion_tokens": 6000,
    }
    assert result.proposals
    assert provider.calls == 2
    assert "private-customer-output" not in caplog.text + repr(failures)
    assert all(r.exc_info is None for r in caplog.records)


def test_unknown_provider_key_is_redacted_but_formal_failure_stays_unchanged(caplog):
    payload = core_ir()
    payload["architecture"]["components"][0]["private_customer_secret"] = "private raw text"
    provider = JSONFixtureProvider([LLMGeneration(json.dumps(payload))] * 2)
    with caplog.at_level(logging.WARNING), pytest.raises(SolutionDraftError) as caught:
        _generate_and_parse_v2_pass(provider, (), parse_core, pass_name="core")
    failures = [r.solution_generation_failure for r in caplog.records
                if hasattr(r, "solution_generation_failure")]
    assert [f["attempt"] for f in failures] == [1, 2]
    assert failures[-1]["category"] == "unknown_key"
    assert failures[-1]["json_path"] == "$.architecture.components[0].<key>"
    assert caught.value.contract_failure.json_path == "$.architecture.components[0].private_customer_secret"
    assert provider.calls == 2
    assert "private_customer_secret" not in caplog.text + repr(failures)
    assert "private raw text" not in caplog.text + repr(failures)


def test_provider_error_log_preserves_category_not_cause_and_does_not_regenerate(caplog):
    error = LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR,
                            failure_kind=LLMProviderFailureKind.PERMISSION_DENIED, http_status=403)
    error.__cause__ = RuntimeError("Authorization Bearer private-api-key")
    provider = JSONFixtureProvider([error])
    with caplog.at_level(logging.WARNING), pytest.raises(LLMProviderError) as caught:
        _generate_and_parse_v2_pass(provider, (), parse_core, pass_name="implementation")
    failure = next(r.solution_generation_failure for r in caplog.records
                   if hasattr(r, "solution_generation_failure"))
    assert failure["phase"] == "implementation"
    assert failure["category"] == "permission_denied"
    assert failure["http_status"] == 403
    assert caught.value is error
    assert provider.calls == 1
    assert "private-api-key" not in caplog.text + repr(failure)
    assert all(r.exc_info is None for r in caplog.records)


@pytest.mark.parametrize("citations,subtype,offending", [
    (["S9"], "not_in_allowlist", ("S9",)),
    ([], "empty", ()),
    (["S1", "S1"], "duplicate", ("S1",)),
    ([{"private_customer_secret": "private raw text"}], "wrong_type", ("<dict>",)),
    (["private_customer_secret"], "malformed", ("<redacted>",)),
])
def test_citation_logs_forward_only_sanitized_formal_parser_ids(caplog, citations, subtype, offending):
    payload = core_ir()
    payload["proposed_solution"][0]["citations"] = citations
    provider = JSONFixtureProvider([
        LLMGeneration(json.dumps(payload)), LLMGeneration(json.dumps(core_ir())),
    ])
    with caplog.at_level(logging.WARNING):
        result = _generate_and_parse_v2_pass(provider, (), parse_core, pass_name="core")
    diagnostic = next(r.solution_generation_failure for r in caplog.records
                      if hasattr(r, "solution_generation_failure"))
    assert diagnostic["category"] == "invalid_citation"
    assert diagnostic["json_path"] == "$.proposed_solution[0].citations"
    assert diagnostic["citation_subtype"] == subtype
    assert diagnostic["allowed_ids"] == ("S1",)
    assert diagnostic["offending_ids"] == offending
    assert diagnostic["attempt"] == 1
    assert result.proposals
    assert provider.calls == 2
    assert "private_customer_secret" not in caplog.text + repr(diagnostic)
    assert "private raw text" not in caplog.text + repr(diagnostic)
    assert all(r.exc_info is None for r in caplog.records)
