"""Generic OpenAI-compatible chat-completions provider contract."""

from types import SimpleNamespace

from apps.llm.base import LLMProviderConfig


class _Endpoint:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="verified"))],
        )


def test_openai_compatible_provider_uses_chat_completions_without_deepseek_options(monkeypatch):
    from apps.llm import openai_compatible

    endpoint = _Endpoint()
    client_arguments = {}

    def client_factory(**kwargs):
        client_arguments.update(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=endpoint))

    monkeypatch.setattr(openai_compatible, "OpenAI", client_factory)
    provider = openai_compatible.OpenAICompatibleLLMProvider(LLMProviderConfig(
        provider_name="openai_compatible",
        model_name="gpt-5.6-terra",
        api_key="verifier-test-secret",
        base_url="https://mirror.invalid/v1",
        timeout_seconds=23,
        max_retries=0,
        max_output_tokens=1500,
        thinking_enabled=False,
    ))

    result = provider.generate([
        {"role": "system", "content": "  verifier contract  "},
        {"role": "user", "content": "  synthetic packet  "},
    ])

    assert result.content == "verified"
    assert client_arguments == {
        "api_key": "verifier-test-secret",
        "base_url": "https://mirror.invalid/v1",
        "timeout": 23,
        "max_retries": 0,
    }
    assert endpoint.calls == [{
        "model": "gpt-5.6-terra",
        "messages": [
            {"role": "system", "content": "verifier contract"},
            {"role": "user", "content": "synthetic packet"},
        ],
        "max_tokens": 1500,
    }]


def test_openai_compatible_provider_honors_per_call_output_budget(monkeypatch):
    from apps.llm import openai_compatible

    endpoint = _Endpoint()
    monkeypatch.setattr(
        openai_compatible,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=endpoint)),
    )
    provider = openai_compatible.OpenAICompatibleLLMProvider(LLMProviderConfig(
        provider_name="openai_compatible", model_name="gpt-5.6-terra",
        api_key="secret", base_url="https://mirror.invalid/v1", timeout_seconds=10,
        max_retries=0, max_output_tokens=1500, thinking_enabled=False,
    ))

    provider.generate([{"role": "user", "content": "packet"}], max_output_tokens=321)

    assert endpoint.calls[0]["max_tokens"] == 321


def test_qwen_capability_sends_explicit_disabled_thinking_without_changing_request(monkeypatch):
    from apps.llm import openai_compatible

    endpoint = _Endpoint()
    monkeypatch.setattr(
        openai_compatible,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=endpoint)),
    )
    provider = openai_compatible.OpenAICompatibleLLMProvider(
        LLMProviderConfig(
            provider_name="openai_compatible",
            model_name="qwen3.8-max-0902",
            api_key="secret",
            base_url="https://dashscope-compatible.invalid/v1",
            timeout_seconds=60,
            max_retries=0,
            max_output_tokens=1500,
            thinking_enabled=False,
        ),
        supports_enable_thinking=True,
    )

    result = provider.generate([
        {"role": "system", "content": "  verifier contract  "},
        {"role": "user", "content": "  synthetic packet  "},
    ])

    assert result.content == "verified"
    assert endpoint.calls == [{
        "model": "qwen3.8-max-0902",
        "messages": [
            {"role": "system", "content": "verifier contract"},
            {"role": "user", "content": "synthetic packet"},
        ],
        "max_tokens": 1500,
        "extra_body": {"enable_thinking": False},
    }]


def test_qwen_capability_preserves_provider_default_when_thinking_is_unspecified(monkeypatch):
    from apps.llm import openai_compatible

    endpoint = _Endpoint()
    monkeypatch.setattr(
        openai_compatible,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=endpoint)),
    )
    provider = openai_compatible.OpenAICompatibleLLMProvider(
        LLMProviderConfig(
            provider_name="openai_compatible",
            model_name="qwen3.8-max-0902",
            api_key="secret",
            base_url="https://dashscope-compatible.invalid/v1",
            timeout_seconds=60,
            max_retries=0,
            max_output_tokens=1500,
            thinking_enabled=None,
        ),
        supports_enable_thinking=True,
    )

    provider.generate([{"role": "user", "content": "packet"}])

    assert endpoint.calls == [{
        "model": "qwen3.8-max-0902",
        "messages": [{"role": "user", "content": "packet"}],
        "max_tokens": 1500,
    }]
