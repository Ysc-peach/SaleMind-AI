"""Real PostgreSQL/pgvector retrieval with offline providers and no writes."""

import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.knowledge.models import KnowledgeDocument, KnowledgeChunk
from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider
from apps.sales.models import Customer, Opportunity, OpportunityRequirementAnalysis
from apps.sales.services.requirement_analysis_history import create_opportunity_requirement_analysis
from apps.sales.tests.solution_fakes import analysis_payload, SolutionFakeLLM
from apps.sales.tests.requirement_fakes import AnalysisFakeLLM


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw: pytest.fail("Only fake providers in automatic tests."))


@pytest.fixture
def history_and_knowledge(make_user):
    owner = make_user()
    customer = Customer.objects.create(name="受控企业", created_by=owner)
    opportunity = Opportunity.objects.create(customer=customer, project_name="历史需求项目", sales_owner=owner, created_by=owner)
    first = create_opportunity_requirement_analysis(opportunity, created_by=owner, llm_provider=AnalysisFakeLLM(
        content=json.dumps(analysis_payload(existing_environment="unclear", integration_requirement="unclear")),
    ))
    latest = create_opportunity_requirement_analysis(opportunity, created_by=owner, llm_provider=AnalysisFakeLLM(
        content=json.dumps(analysis_payload(data_security_requirement="conflict")),
    ))
    embedding = DeterministicEmbeddingProvider()
    document = KnowledgeDocument.objects.create(
        title="企业资料", document_type="technical", source_file="not-read-by-solution.txt",
        original_filename="企业资料.txt", mime_type="text/plain", file_size=1, checksum_sha256="a"*64,
        status="ready", last_indexed_at=timezone.now(), created_by=owner,
        embedding_provider=embedding.provider_name, embedding_model=embedding.model_name,
        embedding_dimensions=1024, chunk_count=1,
    )
    chunk = KnowledgeChunk.objects.create(
        document=document, chunk_index=0, content="企业产品支持私有化部署。",
        embedding=embedding.embed_query("企业产品支持私有化部署。"), char_count=14,
        section_title="部署", source_reference="《企业资料》部署",
    )
    return first, latest, embedding, chunk


def test_selected_history_real_cosine_retrieval_no_business_writes(history_and_knowledge):
    from apps.sales.services.solution_draft import generate_grounded_solution_draft

    first, latest, embedding, chunk = history_and_knowledge
    models = (Customer, Opportunity, OpportunityRequirementAnalysis, KnowledgeDocument)
    before = {model: list(model.objects.values()) for model in models}
    before_chunks = KnowledgeChunk.objects.count()
    llm = SolutionFakeLLM()

    def forbid_writes(execute, sql, params, many, context):
        assert sql.lstrip().upper().startswith("SELECT"), "Solution must only execute SELECT statements."
        return execute(sql, params, many, context)

    with connection.execute_wrapper(forbid_writes), CaptureQueriesContext(connection) as queries:
        result = generate_grounded_solution_draft(first, embedding_provider=embedding, llm_provider=llm)
    assert result.analysis_id == first.pk != latest.pk
    assert result.generation_status == "generated"
    assert result.readiness.status == "ready_with_gaps"
    assert len(llm.calls) == 2
    retrieval_queries = [query for query in queries if "<=>" in query["sql"]]
    admission_queries = [
        query for query in queries
        if '"knowledge_enterprisegroundingfact"' in query["sql"]
    ]
    assert len(retrieval_queries) == 3
    # Admission is read once before generation and revalidated once after the
    # external verifier call so concurrent provenance changes fail closed.
    assert len(admission_queries) == 2
    assert [source.chunk_id for source in result.sources] == [chunk.pk]
    assert result.sources[0].section_title == "部署"
    assert result.sources[0].source_reference == "《企业资料》部署"
    assert {model: list(model.objects.values()) for model in models} == before
    assert KnowledgeChunk.objects.count() == before_chunks


def test_blocked_saved_history_performs_zero_queries(history_and_knowledge, monkeypatch, django_assert_num_queries):
    from apps.sales.services import solution_draft as service

    _, latest, _, _ = history_and_knowledge
    def forbidden(*a, **kw):
        pytest.fail("Blocked run must never reach a provider.")
    monkeypatch.setattr("apps.knowledge.services.search.get_embedding_provider", forbidden)
    monkeypatch.setattr(service, "get_llm_provider", forbidden)
    with django_assert_num_queries(0):
        result = service.generate_grounded_solution_draft(latest)
    assert result.generation_status == "blocked_by_readiness"
    assert result.draft is None and result.sources == ()
