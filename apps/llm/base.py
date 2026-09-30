"""Minimal contracts shared by language-model providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Sequence, TypedDict


class LLMMessage(TypedDict):
    """One normalized chat message accepted by the provider layer."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMGeneration:
    """Safe final model output exposed to future business services."""

    content: str
    provider_request_id: str | None = None


class LLMProvider(ABC):
    """Provider-neutral interface for one non-streaming generation."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Configured model identifier."""

    @abstractmethod
    def generate(
        self, messages: Sequence[LLMMessage], *, max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        """Generate once; None keeps the configured output budget for this call."""

    def generate_json(
        self, messages: Sequence[LLMMessage], *, max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        """Request JSON when supported, otherwise preserve the provider contract."""

        return self.generate(messages, max_output_tokens=max_output_tokens)


@dataclass(frozen=True, slots=True)
class LLMProviderConfig:
    """Provider configuration with a secret-safe representation."""

    provider_name: str
    model_name: str
    api_key: str = field(repr=False)
    base_url: str
    timeout_seconds: int
    max_retries: int
    max_output_tokens: int
    thinking_enabled: bool | None
