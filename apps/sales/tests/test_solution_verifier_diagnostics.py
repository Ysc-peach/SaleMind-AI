"""Evaluation-only diagnostics around individual Qwen verifier calls."""

import json

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.exceptions import (
    LLMErrorCode,
    LLMProviderError,
    LLMProviderFailureKind,
)
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.sales.services.verifier_diagnostics import (
    QwenFailureCategory,
    VerifierEvaluationDiagnostics,
)
from apps.sales.tests.test_solution_proposal_admissibility_v2 import (
    _proposal,
    _verify,
)


class _FailingVerifier(DeterministicFakeLLM):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        raise self.error


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (LLMProviderFailureKind.TIMEOUT, QwenFailureCategory.TIMEOUT),
        (LLMProviderFailureKind.RATE_LIMITED, QwenFailureCategory.RATE_LIMITED),
        (LLMProviderFailureKind.CONNECTION_ERROR, QwenFailureCategory.CONNECTION_ERROR),
        (LLMProviderFailureKind.SERVER_ERROR, QwenFailureCategory.SERVER_ERROR),
        (LLMProviderFailureKind.AUTH_ERROR, QwenFailureCategory.AUTH_ERROR),
        (LLMProviderFailureKind.QUOTA_ERROR, QwenFailureCategory.QUOTA_ERROR),
        (LLMProviderFailureKind.INVALID_RESPONSE, QwenFailureCategory.INVALID_RESPONSE),
        (
            LLMProviderFailureKind.UNKNOWN_PROVIDER_ERROR,
            QwenFailureCategory.UNKNOWN_PROVIDER_ERROR,
        ),
    ],
)
def test_verifier_call_records_safe_provider_failure(kind, expected):
    secret = "QWEN_API_KEY_MUST_NOT_LEAK"
    customer_text = "CUSTOMER_PRIVATE_PROMPT_MUST_NOT_LEAK"
    diagnostics = VerifierEvaluationDiagnostics()
    error = LLMProviderError(
        LLMErrorCode.LLM_PROVIDER_ERROR,
        failure_kind=kind,
        http_status=503,
        request_id="req-safe-456",
    )

    with pytest.raises(LLMProviderError):
        _verify(
            _proposal(customer_text),
            _FailingVerifier(error),
            diagnostics=diagnostics,
        )

    assert len(diagnostics.calls) == 1
    call = diagnostics.calls[0]
    assert call.call_index == 1
    assert call.claim_count == 1
    assert call.attempt_number == 1
    assert call.success is False
    assert call.failure_category is expected
    assert call.http_status == 503
    assert call.provider_request_id == "req-safe-456"
    assert call.started_at <= call.ended_at
    assert call.latency_seconds >= 0
    rendered = repr(call) + json.dumps(call.safe_dict(), ensure_ascii=False)
    assert secret not in rendered
    assert customer_text not in rendered


def test_permission_denied_remains_distinct_in_verifier_call_diagnostics():
    import openai
    from apps.llm.openai_compatible import _safe_provider_error
    from apps.llm.tests.test_qwen_provider_diagnostics import _status_error

    diagnostics = VerifierEvaluationDiagnostics()
    error = _safe_provider_error(_status_error(openai.PermissionDeniedError, 403))

    with pytest.raises(LLMProviderError) as caught:
        _verify(_proposal("safe fixed claim"), _FailingVerifier(error), diagnostics=diagnostics)

    assert caught.value is error
    assert len(diagnostics.calls) == 1
    assert diagnostics.calls[0].failure_category.value == "qwen_permission_denied"
    assert diagnostics.calls[0].http_status == 403
    assert diagnostics.calls[0].attempt_number == 1


def test_malformed_qwen_content_is_classified_as_response_parse_error():
    class MalformedVerifier(DeterministicFakeLLM):
        def generate(self, messages, *, max_output_tokens=None):
            super().generate(messages, max_output_tokens=max_output_tokens)
            return LLMGeneration(content="not-json")

    diagnostics = VerifierEvaluationDiagnostics()

    with pytest.raises(Exception):
        _verify(
            _proposal("建议采用私有化部署。"),
            MalformedVerifier(),
            diagnostics=diagnostics,
        )

    assert len(diagnostics.calls) == 1
    assert diagnostics.calls[0].failure_category is QwenFailureCategory.RESPONSE_PARSE_ERROR
    assert diagnostics.calls[0].success is False


def test_successful_qwen_call_records_no_prompt_or_raw_response():
    class SuccessfulVerifier(DeterministicFakeLLM):
        def generate(self, messages, *, max_output_tokens=None):
            super().generate(messages, max_output_tokens=max_output_tokens)
            return LLMGeneration(
                content=json.dumps({"results": [{
                    "location": "proposals[0]",
                    "decision": "ADMISSIBLE",
                    "atomicity": "ATOMIC",
                }]}),
                provider_request_id="req-success-789",
            )

    diagnostics = VerifierEvaluationDiagnostics()

    _verify(
        _proposal("建议采用私有化部署。"),
        SuccessfulVerifier(),
        diagnostics=diagnostics,
    )

    assert len(diagnostics.calls) == 1
    call = diagnostics.calls[0]
    assert call.success is True
    assert call.failure_category is None
    assert call.provider_request_id == "req-success-789"
    assert set(call.safe_dict()) == {
        "call_index",
        "claim_count",
        "attempt_number",
        "started_at",
        "ended_at",
        "latency_seconds",
        "success",
        "failure_category",
        "http_status",
        "provider_request_id",
    }
