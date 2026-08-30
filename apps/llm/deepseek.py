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


_ALLOWED_ROLES = frozenset({"system", "user", "assistant"})


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

    def generate(self, messages: Sequence[LLMMessage]) -> LLMGeneration:
        validated_messages = self._validate_messages(messages)
        thinking_type = "enabled" if self.thinking_enabled else "disabled"
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                messages=validated_messages,
                max_tokens=self._config.max_output_tokens,
                extra_body={"thinking": {"type": thinking_type}},
            )
        except OpenAIError:
            raise LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR) from None

        try:
            choices = list(response.choices)
            content = choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            self._raise_invalid_response()
        if not isinstance(content, str) or not content.strip():
            self._raise_invalid_response()
        return LLMGeneration(content=content.strip())

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
