"""Independent factory for the semantic-grounding verifier provider."""

from django.conf import settings

from apps.llm.base import LLMProvider, LLMProviderConfig
from apps.llm.deepseek import DeepSeekLLMProvider
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.llm.openai_compatible import OpenAICompatibleLLMProvider


def get_verifier_provider() -> LLMProvider:
    provider_name = settings.VERIFIER_PROVIDER
    if not isinstance(provider_name, str) or not provider_name.strip():
        raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)
    if provider_name.strip() not in {"openai_compatible", "deepseek"}:
        raise LLMProviderError(LLMErrorCode.UNSUPPORTED_LLM_PROVIDER)
    config = _config_from_settings()
    if config.provider_name == "deepseek":
        return DeepSeekLLMProvider(config)
    return OpenAICompatibleLLMProvider(
        config,
        supports_enable_thinking=config.model_name.casefold().startswith("qwen3"),
    )


def _config_from_settings() -> LLMProviderConfig:
    strings = (
        settings.VERIFIER_PROVIDER,
        settings.VERIFIER_MODEL,
        settings.VERIFIER_API_KEY,
        settings.VERIFIER_BASE_URL,
    )
    integers = (
        settings.VERIFIER_TIMEOUT_SECONDS,
        settings.VERIFIER_MAX_OUTPUT_TOKENS,
    )
    if any(not isinstance(value, str) or not value.strip() for value in strings):
        raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in integers
    ):
        raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)
    retries = settings.VERIFIER_MAX_RETRIES
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)
    return LLMProviderConfig(
        provider_name=settings.VERIFIER_PROVIDER.strip(),
        model_name=settings.VERIFIER_MODEL.strip(),
        api_key=settings.VERIFIER_API_KEY.strip(),
        base_url=settings.VERIFIER_BASE_URL.strip(),
        timeout_seconds=settings.VERIFIER_TIMEOUT_SECONDS,
        max_retries=retries,
        max_output_tokens=settings.VERIFIER_MAX_OUTPUT_TOKENS,
        thinking_enabled=False,
    )
