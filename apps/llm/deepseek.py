"""DeepSeek language-model provider."""

from collections.abc import Mapping, Sequence
from typing import NoReturn

from openai import OpenAI, OpenAIError

from apps.llm.base import (
    LLMGeneration,
    LLMMessage,
    LLMProvider,
    LLMProviderConfig,
)
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.llm.openai_compatible import _safe_provider_error


_ALLOWED_ROLES = frozenset({"system", "user", "assistant"})
_SAFE_FINISH_REASONS = frozenset({
    "stop", "length", "content_filter", "tool_calls", "function_call",
    "insufficient_system_resource", "aborted",
})


class DeepSeekLLMProvider(LLMProvider):
    """DeepSeek Chat Completions provider using the existing OpenAI SDK."""

    def __init__(self, config: LLMProviderConfig):
        self._config = config
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

    @property
    def thinking_enabled(self) -> bool:
        return self._config.thinking_enabled

    def generate(
        self, messages: Sequence[LLMMessage], *, max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        return self._generate(
            messages,
            max_output_tokens=max_output_tokens,
            json_output=False,
        )

    def generate_json(
        self, messages: Sequence[LLMMessage], *, max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        return self._generate(
            messages,
            max_output_tokens=max_output_tokens,
            json_output=True,
        )

    def _generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        max_output_tokens: int | None,
        json_output: bool,
    ) -> LLMGeneration:
        validated_messages = self._validate_messages(messages)
        output_budget = self._config.max_output_tokens if max_output_tokens is None else max_output_tokens
        if not isinstance(output_budget, int) or isinstance(output_budget, bool) or output_budget <= 0:
            raise LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)
        thinking_type = "enabled" if self.thinking_enabled else "disabled"
        request = {
            "model": self.model_name,
            "messages": validated_messages,
            "max_tokens": output_budget,
            "extra_body": {"thinking": {"type": thinking_type}},
        }
        if json_output:
            request["response_format"] = {"type": "json_object"}
        try:
            response = self._client.chat.completions.create(**request)
        except OpenAIError as error:
            # Preserve only existing secret-safe metadata; public error, request
            # semantics, SDK retries and fail-closed behavior stay unchanged.
            raise _safe_provider_error(error) from None

        try:
            choices = list(response.choices)
            content = choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            self._raise_invalid_response()
        if not isinstance(content, str) or not content.strip():
            self._raise_invalid_response()
        finish_reason = getattr(choices[0], "finish_reason", None)
        if not isinstance(finish_reason, str) or finish_reason not in _SAFE_FINISH_REASONS:
            finish_reason = None
        usage = getattr(response, "usage", None)
        return LLMGeneration(
            content=content.strip(),
            finish_reason=finish_reason,
            prompt_tokens=_safe_token_count(getattr(usage, "prompt_tokens", None)),
            completion_tokens=_safe_token_count(getattr(usage, "completion_tokens", None)),
        )

    def _validate_messages(
        self,
        messages: Sequence[LLMMessage],
    ) -> list[LLMMessage]:
        if (
            isinstance(messages, (str, bytes, Mapping))
            or not isinstance(messages, Sequence)
            or not messages
        ):
            self._raise_invalid_response()

        normalized: list[LLMMessage] = []
        for message in messages:
            if not isinstance(message, Mapping):
                self._raise_invalid_response()
            role = message.get("role")
            content = message.get("content")
            if (
                role not in _ALLOWED_ROLES
                or not isinstance(content, str)
                or not content.strip()
            ):
                self._raise_invalid_response()
            normalized.append({"role": role, "content": content.strip()})
        return normalized

    def _raise_invalid_response(self) -> NoReturn:
        raise LLMProviderError(LLMErrorCode.LLM_INVALID_RESPONSE)


def _safe_token_count(value: object) -> int | None:
    """Optional usage metadata must never carry response text or booleans."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
