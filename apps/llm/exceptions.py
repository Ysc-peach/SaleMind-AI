"""Stable, secret-safe language-model provider errors."""

from enum import StrEnum


class LLMErrorCode(StrEnum):
    LLM_NOT_CONFIGURED = "llm_not_configured"
    UNSUPPORTED_LLM_PROVIDER = "unsupported_llm_provider"
    LLM_PROVIDER_ERROR = "llm_provider_error"
    LLM_INVALID_RESPONSE = "llm_invalid_response"


_SAFE_ERROR_MESSAGES = {
    LLMErrorCode.LLM_NOT_CONFIGURED: "The language-model provider is not configured.",
    LLMErrorCode.UNSUPPORTED_LLM_PROVIDER: (
        "The language-model provider is not supported."
    ),
    LLMErrorCode.LLM_PROVIDER_ERROR: "The language-model provider request failed.",
    LLMErrorCode.LLM_INVALID_RESPONSE: (
        "The language-model provider returned an invalid response."
    ),
}


class LLMProviderError(Exception):
    """A stable provider failure safe to expose to future API layers."""

    def __init__(self, code: LLMErrorCode):
        self.code = code.value
        self.safe_message = _SAFE_ERROR_MESSAGES[code]
        super().__init__(self.safe_message)
