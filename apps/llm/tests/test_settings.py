"""Phase 4.1 LLM configuration defaults."""

from django.conf import settings


def test_llm_configuration_defaults_are_available():
    assert settings.LLM_PROVIDER == "deepseek"
    assert settings.LLM_MODEL == "deepseek-v4-flash"
    assert settings.LLM_BASE_URL == "https://api.deepseek.com"
    assert settings.LLM_TIMEOUT_SECONDS > 0
    assert settings.LLM_MAX_RETRIES >= 0
    assert settings.LLM_MAX_OUTPUT_TOKENS > 0
    assert settings.LLM_THINKING_ENABLED is False
