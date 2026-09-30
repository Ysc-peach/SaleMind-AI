"""Independent semantic-verifier configuration and factory."""

from types import SimpleNamespace

import pytest
from django.test import override_settings


VERIFIER_SETTINGS = {
    "VERIFIER_PROVIDER": "openai_compatible",
    "VERIFIER_MODEL": "gpt-5.6-terra",
    "VERIFIER_API_KEY": "verifier-factory-secret",
    "VERIFIER_BASE_URL": "https://mirror.invalid/v1",
    "VERIFIER_TIMEOUT_SECONDS": 30,
    "VERIFIER_MAX_RETRIES": 0,
    "VERIFIER_MAX_OUTPUT_TOKENS": 1500,
}


@override_settings(**VERIFIER_SETTINGS)
def test_factory_builds_independent_openai_compatible_verifier():
    from apps.llm.openai_compatible import OpenAICompatibleLLMProvider
    from apps.llm.verifier_factory import get_verifier_provider

    provider = get_verifier_provider()

    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.provider_name == "openai_compatible"
    assert provider.model_name == "gpt-5.6-terra"
    assert "verifier-factory-secret" not in repr(provider._config)


@override_settings(**{**VERIFIER_SETTINGS, "VERIFIER_PROVIDER": "unknown"})
def test_factory_rejects_unknown_verifier_provider():
    from apps.llm.exceptions import LLMProviderError
    from apps.llm.verifier_factory import get_verifier_provider

    with pytest.raises(LLMProviderError) as exc:
        get_verifier_provider()

    assert exc.value.code == "unsupported_llm_provider"


@pytest.mark.parametrize("name", ["VERIFIER_MODEL", "VERIFIER_API_KEY", "VERIFIER_BASE_URL"])
def test_factory_rejects_missing_verifier_configuration(settings, name):
    from apps.llm.exceptions import LLMProviderError
    from apps.llm.verifier_factory import get_verifier_provider

    for key, value in VERIFIER_SETTINGS.items():
        setattr(settings, key, value)
    setattr(settings, name, "")

    with pytest.raises(LLMProviderError) as exc:
        get_verifier_provider()

    assert exc.value.code == "llm_not_configured"


@override_settings(**VERIFIER_SETTINGS)
def test_verifier_settings_do_not_replace_generation_settings():
    from django.conf import settings

    assert settings.VERIFIER_PROVIDER == "openai_compatible"
    assert settings.VERIFIER_MODEL == "gpt-5.6-terra"
    assert settings.VERIFIER_TIMEOUT_SECONDS > 0
    assert settings.VERIFIER_MAX_RETRIES == 0
    assert settings.VERIFIER_MAX_OUTPUT_TOKENS > 0
    assert settings.LLM_PROVIDER == "deepseek"
    assert settings.LLM_MODEL == "deepseek-v4-flash"


@override_settings(**{
    **VERIFIER_SETTINGS,
    "VERIFIER_MODEL": "qwen3.8-max-0902",
    "VERIFIER_TIMEOUT_SECONDS": 60,
    "VERIFIER_MAX_RETRIES": 0,
    "VERIFIER_MAX_CONCURRENCY": 2,
})
def test_qwen_verifier_factory_propagates_disabled_thinking_only_to_supported_request(
    monkeypatch,
):
    from django.conf import settings
    from apps.llm import openai_compatible
    from apps.llm.verifier_factory import get_verifier_provider

    endpoint_calls = []
    client_arguments = {}

    def client_factory(**kwargs):
        client_arguments.update(kwargs)

        def create(**request):
            endpoint_calls.append(request)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="verified"))],
            )

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

    monkeypatch.setattr(openai_compatible, "OpenAI", client_factory)

    provider = get_verifier_provider()
    provider.generate([{"role": "user", "content": "packet"}])

    assert client_arguments == {
        "api_key": "verifier-factory-secret",
        "base_url": "https://mirror.invalid/v1",
        "timeout": 60,
        "max_retries": 0,
    }
    assert settings.VERIFIER_MAX_CONCURRENCY == 2
    assert endpoint_calls == [{
        "model": "qwen3.8-max-0902",
        "messages": [{"role": "user", "content": "packet"}],
        "max_tokens": 1500,
        "extra_body": {"enable_thinking": False},
    }]
