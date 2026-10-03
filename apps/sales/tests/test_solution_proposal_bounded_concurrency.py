"""Bounded, isolated semantic verification for generated proposals."""

import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.test import override_settings

from apps.llm.base import LLMGeneration, LLMProvider
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.rag.tests.test_answering import search_result
from apps.sales.services.solution_retrieval import merge_evidence
from apps.sales.services.solution_schema import (
    AtomicSolutionClaim,
    AtomicSolutionClaimSet,
    SolutionSectionKey,
    SolutionStatementType,
)
from apps.sales.tests.solution_fakes import typed_analysis


def proposal_set(*texts):
    return AtomicSolutionClaimSet(tuple(
        AtomicSolutionClaim(
            section=SolutionSectionKey.DEPLOYMENT,
            statement_type=SolutionStatementType.PROPOSAL,
            text=text,
            citations=("S1",),
        )
        for text in texts
    ))


def sources():
    return merge_evidence([[
        search_result(content="SalesMind 当前版本支持企业私有化部署。")
    ]])


class ControlledConcurrentVerifier(LLMProvider):
    provider_name = "controlled-concurrency"
    model_name = "fake-verifier"

    def __init__(
        self,
        *,
        barrier_parties=0,
        delays=None,
        relations=None,
        failures=None,
        admissibility=False,
        malformed=False,
        atomicities=None,
    ):
        self._lock = threading.Lock()
        self._barrier = (
            threading.Barrier(barrier_parties) if barrier_parties else None
        )
        self._delays = delays or {}
        self._relations = relations or {}
        self._failures = failures or {}
        self._admissibility = admissibility
        self._malformed = malformed
        self._atomicities = atomicities or {}
        self.calls = []
        self.completion_order = []
        self.active = 0
        self.max_active = 0
        self.started = 0

    def generate(self, messages, *, max_output_tokens=None):
        tag = (
            "proposal_admissibility_packets" if self._admissibility
            else "grounding_claim_packets"
        )
        match = re.search(
            rf"<{tag}>(.*?)</{tag}>",
            messages[-1]["content"],
            flags=re.DOTALL,
        )
        payload = json.loads(html.unescape(match.group(1)))
        packets = tuple(payload["proposals" if self._admissibility else "claims"])
        text = packets[0]["text"] if len(packets) == 1 else "<batched>"
        with self._lock:
            self.calls.append(packets)
            self.active += 1
            self.started += 1
            ordinal = self.started
            self.max_active = max(self.max_active, self.active)
        try:
            if (
                self._barrier is not None
                and len(packets) == 1
                and ordinal <= self._barrier.parties
            ):
                self._barrier.wait(timeout=2)
            time.sleep(self._delays.get(text, 0.01))
            if text in self._failures:
                raise self._failures[text]
            if self._malformed and text == "拒绝建议。":
                return LLMGeneration(content="{}")
            relation = self._relations.get(text, "SUPPORTED")
            verdict = (
                {"decision": "ADMISSIBLE" if relation == "SUPPORTED" else "INADMISSIBLE"}
                if self._admissibility else {"relation": relation}
            )
            return LLMGeneration(content=json.dumps({"results": [
                {
                    "location": packet["location"],
                    **verdict,
                    "atomicity": self._atomicities.get(text, "ATOMIC"),
                }
                for packet in packets
            ]}))
        finally:
            with self._lock:
                self.active -= 1
                self.completion_order.append(text)


def verify(proposals, provider):
    from apps.sales.services.solution_grounding import verify_atomic_solution_proposals

    return verify_atomic_solution_proposals(
        analysis=typed_analysis(),
        proposals=proposals,
        sources=sources(),
        llm_provider=provider,
    )


def test_default_concurrency_is_two_and_each_request_contains_one_proposal():
    provider = ControlledConcurrentVerifier(barrier_parties=2)

    result = verify(proposal_set("建议一。", "建议二。", "建议三。"), provider)

    assert len(provider.calls) == 3
    assert all(len(packets) == 1 for packets in provider.calls)
    assert provider.max_active == 2
    assert [item.location for item in result.results] == [
        "claims[0]",
        "claims[1]",
        "claims[2]",
    ]


@override_settings(VERIFIER_MAX_CONCURRENCY=1)
def test_configured_concurrency_one_serializes_without_business_code_change():
    provider = ControlledConcurrentVerifier()

    verify(proposal_set("建议一。", "建议二。", "建议三。"), provider)

    assert len(provider.calls) == 3
    assert provider.max_active == 1


@override_settings(VERIFIER_MAX_CONCURRENCY=3)
def test_configured_concurrency_three_is_observed_but_never_exceeded():
    provider = ControlledConcurrentVerifier(barrier_parties=3)

    verify(proposal_set("建议一。", "建议二。", "建议三。", "建议四。"), provider)

    assert len(provider.calls) == 4
    assert provider.max_active == 3


