"""Stable, secret-safe language-model provider errors."""

from enum import StrEnum
import re


class LLMErrorCode(StrEnum):
    LLM_NOT_CONFIGURED = "llm_not_configured"
    UNSUPPORTED_LLM_PROVIDER = "unsupported_llm_provider"
    LLM_PROVIDER_ERROR = "llm_provider_error"
    LLM_INVALID_RESPONSE = "llm_invalid_response"


class LLMProviderFailureKind(StrEnum):
    """Secret-safe internal cause retained below the stable API error code."""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CONNECTION_ERROR = "connection_error"
    SERVER_ERROR = "server_error"
    AUTH_ERROR = "auth_error"
    PERMISSION_DENIED = "permission_denied"
    QUOTA_ERROR = "quota_error"
    INVALID_RESPONSE = "invalid_response"
    RESPONSE_PARSE_ERROR = "response_parse_error"
    UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"


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


_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


class LLMProviderError(Exception):
    """A stable provider failure safe to expose to future API layers."""

    def __init__(
        self,
        code: LLMErrorCode,
        *,
        failure_kind: LLMProviderFailureKind | None = None,
        http_status: int | None = None,
        request_id: str | None = None,
    ):
        self.code = code.value
        self.safe_message = _SAFE_ERROR_MESSAGES[code]
        self.failure_kind = (
            failure_kind
            if isinstance(failure_kind, LLMProviderFailureKind)
            else None
        )
        self.http_status = (
            http_status
            if isinstance(http_status, int)
            and not isinstance(http_status, bool)
            and 100 <= http_status <= 599
            else None
        )
        self.request_id = (
            request_id
            if isinstance(request_id, str) and _SAFE_REQUEST_ID.fullmatch(request_id)
            else None
        )
        super().__init__(self.safe_message)
