"""Generic OpenAI-compatible non-streaming chat-completions provider."""

from collections.abc import Mapping, Sequence
from typing import NoReturn

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)

from apps.llm.base import LLMGeneration, LLMMessage, LLMProvider, LLMProviderConfig
from apps.llm.exceptions import (
    LLMErrorCode,
    LLMProviderError,
    LLMProviderFailureKind,
)


_ALLOWED_ROLES = frozenset({"system", "user", "assistant"})


class OpenAICompatibleLLMProvider(LLMProvider):
    """Use the OpenAI-compatible ``/chat/completions`` boundary only."""

    def __init__(
        self,
        config: LLMProviderConfig,
        *,
        supports_enable_thinking: bool = False,
    ):
        self._config = config
        self._supports_enable_thinking = supports_enable_thinking
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    @property
    def provider_name(self) -> str:
        return self._config.provider_name

    @property
    def model_name(self) -> str:
        return self._config.model_name

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        normalized = self._validate_messages(messages)
        output_budget = self._config.max_output_tokens if max_output_tokens is None else max_output_tokens
        if not isinstance(output_budget, int) or isinstance(output_budget, bool) or output_budget <= 0:
            raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)
        request = {
            "model": self.model_name,
            "messages": normalized,
            "max_tokens": output_budget,
        }
        if self._supports_enable_thinking and self._config.thinking_enabled is False:
            request["extra_body"] = {"enable_thinking": False}
        try:
            response = self._client.chat.completions.create(**request)
        except OpenAIError as error:
            raise _safe_provider_error(error) from None
        try:
            choices = list(response.choices)
            content = choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            self._invalid_response()
        if not isinstance(content, str) or not content.strip():
            self._invalid_response()
        return LLMGeneration(
            content=content.strip(),
            provider_request_id=getattr(response, "_request_id", None),
        )

    def _validate_messages(self, messages: Sequence[LLMMessage]) -> list[LLMMessage]:
        if (
            isinstance(messages, (str, bytes, Mapping))
            or not isinstance(messages, Sequence)
            or not messages
        ):
            self._invalid_response()
        result = []
        for message in messages:
            if not isinstance(message, Mapping):
                self._invalid_response()
            role, content = message.get("role"), message.get("content")
            if role not in _ALLOWED_ROLES or not isinstance(content, str) or not content.strip():
                self._invalid_response()
            result.append({"role": role, "content": content.strip()})
        return result

    def _invalid_response(self) -> NoReturn:
        raise LLMProviderError(
            LLMErrorCode.LLM_INVALID_RESPONSE,
            failure_kind=LLMProviderFailureKind.INVALID_RESPONSE,
        )


_QUOTA_CODES = frozenset({
    "billing_hard_limit_reached",
    "insufficient_quota",
    "quota_exceeded",
})


def _safe_provider_error(error: OpenAIError) -> LLMProviderError:
    status = getattr(error, "status_code", None)
    if isinstance(error, APITimeoutError):
        kind = LLMProviderFailureKind.TIMEOUT
    elif isinstance(error, RateLimitError):
        kind = (
            LLMProviderFailureKind.QUOTA_ERROR
            if _provider_error_code(error) in _QUOTA_CODES
            else LLMProviderFailureKind.RATE_LIMITED
        )
    elif isinstance(error, AuthenticationError):
        kind = LLMProviderFailureKind.AUTH_ERROR
    elif isinstance(error, PermissionDeniedError):
        kind = LLMProviderFailureKind.PERMISSION_DENIED
    elif isinstance(error, APIResponseValidationError):
        kind = LLMProviderFailureKind.INVALID_RESPONSE
    elif isinstance(error, APIConnectionError):
        kind = LLMProviderFailureKind.CONNECTION_ERROR
    elif isinstance(error, APIStatusError) and isinstance(status, int) and status >= 500:
        kind = LLMProviderFailureKind.SERVER_ERROR
    else:
        kind = LLMProviderFailureKind.UNKNOWN_PROVIDER_ERROR
    return LLMProviderError(
        LLMErrorCode.LLM_PROVIDER_ERROR,
        failure_kind=kind,
        http_status=status,
        request_id=_provider_request_id(error),
    )


def _provider_error_code(error: OpenAIError) -> str | None:
    value = getattr(error, "code", None)
    if isinstance(value, str):
        return value.strip().lower()
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        nested = body.get("error")
        candidates = (body.get("code"), nested.get("code") if isinstance(nested, Mapping) else None)
        for candidate in candidates:
            if isinstance(candidate, str):
                return candidate.strip().lower()
    return None


def _provider_request_id(error: OpenAIError) -> str | None:
    value = getattr(error, "request_id", None)
    if isinstance(value, str):
        return value
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for name in ("x-request-id", "request-id", "x-dashscope-request-id"):
        value = headers.get(name)
        if isinstance(value, str):
            return value
    return None