@override_settings(VERIFIER_MAX_CONCURRENCY=2)
def test_result_order_follows_original_proposals_not_completion_order():
    provider = ControlledConcurrentVerifier(delays={
        "建议一。": 0.06,
        "建议二。": 0.01,
        "建议三。": 0.02,
    })

    result = verify(proposal_set("建议一。", "建议二。", "建议三。"), provider)

    assert len(provider.calls) == 3
    assert provider.completion_order != ["建议一。", "建议二。", "建议三。"]
    assert [item.location for item in result.results] == [
        "claims[0]",
        "claims[1]",
        "claims[2]",
    ]


def test_one_unsupported_proposal_rejects_the_whole_verification():
    provider = ControlledConcurrentVerifier(relations={"越权建议。": "INSUFFICIENT"})

    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with pytest.raises(SolutionDraftGroundingError) as exc:
        verify(proposal_set("安全建议。", "越权建议。"), provider)

    assert exc.value.code == "solution_draft_not_grounded"
    assert len(provider.calls) == 2


def test_one_timeout_rejects_the_whole_verification_without_retry():
    timeout = LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)
    provider = ControlledConcurrentVerifier(failures={"超时建议。": timeout})

    with pytest.raises(LLMProviderError) as exc:
        verify(proposal_set("安全建议。", "超时建议。"), provider)

    assert exc.value is timeout
    assert len(provider.calls) == 2


@pytest.mark.parametrize("invalid", [0, -1, True, "2"])
def test_invalid_concurrency_setting_fails_closed_before_provider(invalid):
    provider = ControlledConcurrentVerifier()

    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    with override_settings(VERIFIER_MAX_CONCURRENCY=invalid):
        with pytest.raises(SolutionDraftGroundingError) as exc:
            verify(proposal_set("建议一。"), provider)

    assert exc.value.code == "invalid_solution_grounding_input"
    assert provider.calls == []


def verify_schedule(texts, provider, *, v2):
    if not v2:
        return verify(proposal_set(*texts), provider)
    from apps.sales.services.solution_prompt_v2 import AtomicSolutionProposalSetV2
    from apps.sales.tests.test_solution_proposal_admissibility_v2 import _proposal, _verify

    proposals = AtomicSolutionProposalSetV2(tuple(
        _proposal(text).proposals[0] for text in texts
    ))
    result = _verify(proposals, provider)
    assert result is proposals
    return result


@pytest.mark.parametrize("v2", [False, True], ids=["grounding", "admissibility"])
@pytest.mark.parametrize("failure", ["veto", "compound", "provider", "malformed"])
@override_settings(VERIFIER_MAX_CONCURRENCY=2)
def test_later_completed_failure_stops_dispatch_before_slow_first_claim_drains(v2, failure):
    """A second-claim failure must not be hidden by a slower first claim."""
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    provider_error = LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)
    provider = ControlledConcurrentVerifier(
        barrier_parties=2,
        admissibility=v2,
        delays={"慢速建议。": 0.15, "拒绝建议。": 0.001},
        relations={"拒绝建议。": "INSUFFICIENT"} if failure == "veto" else None,
        atomicities={"拒绝建议。": "COMPOUND"} if failure == "compound" else None,
        failures={"拒绝建议。": provider_error} if failure == "provider" else None,
        malformed=failure == "malformed",
    )
    error_type = LLMProviderError if failure == "provider" else SolutionDraftGroundingError
    texts = ("慢速建议。", "拒绝建议。", "建议三。", "建议四。", "建议五。", "建议六。")

    with pytest.raises(error_type) as exc:
        verify_schedule(texts, provider, v2=v2)

    assert len(provider.calls) == 2
    assert provider.active == 0  # Already running work is drained before returning.
    if failure == "provider":
        assert exc.value is provider_error
    else:
        assert exc.value.code == (
            "solution_grounding_invalid_response" if failure == "malformed"
            else "solution_draft_not_grounded"
        )


@pytest.mark.parametrize("v2", [False, True], ids=["grounding", "admissibility"])
@override_settings(VERIFIER_MAX_CONCURRENCY=2)
def test_pending_verifier_futures_are_bounded_and_success_visits_every_claim(monkeypatch, v2):
    """Counting real unfinished futures catches eager queueing beyond workers."""
    class RecordingExecutor(ThreadPoolExecutor):
        max_unfinished = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.submitted = []

        def submit(self, fn, /, *args, **kwargs):
            future = super().submit(fn, *args, **kwargs)
            self.submitted.append(future)
            type(self).max_unfinished = max(
                self.max_unfinished,
                sum(not item.done() for item in self.submitted),
            )
            return future

    monkeypatch.setattr("apps.sales.services.solution_grounding.ThreadPoolExecutor", RecordingExecutor)
    provider = ControlledConcurrentVerifier(admissibility=v2, barrier_parties=2)
    texts = ("建议一。", "建议二。", "建议三。", "建议四。", "建议五。", "建议六。")

    result = verify_schedule(texts, provider, v2=v2)

    assert RecordingExecutor.max_unfinished <= 2
    assert len(provider.calls) == 6
    assert all(len(packets) == 1 for packets in provider.calls)
    assert {packets[0]["text"] for packets in provider.calls} == set(texts)
    if not v2:
        assert [item.location for item in result.results] == [
            "claims[0]", "claims[1]", "claims[2]", "claims[3]", "claims[4]", "claims[5]",
        ]
