"""Independent semantic-verifier configuration and factory."""

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
