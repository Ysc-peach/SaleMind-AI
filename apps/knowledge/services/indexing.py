"""Initial and zero-downtime knowledge document indexing orchestration."""

from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.knowledge.embeddings import get_embedding_provider
from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument
from apps.knowledge.parsers import parse_document
from apps.knowledge.services.chunking import ChunkDraft, chunk_segments


def index_document(
    document_id: int,
    *,
    provider: EmbeddingProvider | None = None,
) -> KnowledgeDocument:
    """Index one pending document and return its persisted ready state."""

    document, run_id = _start_indexing(document_id)
    try:
        chunks, embeddings, embedding_provider = _prepare_index_payload(
            document,
            provider,
        )
        return _complete_indexing(
            document_id=document_id,
            run_id=run_id,
            chunks=chunks,
            embeddings=embeddings,
            provider=embedding_provider,
        )
    except KnowledgeDocumentError as error:
        if not _mark_initial_indexing_failed(document_id, run_id, error):
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT
            ) from None
        raise
    except Exception:
        error = KnowledgeDocumentError(KnowledgeDocumentErrorCode.INDEXING_FAILED)
        if not _mark_initial_indexing_failed(document_id, run_id, error):
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT
            ) from None
        raise error from None


def reindex_document(
    document_id: int,
    *,
    provider: EmbeddingProvider | None = None,
) -> KnowledgeDocument:
    """Rebuild one ready document while its current chunks remain available."""

    document, run_id = _start_reindexing(document_id)
    try:
        chunks, embeddings, embedding_provider = _prepare_index_payload(
            document,
            provider,
        )
        return _complete_reindexing(
            document_id=document_id,
            run_id=run_id,
            chunks=chunks,
            embeddings=embeddings,
            provider=embedding_provider,
        )
    except KnowledgeDocumentError as error:
        if not _mark_reindexing_failed(document_id, run_id, error):
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT
            ) from None
        raise
    except Exception:
        error = KnowledgeDocumentError(KnowledgeDocumentErrorCode.REINDEX_FAILED)
        if not _mark_reindexing_failed(document_id, run_id, error):
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT
            ) from None
        raise error from None


def _prepare_index_payload(
    document: KnowledgeDocument,
    provider: EmbeddingProvider | None,
) -> tuple[list[ChunkDraft], list[list[float]], EmbeddingProvider]:
    segments = _parse_source_file(document)
    chunks = chunk_segments(segments)
    if not chunks:
        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.NO_INDEXABLE_CONTENT)
    embedding_provider = (
        provider if provider is not None else get_embedding_provider()
    )
    embeddings = embedding_provider.embed_documents(
        [chunk.content for chunk in chunks]
    )
    if len(embeddings) != len(chunks):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_INVALID_RESPONSE
        )
    return chunks, embeddings, embedding_provider


def _parse_source_file(document: KnowledgeDocument):
    try:
        source = document.source_file.open("rb")
    except (OSError, TypeError, ValueError):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.INVALID_FILE
        ) from None
    with source:
        return parse_document(source, document.original_filename)


