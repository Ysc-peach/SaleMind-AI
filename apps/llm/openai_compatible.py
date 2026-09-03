"""Generic OpenAI-compatible non-streaming chat-completions provider."""

from collections.abc import Mapping, Sequence
from typing import NoReturn

from openai import OpenAI, OpenAIError

from apps.llm.base import LLMGeneration, LLMMessage, LLMProvider, LLMProviderConfig
from apps.llm.exceptions import LLMErrorCode, LLMProviderError


_ALLOWED_ROLES = frozenset({"system", "user", "assistant"})


class OpenAICompatibleLLMProvider(LLMProvider):
    """Use the OpenAI-compatible ``/chat/completions`` boundary only."""

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
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                messages=normalized,
                max_tokens=output_budget,
            )
        except OpenAIError:
            raise LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR) from None
        try:
            choices = list(response.choices)
            content = choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            self._invalid_response()
        if not isinstance(content, str) or not content.strip():
            self._invalid_response()
        return LLMGeneration(content=content.strip())

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
        raise LLMProviderError(LLMErrorCode.LLM_INVALID_RESPONSE)
