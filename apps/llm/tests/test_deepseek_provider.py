"""DeepSeek provider request, validation, and response contracts."""

import logging
from types import SimpleNamespace

import pytest
from openai import OpenAIError

from apps.llm.base import LLMProviderConfig


class _ChatCompletionsEndpoint:
    def __init__(self, response_or_error):
        self._response_or_error = response_or_error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response_or_error, Exception):
            raise self._response_or_error
        return self._response_or_error


def _response(content="SalesMind LLM connected", *, reasoning_content=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning_content,
                )
            )
        ]
    )


def _build_provider(monkeypatch, response_or_error=None):
    from apps.llm import deepseek

    endpoint = _ChatCompletionsEndpoint(
        _response() if response_or_error is None else response_or_error
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=endpoint),
    )
    client_arguments: dict = {}

    def client_factory(**kwargs):
        client_arguments.update(kwargs)
        return client

    monkeypatch.setattr(deepseek, "OpenAI", client_factory)
    config = LLMProviderConfig(
        provider_name="deepseek",
        model_name="deepseek-v4-flash",
        api_key="provider-test-secret",
        base_url="https://api.deepseek.com",
        timeout_seconds=17,
        max_retries=2,
        max_output_tokens=321,
        thinking_enabled=False,
    )
    provider = deepseek.DeepSeekLLMProvider(config)
    return provider, endpoint, client_arguments


def test_provider_implements_the_llm_interface(monkeypatch):
    from apps.llm.base import LLMProvider

    provider, _, _ = _build_provider(monkeypatch)

    assert isinstance(provider, LLMProvider)
    assert callable(provider.generate)


def test_provider_constructs_sdk_client_only_from_configuration(monkeypatch):
    _, _, client_arguments = _build_provider(monkeypatch)

    assert client_arguments == {
        "api_key": "provider-test-secret",
        "base_url": "https://api.deepseek.com",
        "timeout": 17,
        "max_retries": 2,
    }


def test_generate_passes_normalized_messages_and_explicit_non_thinking(monkeypatch):
    provider, endpoint, _ = _build_provider(monkeypatch)
    messages = [
        {"role": "system", "content": "  You are a presales assistant.  "},
        {"role": "user", "content": "  Summarize the requirement.  "},
        {"role": "assistant", "content": "  Previous safe answer.  "},
    ]

    result = provider.generate(messages)

    assert result.content == "SalesMind LLM connected"
    assert endpoint.calls == [
        {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "You are a presales assistant."},
                {"role": "user", "content": "Summarize the requirement."},
                {"role": "assistant", "content": "Previous safe answer."},
            ],
            "max_tokens": 321,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    ]


def test_reasoning_content_is_not_exposed_by_generation_result(monkeypatch):
    secret_reasoning = "private chain of thought"
    provider, _, _ = _build_provider(
        monkeypatch,
        _response("final answer", reasoning_content=secret_reasoning),
    )

    result = provider.generate([{"role": "user", "content": "question"}])

    assert result.content == "final answer"
    assert not hasattr(result, "reasoning_content")
    assert secret_reasoning not in repr(result)


@pytest.mark.parametrize(
    "messages",
    [
        [],
        {},
        "not-a-message-sequence",
        [{"role": "tool", "content": "result"}],
        [{"role": "user", "content": ""}],
        [{"role": "user", "content": "  \n"}],
        [{"role": "user", "content": 123}],
        [{"content": "missing role"}],
        [{"role": "user"}],
        ["not-a-message"],
    ],
    ids=[
        "empty-list",
        "mapping-not-sequence",
        "string-not-sequence",
        "invalid-role",
        "empty-content",
        "blank-content",
        "non-string-content",
        "missing-role",
        "missing-content",
        "non-mapping-message",
    ],
)
def test_invalid_messages_are_rejected_before_sdk_request(monkeypatch, messages):
    from apps.llm.exceptions import LLMProviderError

    provider, endpoint, _ = _build_provider(monkeypatch)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate(messages)

    assert exc_info.value.code == "llm_invalid_response"
    assert endpoint.calls == []


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(),
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=None),
        SimpleNamespace(choices=[SimpleNamespace()]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())]),
        _response(None),
        _response(""),
        _response("  \n"),
        _response(123),
    ],
    ids=[
        "missing-choices",
        "empty-choices",
        "none-choices",
        "missing-message",
        "missing-content",
        "none-content",
        "empty-content",
        "blank-content",
        "non-string-content",
    ],
)
def test_malformed_or_empty_response_is_rejected(monkeypatch, response):
    from apps.llm.exceptions import LLMProviderError

    provider, _, _ = _build_provider(monkeypatch, response)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": "question"}])

    assert exc_info.value.code == "llm_invalid_response"


def test_sdk_error_is_converted_without_sensitive_details(monkeypatch, caplog):
    from apps.llm.exceptions import LLMProviderError

    secret = "provider-test-secret"
    enterprise_text = "confidential customer strategy"
    provider, _, _ = _build_provider(
        monkeypatch,
        OpenAIError(f"bad key {secret}; rejected {enterprise_text}"),
    )
    caplog.set_level(logging.INFO)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([{"role": "user", "content": enterprise_text}])

    rendered_error = str(exc_info.value)
    assert exc_info.value.code == "llm_provider_error"
    assert secret not in rendered_error
    assert enterprise_text not in rendered_error
    assert secret not in caplog.text
    assert enterprise_text not in caplog.text


@pytest.mark.django_db
def test_generate_performs_no_database_queries(monkeypatch, django_assert_num_queries):
    provider, _, _ = _build_provider(monkeypatch)

    with django_assert_num_queries(0):
        result = provider.generate([{"role": "user", "content": "question"}])

    assert result.content == "SalesMind LLM connected"
