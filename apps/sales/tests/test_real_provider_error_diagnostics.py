"""Offline evaluation diagnostics; provider mapping and requests stay unchanged."""

import json
from importlib import import_module
from types import SimpleNamespace

import httpx2
import openai
import pytest

from apps.llm.base import LLMProviderConfig
from apps.llm.exceptions import LLMErrorCode, LLMProviderError, LLMProviderFailureKind


def _provider(monkeypatch, outcome):
    from apps.llm import openai_compatible

    class Endpoint:
        def create(self, **kwargs):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(openai_compatible, "OpenAI", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=Endpoint()),
    ))
    return openai_compatible.OpenAICompatibleLLMProvider(
        LLMProviderConfig(
            provider_name="openai_compatible", model_name="qwen3-test",
            api_key="API_KEY_DO_NOT_PRINT",
            base_url="https://url-user:URL_PASSWORD@qwen.invalid/v1?token=QUERY_SECRET",
            timeout_seconds=60, max_retries=0, max_output_tokens=1500,
            thinking_enabled=False,
        ),
        supports_enable_thinking=True,
    )


def _sdk_error(error_class, status, code, message):
    request = httpx2.Request(
        "POST", "https://qwen.invalid/v1/chat/completions",
        headers={"Authorization": "Bearer HEADER_SECRET"},
    )
    response = httpx2.Response(status, request=request)
    return error_class("RAW_ERROR_SECRET", response=response, body={
        "error": {"code": code, "message": message},
        "request": "CUSTOMER_TEXT_MUST_NOT_LEAK",
    })


def test_verifier_snapshot_excludes_credentials_query_and_headers(monkeypatch):
    subject = import_module("apps.sales.services.real_provider_benchmark")
    provider = _provider(monkeypatch, None)
    build = getattr(subject, "evaluation_verifier_config_snapshot", None)
    assert callable(build), "Benchmark lacks a safe verifier configuration snapshot"

    result = build(provider, max_concurrency=2)

    assert result == {
        "provider": "openai_compatible", "model": "qwen3-test",
        "base_url": {"host": "qwen.invalid", "path": "/v1"},
        "enable_thinking": False, "timeout": 60, "concurrency": 2,
    }
    assert provider._config.max_retries == 0


@pytest.mark.parametrize(("error_class", "status", "code", "message", "safe_message", "category"), [
    (openai.AuthenticationError, 401, "InvalidApiKey", "Invalid API key.",
     "Provider reported an invalid API key.", "auth_error"),
    (openai.PermissionDeniedError, 403, "DataInspectionFailed",
     "Input may contain inappropriate content. API_KEY_DO_NOT_PRINT HEADER_SECRET",
     "Provider reported a content-policy rejection.", "permission_denied"),
    (openai.PermissionDeniedError, 403, "AllocationQuota.FreeTierOnly",
     "Access denied.", "Provider reported an access-permission rejection.",
     "permission_denied"),
])
def test_error_diagnostic_distinguishes_sdk_classes_without_reclassifying(
    monkeypatch, error_class, status, code, message, safe_message, category,
):
    subject = import_module("apps.sales.services.real_provider_benchmark")
    describe = getattr(subject, "evaluation_llm_provider_error", None)
    assert callable(describe), "Benchmark lacks safe provider error diagnostics"
    sdk_error = _sdk_error(error_class, status, code, message)
    provider = _provider(monkeypatch, sdk_error)

    with pytest.raises(LLMProviderError) as caught:
        provider.generate([{"role": "user", "content": "safe fixed probe"}])
    error = caught.value
    result = describe(error, provider=provider)

    assert error.failure_kind.value == category
    assert error.__context__ is sdk_error
    assert result == {
        "mapped_category": category, "exception_class": "LLMProviderError",
        "sdk_exception_class": error_class.__name__, "http_status": status,
        "provider": "openai_compatible", "model": "qwen3-test",
        "base_url": {"host": "qwen.invalid", "path": "/v1"},
        "provider_error_code": code, "sanitized_provider_message": safe_message,
    }
    rendered = json.dumps(result)
    for secret in ("API_KEY_DO_NOT_PRINT", "URL_PASSWORD", "QUERY_SECRET",
                   "url-user", "HEADER_SECRET", "RAW_ERROR_SECRET",
                   "CUSTOMER_TEXT_MUST_NOT_LEAK", "Authorization"):
        assert secret not in rendered


def test_untrusted_provider_message_and_secret_code_are_not_echoed(monkeypatch):
    subject = import_module("apps.sales.services.real_provider_benchmark")
    describe = getattr(subject, "evaluation_llm_provider_error", None)
    assert callable(describe), "Benchmark lacks safe provider error diagnostics"
    provider = _provider(monkeypatch, _sdk_error(
        openai.PermissionDeniedError, 403, "API_KEY_DO_NOT_PRINT",
        "Authorization: Bearer HEADER_SECRET; customer text and unknown explanation",
    ))
    with pytest.raises(LLMProviderError) as caught:
        provider.generate([{"role": "user", "content": "safe fixed probe"}])

    result = describe(caught.value, provider=provider)

    assert result["provider_error_code"] is None
    assert result["sanitized_provider_message"] is None
    assert "HEADER_SECRET" not in json.dumps(result)


def test_missing_sdk_context_does_not_invent_provider_code_or_message(monkeypatch):
    subject = import_module("apps.sales.services.real_provider_benchmark")
    describe = getattr(subject, "evaluation_llm_provider_error", None)
    assert callable(describe), "Benchmark lacks safe provider error diagnostics"
    error = LLMProviderError(
        LLMErrorCode.LLM_PROVIDER_ERROR, failure_kind=LLMProviderFailureKind.AUTH_ERROR,
    )

    result = describe(error, provider=_provider(monkeypatch, None))

    assert result["sdk_exception_class"] is None
    assert result["http_status"] is None
    assert result["provider_error_code"] is None
    assert result["sanitized_provider_message"] is None


def test_snapshot_reports_absent_thinking_control_as_unknown(monkeypatch):
    subject = import_module("apps.sales.services.real_provider_benchmark")
    build = getattr(subject, "evaluation_verifier_config_snapshot", None)
    assert callable(build), "Benchmark lacks a safe verifier configuration snapshot"
    provider = _provider(monkeypatch, None)
    provider._supports_enable_thinking = False

    assert build(provider, max_concurrency=2)["enable_thinking"] is None
