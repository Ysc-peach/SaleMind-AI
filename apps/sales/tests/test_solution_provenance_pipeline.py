"""Production pipeline admits facts before the verifier and generates proposals only."""

import hashlib
import json
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus as Approval,
    EnterpriseGroundingFactStatus as FactStatus,
    KnowledgeDocument,
)
from apps.llm.base import LLMGeneration
from apps.llm.tests.fakes import DeterministicFakeLLM
from apps.rag.tests.test_answering import search_result
from apps.sales.services.solution_schema import SolutionStatementType
from apps.sales.tests.solution_fakes import analysis_record


pytestmark = pytest.mark.django_db


class ProposalLLM(DeterministicFakeLLM):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload

    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        return LLMGeneration(content=json.dumps(self.payload, ensure_ascii=False))


class AlwaysSupportedVerifier(DeterministicFakeLLM):
    def generate(self, messages, *, max_output_tokens=None):
        super().generate(messages, max_output_tokens=max_output_tokens)
        import html
        import re

        match = re.search(
            r"<grounding_claim_packets>(.*?)</grounding_claim_packets>",
            messages[-1]["content"],
            flags=re.DOTALL,
        )
        packets = json.loads(html.unescape(match.group(1)))
        return LLMGeneration(content=json.dumps({"results": [
            {
                "location": item["location"],
                "relation": "SUPPORTED",
                "atomicity": "ATOMIC",
            }
            for item in packets["claims"]
        ]}))


@pytest.fixture
def admitted_source(django_user_model):
    actor = django_user_model.objects.create_user(
        username="pipeline-admin",
        email="pipeline-admin@example.com",
        role="admin",
        password="StrongPassword123!",
    )
    run_id = uuid4()
    content = "SalesMind 当前版本支持企业私有化部署。"
    document = KnowledgeDocument.objects.create(
        title="Approved deployment",
        document_type="technical",
        source_file="knowledge/documents/approved.md",
        original_filename="approved.md",
        mime_type="text/markdown",
        file_size=20,
        checksum_sha256="f" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=run_id,
        created_by=actor,
    )
    result = search_result(
        chunk_id=73,
        document_id=document.pk,
        content=content,
        document_title=document.title,
        original_filename=document.original_filename,
    )

    def create_fact(*, subject_key="private_deployment", status=FactStatus.CONFIRMED_SUPPORTED,
                    approval=Approval.APPROVED):
        approved = approval == Approval.APPROVED
        return EnterpriseGroundingFact.objects.create(
            subject_key=subject_key,
            statement=content,
            status=status,
            source_document=document,
            source_chunk_id=result.chunk_id,
            source_excerpt=content,
            source_index_run_id=run_id,
            source_content_hash=hashlib.sha256(content.encode()).hexdigest(),
            approval_status=approval,
            approved_by=actor if approved else None,
            approved_at=timezone.now() if approved else None,
        )

    return result, create_fact


@pytest.mark.parametrize("forbidden_type", ["customer_fact", "enterprise_fact", "unresolved"])
def test_generation_ir_rejects_nonproposal_claim_types(forbidden_type):
    from apps.sales.services.solution_schema import parse_atomic_solution_proposals
    from apps.sales.services.solution_errors import SolutionDraftError

    content = json.dumps({"proposals": [{
        "section": "overall_approach",
        "statement_type": forbidden_type,
        "text": "模型无权生成此类事实。",
        "citations": ["S1"],
    }]})

    with pytest.raises(SolutionDraftError):
        parse_atomic_solution_proposals(content, allowed_source_labels=("S1",))


def test_approved_fact_is_program_claim_and_proposal_uses_approved_source(
    monkeypatch,
    admitted_source,
):
    from apps.sales.services import solution_draft

    result, create_fact = admitted_source
    create_fact()
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kwargs: [result])
    generator = ProposalLLM({"proposals": [{
        "section": "deployment",
        "text": "建议采用私有化部署方向。",
        "citations": ["S1"],
    }]})
    verifier = AlwaysSupportedVerifier()

    output = solution_draft.generate_grounded_solution_draft(
        analysis_record(), llm_provider=generator, verifier_provider=verifier,
    )

    statements = tuple(
        statement
        for section in output.draft.solution_sections
        for statement in section.statements
    )
    assert any(
        item.type is SolutionStatementType.ENTERPRISE_FACT
        and item.text == "SalesMind 当前版本支持企业私有化部署。"
        for item in statements
    )
    assert any(item.type is SolutionStatementType.PROPOSAL for item in statements)
    assert len(generator.calls) == 1
    assert len(verifier.calls) == 1


@pytest.mark.parametrize(
    "subject_key",
    [
        "server_compatibility",
        "oa_integration",
        "sso_integration",
        "kubernetes_deployment",
        "oracle_compatibility",
    ],
)
def test_n4_cannot_be_enterprise_fact_even_when_verifier_always_supports(
    monkeypatch,
    admitted_source,
    subject_key,
):
    from apps.sales.services import solution_draft

    result, create_fact = admitted_source
    create_fact(subject_key=subject_key, status=FactStatus.UNCONFIRMED)
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kwargs: [result])
    generator = ProposalLLM({"proposals": []})
    verifier = AlwaysSupportedVerifier()

    output = solution_draft.generate_grounded_solution_draft(
        analysis_record(), llm_provider=generator, verifier_provider=verifier,
    )

    statements = tuple(
        statement
        for section in output.draft.solution_sections
        for statement in section.statements
    )
    assert not any(item.type is SolutionStatementType.ENTERPRISE_FACT for item in statements)
    assert any(item.type is SolutionStatementType.UNRESOLVED for item in statements)
    assert len(verifier.calls) == 1


def test_proposed_confirmed_fact_cannot_authorize_proposal_citation(
    monkeypatch,
    admitted_source,
):
    from apps.sales.services import solution_draft
    from apps.sales.services.solution_errors import SolutionDraftError

    result, create_fact = admitted_source
    create_fact(approval=Approval.PROPOSED)
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kwargs: [result])
    generator = ProposalLLM({"proposals": [{
        "section": "deployment",
        "text": "建议采用私有化部署方向。",
        "citations": ["S1"],
    }]})
    verifier = AlwaysSupportedVerifier()

    with pytest.raises(SolutionDraftError):
        solution_draft.generate_grounded_solution_draft(
            analysis_record(), llm_provider=generator, verifier_provider=verifier,
        )

    assert len(generator.calls) == 1
    assert len(verifier.calls) == 0


def test_generation_prompt_contains_only_admitted_enterprise_evidence(
    monkeypatch,
    admitted_source,
):
    from apps.sales.services import solution_draft

    result, create_fact = admitted_source
    create_fact(approval=Approval.PROPOSED)
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kwargs: [result])
    generator = ProposalLLM({"proposals": []})
    verifier = AlwaysSupportedVerifier()

    solution_draft.generate_grounded_solution_draft(
        analysis_record(), llm_provider=generator, verifier_provider=verifier,
    )

    assert result.content not in generator.calls[0][-1]["content"]
    assert "proposal" in generator.calls[0][0]["content"].lower()
    assert "enterprise_fact" not in generator.calls[0][0]["content"]

