"""Knowledge vector search contracts backed by PostgreSQL pgvector."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument


pytestmark = pytest.mark.django_db


def vector(*values):
    return [*values, *([0.0] * (1024 - len(values)))]


class ControlledQueryProvider:
    provider_name = "search-fake"
    model_name = "unit-space"
    dimensions = 1024

    def __init__(self, query_vector):
        self.query_vector = query_vector
        self.query_calls = []

    def embed_query(self, text):
        self.query_calls.append(text)
        return self.query_vector

    def embed_documents(self, texts):
        raise AssertionError("Search must call embed_query(), not embed_documents().")


def create_user(*, role=UserRole.ADMIN, suffix="owner"):
    return get_user_model().objects.create_user(
        username=f"search-{suffix}",
        email=f"search-{suffix}@example.com",
        role=role,
        password="StrongPassword123!",
    )


def create_document(
    *,
    created_by,
    title="Searchable document",
    document_type=KnowledgeDocument.DocumentType.TECHNICAL,
    status=KnowledgeDocument.Status.READY,
    provider_name="search-fake",
    model_name="unit-space",
    dimensions=1024,
    **overrides,
):
    values = {
        "title": title,
        "document_type": document_type,
        "source_file": "knowledge/documents/test/search.txt",
        "original_filename": "search.txt",
        "mime_type": "text/plain",
        "file_size": 100,
        "checksum_sha256": "a" * 64,
        "status": status,
        "embedding_provider": provider_name,
        "embedding_model": model_name,
        "embedding_dimensions": dimensions,
        "last_indexed_at": timezone.now() if status == "ready" else None,
        "created_by": created_by,
    }
    values.update(overrides)
    return KnowledgeDocument.objects.create(**values)


def create_chunk(
    *,
    document,
    chunk_index,
    embedding,
    content,
    page_number=None,
    section_title="",
    source_reference="",
):
    return KnowledgeChunk.objects.create(
        document=document,
        chunk_index=chunk_index,
        content=content,
        embedding=embedding,
        page_number=page_number,
        section_title=section_title,
        source_reference=source_reference,
        metadata={"internal": "not part of search results"},
        char_count=len(content),
    )


def test_search_uses_query_embedding_and_real_pgvector_cosine_ranking():
    from apps.knowledge.services.search import search_knowledge

    owner = create_user()
    document = create_document(
        created_by=owner,
        title="SalesMind AI 产品白皮书",
    )
    closest = create_chunk(
        document=document,
        chunk_index=0,
        embedding=vector(1.0, 0.0),
        content="Private deployment is supported.",
        page_number=12,
        source_reference="《SalesMind AI 产品白皮书》第 12 页",
    )
    middle = create_chunk(
        document=document,
        chunk_index=1,
        embedding=vector(0.8, 0.6),
        content="Deployment architecture details.",
        section_title="部署 > PostgreSQL 配置",
        source_reference="《SalesMind AI 产品白皮书》部署 > PostgreSQL 配置",
    )
    furthest = create_chunk(
        document=document,
        chunk_index=2,
        embedding=vector(0.0, 1.0),
        content="Unrelated content.",
    )
    provider = ControlledQueryProvider(vector(1.0, 0.0))

    results = search_knowledge(
        query="私有化部署",
        top_k=3,
        provider=provider,
    )

    assert provider.query_calls == ["私有化部署"]
    assert [result.chunk_id for result in results] == [
        closest.id,
        middle.id,
        furthest.id,
    ]
    assert results[0].document_id == document.id
    assert results[0].document_title == "SalesMind AI 产品白皮书"
    assert results[0].document_type == "technical"
    assert results[0].original_filename == "search.txt"
    assert results[0].content == "Private deployment is supported."
    assert results[0].page_number == 12
    assert results[0].section_title is None
    assert results[0].source_reference == "《SalesMind AI 产品白皮书》第 12 页"
    assert results[0].similarity == pytest.approx(1.0)
    assert results[1].similarity == pytest.approx(0.8)
    assert results[2].similarity == pytest.approx(0.0)


def test_search_only_includes_ready_chunks_in_the_current_embedding_space():
    from apps.knowledge.services.search import search_knowledge

    owner = create_user(suffix="compatibility")
    matching = create_document(created_by=owner, title="Matching")
    active_reindex = create_document(
        created_by=owner,
        title="Active reindex",
        indexing_run_id=uuid4(),
        processing_started_at=timezone.now(),
    )
    pending = create_document(
        created_by=owner,
        title="Pending",
        status=KnowledgeDocument.Status.PENDING,
    )
    processing = create_document(
        created_by=owner,
        title="Processing",
        status=KnowledgeDocument.Status.PROCESSING,
        indexing_run_id=uuid4(),
        processing_started_at=timezone.now(),
    )
    failed = create_document(
        created_by=owner,
        title="Failed",
        status=KnowledgeDocument.Status.FAILED,
    )
    wrong_provider = create_document(
        created_by=owner,
        title="Wrong provider",
        provider_name="old-provider",
    )
    wrong_model = create_document(
        created_by=owner,
        title="Wrong model same dimensions",
        model_name="old-model",
    )
    wrong_dimensions = create_document(
        created_by=owner,
        title="Wrong dimensions",
        dimensions=768,
    )
    documents = [
        matching,
        active_reindex,
        pending,
        processing,
        failed,
        wrong_provider,
        wrong_model,
        wrong_dimensions,
    ]
    chunks = [
        create_chunk(
            document=document,
            chunk_index=0,
            embedding=vector(1.0, 0.0),
            content=document.title,
        )
        for document in documents
    ]

    results = search_knowledge(
        query="compatible space",
        top_k=20,
        provider=ControlledQueryProvider(vector(1.0, 0.0)),
    )

    assert [result.chunk_id for result in results] == [chunks[0].id, chunks[1].id]


def test_search_filters_document_type_limits_top_k_and_uses_id_tiebreaker():
    from apps.knowledge.services.search import search_knowledge

    owner = create_user(suffix="filter")
    technical = create_document(created_by=owner, document_type="technical")
    product = create_document(
        created_by=owner,
        title="Product",
        document_type="product",
    )
    lower_id = create_chunk(
        document=technical,
        chunk_index=0,
        embedding=vector(1.0, 0.0),
        content="Technical A",
    )
    higher_id = create_chunk(
        document=technical,
        chunk_index=1,
        embedding=vector(1.0, 0.0),
        content="Technical B",
    )
    create_chunk(
        document=product,
        chunk_index=0,
        embedding=vector(1.0, 0.0),
        content="Product",
    )

    results = search_knowledge(
        query="technical",
        top_k=1,
        document_type="technical",
        provider=ControlledQueryProvider(vector(1.0, 0.0)),
    )

    assert [result.chunk_id for result in results] == [lower_id.id]
    assert lower_id.id < higher_id.id


def test_search_similarity_is_not_clamped_to_zero():
    from apps.knowledge.services.search import search_knowledge

    owner = create_user(suffix="negative")
    document = create_document(created_by=owner)
    chunk = create_chunk(
        document=document,
        chunk_index=0,
        embedding=vector(-1.0, 0.0),
        content="Opposite vector",
    )

    results = search_knowledge(
        query="opposite",
        provider=ControlledQueryProvider(vector(1.0, 0.0)),
    )

    assert results[0].chunk_id == chunk.id
    assert results[0].similarity == pytest.approx(-1.0)


def test_search_returns_empty_list_when_no_compatible_chunks_exist():
    from apps.knowledge.services.search import search_knowledge

    provider = ControlledQueryProvider(vector(1.0, 0.0))

    results = search_knowledge(query="nothing indexed", provider=provider)

    assert results == []
    assert provider.query_calls == ["nothing indexed"]
