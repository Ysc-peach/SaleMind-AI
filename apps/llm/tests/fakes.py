"""Deterministic LLM test doubles; never used by the production factory."""

import json
from hashlib import sha256
from typing import Sequence

from apps.llm.base import LLMGeneration, LLMMessage, LLMProvider


class DeterministicFakeLLM(LLMProvider):
    """Return a cross-process stable answer derived from normalized messages."""

    provider_name = "fake"
    model_name = "sha256-test-llm"

    def __init__(self):
        self.calls: list[tuple[LLMMessage, ...]] = []
        self.requested_output_budgets: list[int | None] = []

    def generate(
        self, messages: Sequence[LLMMessage], *, max_output_tokens: int | None = None,
    ) -> LLMGeneration:
        normalized_messages = tuple(
            {"role": message["role"], "content": message["content"]}
            for message in messages
        )
        self.calls.append(normalized_messages)
        self.requested_output_budgets.append(max_output_tokens)
        serialized = json.dumps(
            normalized_messages,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = sha256(serialized.encode("utf-8")).hexdigest()
        return LLMGeneration(content=f"deterministic-llm:{digest}")
