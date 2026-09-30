"""Secret-safe failure metadata for the Qwen-compatible verifier boundary."""

from types import SimpleNamespace

import httpx2
import openai
import pytest

from apps.llm.base import LLMProviderConfig
from apps.llm.exceptions import (
    LLMErrorCode,
    LLMProviderError,
    LLMProviderFailureKind,
)


def _provider(monkeypatch, outcome):
    from apps.llm import openai_compatible

    class Endpoint:
        def create(self, **kwargs):
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    monkeypatch.setattr(
        openai_compatible,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=Endpoint()),
        ),
    )
    return openai_compatible.OpenAICompatibleLLMProvider(
        LLMProviderConfig(
            provider_name="openai_compatible",
            model_name="qwen-test-model",
            api_key="QWEN_API_KEY_MUST_NOT_LEAK",
            base_url="https://qwen.invalid/v1",
            timeout_seconds=60,
            max_retries=0,
            max_output_tokens=1500,
            thinking_enabled=False,
        )
    )


def _request():
    return httpx2.Request("POST", "https://qwen.invalid/v1/chat/completions")


def _status_error(error_class, status, *, code=None, request_id="req-safe-123"):
    request = _request()
    body = {"error": {"code": code or "provider_error"}}
    response = httpx2.Response(
        status,
        request=request,
        headers={"x-request-id": request_id},
        json=body,
    )
    return error_class("provider failure", response=response, body=body)


@pytest.mark.parametrize(
    ("error", "expected_kind", "expected_status"),
    [
        (
            openai.APITimeoutError(_request()),
            LLMProviderFailureKind.TIMEOUT,
            None,
        ),
        (
            openai.APIConnectionError(request=_request()),
            LLMProviderFailureKind.CONNECTION_ERROR,
            None,
        ),
        (
            _status_error(openai.RateLimitError, 429),
            LLMProviderFailureKind.RATE_LIMITED,
            429,
        ),
        (
            _status_error(
                openai.RateLimitError,
                429,
                code="insufficient_quota",
            ),
            LLMProviderFailureKind.QUOTA_ERROR,
            429,
        ),
        (
            _status_error(openai.InternalServerError, 503),
            LLMProviderFailureKind.SERVER_ERROR,
            503,
        ),
        (
            _status_error(openai.AuthenticationError, 401),
            LLMProviderFailureKind.AUTH_ERROR,
            401,
        ),
        (
            _status_error(openai.PermissionDeniedError, 403),
            LLMProviderFailureKind.AUTH_ERROR,
            403,
        ),
        (
            _status_error(openai.BadRequestError, 400),
            LLMProviderFailureKind.UNKNOWN_PROVIDER_ERROR,
            400,
        ),
    ],
)
def test_openai_compatible_failure_preserves_safe_underlying_category(
    monkeypatch,
    error,
    expected_kind,
    expected_status,
):
    provider = _provider(monkeypatch, error)

    with pytest.raises(LLMProviderError) as caught:
        provider.generate([{"role": "user", "content": "safe probe"}])

    assert caught.value.code == LLMErrorCode.LLM_PROVIDER_ERROR.value
    assert caught.value.failure_kind is expected_kind
    assert caught.value.http_status == expected_status
    assert caught.value.request_id == (
        "req-safe-123" if expected_status is not None else None
    )
    rendered = repr(caught.value) + str(caught.value)
    assert "QWEN_API_KEY_MUST_NOT_LEAK" not in rendered
    assert "safe probe" not in rendered


def test_openai_compatible_invalid_response_has_distinct_safe_category(monkeypatch):
    provider = _provider(monkeypatch, SimpleNamespace(choices=[]))

    with pytest.raises(LLMProviderError) as caught:
        provider.generate([{"role": "user", "content": "safe probe"}])

    assert caught.value.code == LLMErrorCode.LLM_INVALID_RESPONSE.value
    assert caught.value.failure_kind is LLMProviderFailureKind.INVALID_RESPONSE


def test_success_response_preserves_only_safe_request_metadata(monkeypatch):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="verified"))],
        _request_id="req-safe-success",
    )
    provider = _provider(monkeypatch, response)

    generation = provider.generate([{"role": "user", "content": "safe probe"}])

    assert generation.content == "verified"
    assert generation.provider_request_id == "req-safe-success"
