"""Bounded, isolated semantic verification for generated proposals."""

import html
import json
import re
import threading
import time

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
    ):
        self._lock = threading.Lock()
        self._barrier = (
            threading.Barrier(barrier_parties) if barrier_parties else None
        )
        self._delays = delays or {}
        self._relations = relations or {}
        self._failures = failures or {}
        self.calls = []
        self.completion_order = []
        self.active = 0
        self.max_active = 0
        self.started = 0

    def generate(self, messages, *, max_output_tokens=None):
        match = re.search(
            r"<grounding_claim_packets>(.*?)</grounding_claim_packets>",
            messages[-1]["content"],
            flags=re.DOTALL,
        )
        payload = json.loads(html.unescape(match.group(1)))
        packets = tuple(payload["claims"])
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
            relation = self._relations.get(text, "SUPPORTED")
            return LLMGeneration(content=json.dumps({"results": [
                {
                    "location": packet["location"],
                    "relation": relation,
                    "atomicity": "ATOMIC",
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
