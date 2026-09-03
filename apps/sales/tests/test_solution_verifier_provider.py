"""Solution generation and semantic verification use independent providers."""

import json

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.rag.tests.test_answering import search_result
from apps.sales.tests.solution_fakes import SolutionFakeLLM, analysis_record


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw: pytest.fail("No real network."))


class IndependentVerifier(DeterministicFakeLLM):
    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        assert "<grounding_claim_packets>" in messages[-1]["content"]
        return LLMGeneration(content=json.dumps({"results": [
            {"location": "claims[0]", "relation": "SUPPORTED"},
            {"location": "claims[1]", "relation": "SUPPORTED"},
            {"location": "claims[2]", "relation": "SUPPORTED"},
            {"location": "claims[3]", "relation": "SUPPORTED"},
            {"location": "claims[4]", "relation": "SUPPORTED"},
        ]}))


def test_explicit_verifier_provider_is_used_only_for_semantic_verification(monkeypatch):
    from apps.sales.services import solution_draft as service

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    generation = SolutionFakeLLM()
    verifier = IndependentVerifier()

    result = service.generate_grounded_solution_draft(
        analysis_record(), llm_provider=generation, verifier_provider=verifier,
    )

    assert result.generation_status == "generated"
    assert len(generation.calls) == 1
    assert generation.requested_output_budgets == [4000]
    assert len(verifier.calls) == 1
    assert verifier.requested_output_budgets == [None]


def test_configured_verifier_factory_does_not_replace_generation_provider(monkeypatch, settings):
    from apps.sales.services import solution_draft as service

    settings.VERIFIER_PROVIDER = "openai_compatible"
    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    generation = SolutionFakeLLM()
    verifier = IndependentVerifier()
    monkeypatch.setattr(service, "get_llm_provider", lambda: generation)
    monkeypatch.setattr(service, "get_verifier_provider", lambda: verifier)

    result = service.generate_grounded_solution_draft(analysis_record())

    assert result.generation_status == "generated"
    assert len(generation.calls) == 1
    assert len(verifier.calls) == 1


def test_unconfigured_verifier_keeps_existing_single_provider_behavior(monkeypatch, settings):
    from apps.sales.services import solution_draft as service

    settings.VERIFIER_PROVIDER = ""
    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    llm = SolutionFakeLLM()
    monkeypatch.setattr(service, "get_llm_provider", lambda: llm)
    monkeypatch.setattr(service, "get_verifier_provider", lambda: pytest.fail("No verifier factory."))

    result = service.generate_grounded_solution_draft(analysis_record())

    assert result.generation_status == "generated"
    assert len(llm.calls) == 2


def test_structural_failure_does_not_construct_configured_verifier(monkeypatch, settings):
    from apps.sales.services import solution_draft as service

    settings.VERIFIER_PROVIDER = "openai_compatible"
    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    monkeypatch.setattr(service, "get_verifier_provider", lambda: pytest.fail("Invalid IR must stop first."))

    with pytest.raises(Exception):
        service.generate_grounded_solution_draft(
            analysis_record(), llm_provider=SolutionFakeLLM(content='{"claims":[]}'),
        )
