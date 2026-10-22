"""Explicit recovery for an indexing run that stopped without an outcome."""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.knowledge.models import KnowledgeDocument, KnowledgeDocumentStatus
from apps.knowledge.services.grounding_fact_attempts import (
    require_actor,
    require_no_outer_transaction,
)


logger = logging.getLogger(__name__)

STALLED_RESET_ERROR_CODE = "indexing_stalled_reset"
STALLED_RESET_SAFE_MESSAGE = (
    "索引执行超过预期时间且没有结果，已由管理员确认重置；未完成的内容不进入检索。"
)


def indexing_is_stalled(document, *, now=None) -> bool:
    """Only a processing run past the configured window counts as stalled.

    There is no heartbeat, so elapsed time is the only available signal. It is
    deliberately not treated as proof that a live run is dead; the recovery
    entry point stays an explicit human action.
    """

    if document.status != KnowledgeDocumentStatus.PROCESSING:
        return False
    if document.processing_started_at is None:
        return True
    now = now or timezone.now()
    return now - document.processing_started_at >= timedelta(
        seconds=settings.KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS
    )


def reset_stalled_indexing(document_id: int, *, actor_id: int) -> KnowledgeDocument:
    """Reset one stalled run on explicit request; never re-runs indexing.

    A document with a previous successful run returns to READY because that
    index is still the current one; a document that never completed returns to
    FAILED. ``indexing_run_id`` and ``processing_started_at`` stay untouched as
    audit facts, and the reason is recorded in the safe error code.
    """

    require_no_outer_transaction()
    with transaction.atomic():
        actor = require_actor(actor_id)
        document = KnowledgeDocument.objects.select_for_update().get(pk=document_id)
        if not indexing_is_stalled(document):
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INDEXING_ALREADY_IN_PROGRESS
            )
        recovered = document.last_index_run_id is not None
        document.status = (
            KnowledgeDocumentStatus.READY
            if recovered
            else KnowledgeDocumentStatus.FAILED
        )
        document.error_code = STALLED_RESET_ERROR_CODE
        document.error_message = STALLED_RESET_SAFE_MESSAGE
        document.save(
            update_fields=["status", "error_code", "error_message", "updated_at"]
        )
    logger.info(
        "stalled indexing reset document_id=%s actor_id=%s recovered=%s",
        document_id, actor.pk, recovered,
    )
    return document
