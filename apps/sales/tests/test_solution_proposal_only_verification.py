"""Proposal-only verifier boundary for the provenance-driven pipeline."""

import html
import json
import re

import pytest

from apps.llm.base import LLMGeneration
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.rag.tests.test_answering import search_result
from apps.sales.services.solution_admission import GroundingAdmission
from apps.sales.services.solution_schema import (
    AtomicSolutionClaim,
    AtomicSolutionClaimSet,
    SolutionSectionKey,
    SolutionStatementType,
)
from apps.sales.tests.solution_fakes import analysis_record


class ProposalGenerator(DeterministicFakeLLM):
    def __init__(self, proposals):
        super().__init__()
        self.proposals = proposals

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        return LLMGeneration(
            content=json.dumps({"proposals": self.proposals}, ensure_ascii=False)
        )


class RecordingVerifier(DeterministicFakeLLM):
    def __init__(self, *, relation="SUPPORTED", on_generate=None):
        super().__init__()
        self.relation = relation
        self.on_generate = on_generate
        self.packets = ()

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        match = re.search(
            r"<grounding_claim_packets>(.*?)</grounding_claim_packets>",
            messages[-1]["content"],
            flags=re.DOTALL,
        )
        payload = json.loads(html.unescape(match.group(1)))
        self.packets = tuple(payload["claims"])
        if self.on_generate is not None:
            self.on_generate()
        return LLMGeneration(content=json.dumps({"results": [
            {
                "location": packet["location"],
                "relation": self.relation,
                "atomicity": "ATOMIC",
            }
            for packet in self.packets
        ]}))


class NeverCallVerifier(DeterministicFakeLLM):
    def generate(self, messages, *, max_output_tokens=None):
        raise AssertionError("Deterministic claims must not enter the semantic verifier.")


def claim(kind, text, *, section=SolutionSectionKey.OVERALL_APPROACH, citations=()):
    return AtomicSolutionClaim(
        section=section,
        statement_type=kind,
        text=text,
        citations=citations,
    )


def admission(*claims, allowed_labels=()):
    return GroundingAdmission(
        claims=AtomicSolutionClaimSet(tuple(claims)),
        enterprise_decisions=(),
        enterprise_provenance=(),
        allowed_proposal_source_labels=allowed_labels,
    )


def run_pipeline(monkeypatch, *, admitted, proposals, verifier, admission_builder=None):
    from apps.sales.services import solution_draft

    source = search_result(content="SalesMind 支持企业私有化部署。")
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kwargs: [source])
    monkeypatch.setattr(
        solution_draft,
        "build_solution_admission",
        admission_builder or (lambda analysis, sources: admitted),
    )
    return solution_draft.generate_grounded_solution_draft(
        analysis_record(),
        llm_provider=ProposalGenerator(proposals),
        verifier_provider=verifier,
    )


@pytest.mark.parametrize(
    "deterministic_claim",
    [
        pytest.param(
            claim(SolutionStatementType.CUSTOMER_FACT, "客户使用人数：约300人。"),
            id="customer-fact",
        ),
        pytest.param(
            claim(
                SolutionStatementType.ENTERPRISE_FACT,
                "SalesMind 支持企业私有化部署。",
                section=SolutionSectionKey.DEPLOYMENT,
                citations=("S1",),
            ),
            id="approved-enterprise-fact",
        ),
        pytest.param(
            claim(
                SolutionStatementType.UNRESOLVED,
                "当前企业资料未确认 SSO 集成能力。",
                section=SolutionSectionKey.INTEGRATION,
            ),
            id="deterministic-unresolved",
        ),
    ],
)
def test_deterministic_claim_skips_verifier_but_remains_in_draft(
    monkeypatch,
    deterministic_claim,
):
    admitted = admission(
        deterministic_claim,
        allowed_labels=("S1",)
        if deterministic_claim.statement_type is SolutionStatementType.ENTERPRISE_FACT
        else (),
    )

    result = run_pipeline(
        monkeypatch,
        admitted=admitted,
        proposals=[],
        verifier=NeverCallVerifier(),
    )

    statements = tuple(
        statement
        for section in result.draft.solution_sections
        for statement in section.statements
    )
    assert any(
        statement.type is deterministic_claim.statement_type
        and statement.text == deterministic_claim.text
        for statement in statements
    )


