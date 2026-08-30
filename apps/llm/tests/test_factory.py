"""LLM provider abstraction and factory contracts."""

import pytest
from django.test import override_settings


VALID_SETTINGS = {
    "LLM_PROVIDER": "deepseek",
    "LLM_MODEL": "deepseek-v4-flash",
    "LLM_API_KEY": "factory-test-secret",
    "LLM_BASE_URL": "https://api.deepseek.com",
    "LLM_TIMEOUT_SECONDS": 30,
    "LLM_MAX_RETRIES": 2,
    "LLM_MAX_OUTPUT_TOKENS": 512,
    "LLM_THINKING_ENABLED": False,
}


@override_settings(**VALID_SETTINGS)
def test_factory_creates_configured_deepseek_provider():
    from apps.llm import get_llm_provider
    from apps.llm.deepseek import DeepSeekLLMProvider

    provider = get_llm_provider()

    assert isinstance(provider, DeepSeekLLMProvider)
    assert provider.provider_name == "deepseek"
    assert provider.model_name == "deepseek-v4-flash"
    assert provider.thinking_enabled is False


@override_settings(**{**VALID_SETTINGS, "LLM_PROVIDER": "unknown"})
def test_factory_rejects_unknown_provider_without_fallback():
    from apps.llm import get_llm_provider
    from apps.llm.exceptions import LLMProviderError

    with pytest.raises(LLMProviderError) as exc_info:
        get_llm_provider()

    assert exc_info.value.code == "unsupported_llm_provider"


@override_settings(
    **{
        **VALID_SETTINGS,
        "LLM_PROVIDER": "unknown",
        "LLM_MODEL": "",
        "LLM_API_KEY": "",
    }
)
def test_unknown_provider_error_precedes_missing_provider_configuration():
    from apps.llm import get_llm_provider
    from apps.llm.exceptions import LLMProviderError

    with pytest.raises(LLMProviderError) as exc_info:
        get_llm_provider()

    assert exc_info.value.code == "unsupported_llm_provider"


@pytest.mark.parametrize(
    "missing_setting",
    ["LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"],
)
def test_factory_rejects_missing_required_configuration(settings, missing_setting):
    from apps.llm import get_llm_provider
    from apps.llm.exceptions import LLMProviderError

    for name, value in VALID_SETTINGS.items():
        setattr(settings, name, value)
    setattr(settings, missing_setting, "")

    with pytest.raises(LLMProviderError) as exc_info:
        get_llm_provider()

    assert exc_info.value.code == "llm_not_configured"


@pytest.mark.parametrize(
    ("invalid_setting", "invalid_value"),
    [
        ("LLM_TIMEOUT_SECONDS", 0),
        ("LLM_TIMEOUT_SECONDS", True),
        ("LLM_MAX_RETRIES", -1),
        ("LLM_MAX_RETRIES", True),
        ("LLM_MAX_OUTPUT_TOKENS", 0),
        ("LLM_MAX_OUTPUT_TOKENS", False),
        ("LLM_THINKING_ENABLED", "false"),
    ],
)
def test_factory_rejects_invalid_typed_configuration(
    settings,
    invalid_setting,
    invalid_value,
):
    from apps.llm import get_llm_provider
    from apps.llm.exceptions import LLMProviderError

    for name, value in VALID_SETTINGS.items():
        setattr(settings, name, value)
    setattr(settings, invalid_setting, invalid_value)

    with pytest.raises(LLMProviderError) as exc_info:
        get_llm_provider()

    assert exc_info.value.code == "llm_not_configured"


def test_llm_configuration_repr_redacts_api_key():
    from apps.llm.base import LLMProviderConfig

    config = LLMProviderConfig(
        provider_name="deepseek",
        model_name="deepseek-v4-flash",
        api_key="never-print-this-secret",
        base_url="https://api.deepseek.com",
        timeout_seconds=30,
        max_retries=2,
        max_output_tokens=512,
        thinking_enabled=False,
    )

    assert "never-print-this-secret" not in repr(config)


@override_settings(**VALID_SETTINGS)
@pytest.mark.django_db
def test_factory_performs_no_database_queries(django_assert_num_queries):
    from apps.llm import get_llm_provider

    with django_assert_num_queries(0):
        provider = get_llm_provider()

    assert provider.provider_name == "deepseek"
