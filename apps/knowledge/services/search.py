"""Exact pgvector retrieval for the shared enterprise knowledge base."""

from dataclasses import dataclass

from pgvector.django import CosineDistance

from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.knowledge.embeddings.factory import get_embedding_provider
from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult:
    """Safe retrieval result with the source fields needed for citation."""

    chunk_id: int
    document_id: int
    document_title: str
    document_type: str
    original_filename: str
    content: str
    page_number: int | None
    section_title: str | None
    source_reference: str
    similarity: float


def search_knowledge(
    *,
    query: str,
    top_k: int = 5,
    document_type: str | None = None,
    provider: EmbeddingProvider | None = None,
) -> list[KnowledgeSearchResult]:
    """Embed a query and retrieve compatible ready chunks by cosine distance."""

    active_provider = provider if provider is not None else get_embedding_provider()
    query_embedding = active_provider.embed_query(query)

    chunks = KnowledgeChunk.objects.select_related("document").filter(
        document__status=KnowledgeDocument.Status.READY,
        document__embedding_provider=active_provider.provider_name,
        document__embedding_model=active_provider.model_name,
        document__embedding_dimensions=active_provider.dimensions,
    )
    if document_type is not None:
        chunks = chunks.filter(document__document_type=document_type)

    ranked_chunks = chunks.annotate(
        distance=CosineDistance("embedding", query_embedding)
    ).order_by("distance", "id")[:top_k]

    return [
        KnowledgeSearchResult(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_title=chunk.document.title,
            document_type=chunk.document.document_type,
            original_filename=chunk.document.original_filename,
            content=chunk.content,
            page_number=chunk.page_number,
            section_title=chunk.section_title or None,
            source_reference=chunk.source_reference,
            similarity=1.0 - float(chunk.distance),
        )
        for chunk in ranked_chunks
    ]