def test_generated_proposal_is_the_only_verifier_candidate(monkeypatch):
    verifier = RecordingVerifier()
    result = run_pipeline(
        monkeypatch,
        admitted=admission(
            claim(SolutionStatementType.CUSTOMER_FACT, "客户要求私有化部署。"),
            claim(
                SolutionStatementType.ENTERPRISE_FACT,
                "SalesMind 支持企业私有化部署。",
                section=SolutionSectionKey.DEPLOYMENT,
                citations=("S1",),
            ),
            claim(
                SolutionStatementType.UNRESOLVED,
                "当前企业资料未确认 SSO 集成能力。",
                section=SolutionSectionKey.INTEGRATION,
            ),
            allowed_labels=("S1",),
        ),
        proposals=[{
            "section": "deployment",
            "text": "建议采用私有化部署方案。",
            "citations": ["S1"],
        }],
        verifier=verifier,
    )

    assert len(verifier.calls) == 1
    assert len(verifier.packets) == 1
    assert verifier.packets[0]["statement_type"] == "proposal"
    assert any(
        statement.type is SolutionStatementType.PROPOSAL
        for section in result.draft.solution_sections
        for statement in section.statements
    )


@pytest.mark.parametrize(
    "proposal_text",
    [
        "建议部署于客户现有 Linux 服务器。",
        "建议将业务数据保留在企业自有环境。",
    ],
)
def test_unsupported_proposal_is_rejected_by_proposal_verifier(
    monkeypatch,
    proposal_text,
):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    verifier = RecordingVerifier(relation="INSUFFICIENT")
    with pytest.raises(SolutionDraftGroundingError):
        run_pipeline(
            monkeypatch,
            admitted=admission(
                claim(
                    SolutionStatementType.ENTERPRISE_FACT,
                    "SalesMind 支持企业私有化部署。",
                    section=SolutionSectionKey.DEPLOYMENT,
                    citations=("S1",),
                ),
                allowed_labels=("S1",),
            ),
            proposals=[{
                "section": "deployment",
                "text": proposal_text,
                "citations": ["S1"],
            }],
            verifier=verifier,
        )

    assert len(verifier.calls) == 1
    assert [packet["text"] for packet in verifier.packets] == [proposal_text]


def test_proposal_verifier_failure_keeps_whole_draft_fail_closed(monkeypatch):
    error = LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)

    class FailingVerifier(DeterministicFakeLLM):
        def generate(self, messages, *, max_output_tokens=None):
            super().generate(messages, max_output_tokens=max_output_tokens)
            raise error

    verifier = FailingVerifier()
    with pytest.raises(LLMProviderError) as exc:
        run_pipeline(
            monkeypatch,
            admitted=admission(
                claim(SolutionStatementType.CUSTOMER_FACT, "客户要求私有化部署。"),
                allowed_labels=("S1",),
            ),
            proposals=[{
                "section": "deployment",
                "text": "建议采用私有化部署方案。",
                "citations": ["S1"],
            }],
            verifier=verifier,
        )

    assert exc.value is error
    assert len(verifier.calls) == 1


def test_verifier_supported_cannot_grant_enterprise_admission(monkeypatch):
    verifier = RecordingVerifier()
    result = run_pipeline(
        monkeypatch,
        admitted=admission(
            claim(
                SolutionStatementType.UNRESOLVED,
                "当前企业资料未确认 SSO 集成能力。",
                section=SolutionSectionKey.INTEGRATION,
            ),
            allowed_labels=("S1",),
        ),
        proposals=[{
            "section": "deployment",
            "text": "建议采用私有化部署方案。",
            "citations": ["S1"],
        }],
        verifier=verifier,
    )

    statements = tuple(
        statement
        for section in result.draft.solution_sections
        for statement in section.statements
    )
    assert not any(
        statement.type is SolutionStatementType.ENTERPRISE_FACT
        for statement in statements
    )
    assert any(
        statement.type is SolutionStatementType.UNRESOLVED
        for statement in statements
    )


def test_return_time_admission_revalidation_remains_after_proposal_verification(
    monkeypatch,
):
    from apps.sales.services.solution_errors import SolutionDraftError

    initially_valid = admission(
        claim(
            SolutionStatementType.ENTERPRISE_FACT,
            "SalesMind 支持企业私有化部署。",
            section=SolutionSectionKey.DEPLOYMENT,
            citations=("S1",),
        ),
        allowed_labels=("S1",),
    )
    invalidated = admission(
        claim(
            SolutionStatementType.UNRESOLVED,
            "当前企业资料未确认私有化部署能力。",
            section=SolutionSectionKey.DEPLOYMENT,
        ),
    )
    state = {"valid": True}

    def current_admission(analysis, sources):
        return initially_valid if state["valid"] else invalidated

    verifier = RecordingVerifier(on_generate=lambda: state.update(valid=False))
    with pytest.raises(SolutionDraftError):
        run_pipeline(
            monkeypatch,
            admitted=initially_valid,
            admission_builder=current_admission,
            proposals=[{
                "section": "deployment",
                "text": "建议采用私有化部署方案。",
                "citations": ["S1"],
            }],
            verifier=verifier,
        )

    assert len(verifier.calls) == 1
