"""Explicit factory for the configured language-model provider."""

from django.conf import settings

from apps.llm.base import LLMProviderConfig
from apps.llm.deepseek import DeepSeekLLMProvider
from apps.llm.exceptions import LLMErrorCode, LLMProviderError


def get_llm_provider() -> DeepSeekLLMProvider:
    """Build the configured provider without dynamic imports or fallback."""

    configured_provider = settings.LLM_PROVIDER
    if not isinstance(configured_provider, str) or not configured_provider.strip():
        raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)
    if configured_provider.strip() != "deepseek":
        raise LLMProviderError(LLMErrorCode.UNSUPPORTED_LLM_PROVIDER)
    return DeepSeekLLMProvider(_config_from_settings())


def _config_from_settings() -> LLMProviderConfig:
    string_values = (
        settings.LLM_PROVIDER,
        settings.LLM_MODEL,
        settings.LLM_API_KEY,
        settings.LLM_BASE_URL,
    )
    if any(not isinstance(value, str) or not value.strip() for value in string_values):
        raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)

    positive_integers = (
        settings.LLM_TIMEOUT_SECONDS,
        settings.LLM_MAX_OUTPUT_TOKENS,
    )
    positive_integers_are_valid = all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in positive_integers
    )
    retries_are_valid = (
        isinstance(settings.LLM_MAX_RETRIES, int)
        and not isinstance(settings.LLM_MAX_RETRIES, bool)
        and settings.LLM_MAX_RETRIES >= 0
    )
    thinking_is_boolean = isinstance(settings.LLM_THINKING_ENABLED, bool)
    if not (
        positive_integers_are_valid
        and retries_are_valid
        and thinking_is_boolean
    ):
        raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)

    return LLMProviderConfig(
        provider_name=settings.LLM_PROVIDER.strip(),
        model_name=settings.LLM_MODEL.strip(),
        api_key=settings.LLM_API_KEY.strip(),
        base_url=settings.LLM_BASE_URL.strip(),
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        thinking_enabled=settings.LLM_THINKING_ENABLED,
    )
