"""Fail-closed pipeline behavior around atomic claim verification."""

import json
from xml.etree import ElementTree

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.rag.tests.test_answering import search_result
from apps.sales.services.solution_retrieval import merge_evidence
from apps.sales.tests.solution_fakes import analysis_record, atomic_solution_payload, SolutionFakeLLM, typed_analysis
from apps.sales.tests.test_solution_atomic_claims import parse


def sources():
    return merge_evidence([[search_result(content="企业资料确认支持私有化部署。")]])


class VerifierFake(DeterministicFakeLLM):
    def __init__(self, content=None):
        super().__init__()
        self.content = content

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        if self.content is not None:
            return LLMGeneration(content=self.content)
        root = ElementTree.fromstring("<root>" + messages[1]["content"] + "</root>")
        claims = json.loads(root.find("grounding_claim_packets").text)["claims"]
        return LLMGeneration(content=json.dumps({"results": [
            {"location": item["location"], "relation": "SUPPORTED", "atomicity": "ATOMIC"}
            for item in claims
        ]}))


@pytest.mark.parametrize("kwargs", [
    {"analysis": object(), "claims": parse(), "sources": sources()},
    {"analysis": typed_analysis(), "claims": object(), "sources": sources()},
    {"analysis": typed_analysis(), "claims": parse(), "sources": ()},
    {"analysis": typed_analysis(), "claims": parse(), "sources": list(sources())},
])
def test_verifier_rejects_untyped_or_non_authoritative_inputs_before_llm(kwargs):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError, verify_atomic_solution_claims

    provider = VerifierFake()
    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify_atomic_solution_claims(**kwargs, llm_provider=provider)
    assert exc.value.code == "invalid_solution_grounding_input" and provider.calls == []


def test_provider_error_during_verification_propagates_without_retry():
    from apps.sales.services.solution_grounding import verify_atomic_solution_claims

    error = LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)

    class Failing(VerifierFake):
        def generate(self, messages, *, max_output_tokens=None):
            raise error

    with pytest.raises(LLMProviderError) as exc:
        value = atomic_solution_payload()
        value["claims"] = [value["claims"][1]]
        verify_atomic_solution_claims(
            analysis=typed_analysis(), claims=parse(value, source_count=1), sources=sources(), llm_provider=Failing(),
        )
    assert exc.value is error


def test_orchestration_generates_then_verifies_once_and_assembles(monkeypatch):
    from apps.sales.services import solution_draft as service

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    llm = SolutionFakeLLM()
    result = service.generate_grounded_solution_draft(analysis_record(), llm_provider=llm)
    assert result.generation_status == "generated"
    assert len(llm.calls) == 2 and llm.requested_output_budgets == [4000, None]
    assert "<grounding_claim_packets>" in llm.calls[1][1]["content"]
    assert len(result.draft.solution_sections) == 5


def test_verifier_reuses_frozen_history_after_caller_record_changes(monkeypatch):
    from apps.sales.services import solution_draft as service

    record = analysis_record()
    original = record.requirements["business_goal"]["value"]

    def mutate_record_after_generation():
        record.requirements["business_goal"]["value"] = "调用期间被修改"

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    llm = SolutionFakeLLM(callback=mutate_record_after_generation)
    service.generate_grounded_solution_draft(record, llm_provider=llm)
    root = ElementTree.fromstring("<root>" + llm.calls[1][1]["content"] + "</root>")
    packets = json.loads(root.find("grounding_claim_packets").text)["claims"]
    customer = next(item for item in packets if item["statement_type"] == "customer_fact")
    requirement_values = {
        item["field"]: item["analysis"]["value"]
        for item in customer["customer_context"]["requirements"]
    }
    assert requirement_values["business_goal"] == original
    assert "调用期间被修改" not in llm.calls[1][1]["content"]


def test_structurally_invalid_atomic_generation_never_calls_verifier(monkeypatch):
    from apps.sales.services import solution_draft as service
    from apps.sales.services.solution_errors import SolutionDraftError

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    llm = SolutionFakeLLM(content='{"title":"truncated"')
    with pytest.raises(SolutionDraftError):
        service.generate_grounded_solution_draft(analysis_record(), llm_provider=llm)
    assert len(llm.calls) == 1 and llm.requested_output_budgets == [4000]


def test_verifier_failure_is_not_retried_or_assembled(monkeypatch):
    from apps.sales.services import solution_draft as service
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    response = {"results": [
        {
            "location": f"claims[{index}]",
            "relation": "INSUFFICIENT" if index == 0 else "SUPPORTED",
            "atomicity": "ATOMIC",
        }
        for index in range(len(atomic_solution_payload()["claims"]))
    ]}
    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    llm = SolutionFakeLLM(grounding_content=json.dumps(response))
    with pytest.raises(SolutionDraftGroundingError):
        service.generate_grounded_solution_draft(analysis_record(), llm_provider=llm)
    assert len(llm.calls) == 2


@pytest.mark.parametrize("statuses", [{"budget": "conflict"}, {"data_security_requirement": "conflict"}])
def test_blocked_readiness_skips_generation_and_verification(monkeypatch, statuses):
    from apps.sales.services import solution_draft as service

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: pytest.fail("Blocked cannot search."))
    llm = SolutionFakeLLM()
    result = service.generate_grounded_solution_draft(analysis_record(**statuses), llm_provider=llm)
    assert result.generation_status == "blocked_by_readiness" and llm.calls == []


def test_insufficient_evidence_skips_generation_and_verification(monkeypatch):
    from apps.sales.services import solution_draft as service

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [])
    llm = SolutionFakeLLM()
    result = service.generate_grounded_solution_draft(analysis_record(), llm_provider=llm)
    assert result.generation_status == "insufficient_evidence" and llm.calls == []