def _start_indexing(document_id: int) -> tuple[KnowledgeDocument, UUID]:
    run_id = uuid4()
    with transaction.atomic():
        document = KnowledgeDocument.objects.select_for_update().get(pk=document_id)
        if document.status != KnowledgeDocument.Status.PENDING:
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INVALID_INDEXING_STATE
            )
        document.status = KnowledgeDocument.Status.PROCESSING
        document.indexing_run_id = run_id
        document.processing_started_at = timezone.now()
        document.error_code = ""
        document.error_message = ""
        document.save(
            update_fields=[
                "status",
                "indexing_run_id",
                "processing_started_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
    return document, run_id


def _start_reindexing(document_id: int) -> tuple[KnowledgeDocument, UUID]:
    run_id = uuid4()
    with transaction.atomic():
        document = KnowledgeDocument.objects.select_for_update().get(pk=document_id)
        if document.status != KnowledgeDocument.Status.READY:
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INVALID_REINDEX_STATE
            )
        started_at = timezone.now()
        if document.indexing_run_id is not None:
            stale_timeout = timedelta(
                seconds=settings.KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS
            )
            if started_at - document.processing_started_at < stale_timeout:
                raise KnowledgeDocumentError(
                    KnowledgeDocumentErrorCode.INDEXING_ALREADY_IN_PROGRESS
                )
        document.indexing_run_id = run_id
        document.processing_started_at = started_at
        document.error_code = ""
        document.error_message = ""
        document.save(
            update_fields=[
                "indexing_run_id",
                "processing_started_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
    return document, run_id


def _complete_indexing(
    *,
    document_id: int,
    run_id: UUID,
    chunks: list[ChunkDraft],
    embeddings: list[list[float]],
    provider: EmbeddingProvider,
) -> KnowledgeDocument:
    with transaction.atomic():
        document = KnowledgeDocument.objects.select_for_update().get(pk=document_id)
        if (
            document.status != KnowledgeDocument.Status.PROCESSING
            or document.indexing_run_id != run_id
        ):
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT
            )
        KnowledgeChunk.objects.bulk_create(
            _build_chunk_records(document, chunks, embeddings)
        )
        document.status = KnowledgeDocument.Status.READY
        document.chunk_count = len(chunks)
        document.embedding_provider = provider.provider_name
        document.embedding_model = provider.model_name
        document.embedding_dimensions = provider.dimensions
        document.last_indexed_at = timezone.now()
        document.indexing_run_id = None
        document.processing_started_at = None
        document.error_code = ""
        document.error_message = ""
        document.save(
            update_fields=[
                "status",
                "chunk_count",
                "embedding_provider",
                "embedding_model",
                "embedding_dimensions",
                "last_indexed_at",
                "indexing_run_id",
                "processing_started_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
    return document


def _complete_reindexing(
    *,
    document_id: int,
    run_id: UUID,
    chunks: list[ChunkDraft],
    embeddings: list[list[float]],
    provider: EmbeddingProvider,
) -> KnowledgeDocument:
    with transaction.atomic():
        document = KnowledgeDocument.objects.select_for_update().get(pk=document_id)
        if (
            document.status != KnowledgeDocument.Status.READY
            or document.indexing_run_id != run_id
        ):
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT
            )
        document.chunks.all().delete()
        KnowledgeChunk.objects.bulk_create(
            _build_chunk_records(document, chunks, embeddings)
        )
        document.chunk_count = len(chunks)
        document.embedding_provider = provider.provider_name
        document.embedding_model = provider.model_name
        document.embedding_dimensions = provider.dimensions
        document.last_indexed_at = timezone.now()
        document.indexing_run_id = None
        document.processing_started_at = None
        document.error_code = ""
        document.error_message = ""
        document.save(
            update_fields=[
                "chunk_count",
                "embedding_provider",
                "embedding_model",
                "embedding_dimensions",
                "last_indexed_at",
                "indexing_run_id",
                "processing_started_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
    return document


def _build_chunk_records(
    document: KnowledgeDocument,
    chunks: list[ChunkDraft],
    embeddings: list[list[float]],
) -> list[KnowledgeChunk]:
    return [
        KnowledgeChunk(
            document=document,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            embedding=embedding,
            page_number=chunk.page_number,
            section_title=chunk.section_title or "",
            source_reference=chunk.source_reference,
            metadata=chunk.metadata,
            char_count=chunk.char_count,
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]


def _mark_initial_indexing_failed(
    document_id: int,
    run_id: UUID,
    error: KnowledgeDocumentError,
) -> bool:
    with transaction.atomic():
        document = KnowledgeDocument.objects.select_for_update().get(pk=document_id)
        if (
            document.status != KnowledgeDocument.Status.PROCESSING
            or document.indexing_run_id != run_id
        ):
            return False

        KnowledgeChunk.objects.filter(document_id=document_id).delete()
        document.status = KnowledgeDocument.Status.FAILED
        document.chunk_count = 0
        document.embedding_provider = ""
        document.embedding_model = ""
        document.embedding_dimensions = None
        document.last_indexed_at = None
        document.indexing_run_id = None
        document.processing_started_at = None
        document.error_code = error.code
        document.error_message = error.safe_message
        document.save(
            update_fields=[
                "status",
                "chunk_count",
                "embedding_provider",
                "embedding_model",
                "embedding_dimensions",
                "last_indexed_at",
                "indexing_run_id",
                "processing_started_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
    return True


def _mark_reindexing_failed(
    document_id: int,
    run_id: UUID,
    error: KnowledgeDocumentError,
) -> bool:
    with transaction.atomic():
        document = KnowledgeDocument.objects.select_for_update().get(pk=document_id)
        if (
            document.status != KnowledgeDocument.Status.READY
            or document.indexing_run_id != run_id
        ):
            return False

        document.indexing_run_id = None
        document.processing_started_at = None
        document.error_code = error.code
        document.error_message = error.safe_message
        document.save(
            update_fields=[
                "indexing_run_id",
                "processing_started_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
    return True
