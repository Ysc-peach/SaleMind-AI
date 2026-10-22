"""A stalled indexing run can only be reset by an explicit, gated action.

There is no heartbeat, so elapsed time is the only signal available. Recovery
therefore stays a human action: a document with a previous successful run
returns to READY, one that never indexed returns to FAILED, and neither path
re-runs indexing or restores unfinished content.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.knowledge.exceptions import KnowledgeDocumentError
from apps.knowledge.models import KnowledgeDocument
from apps.knowledge.services.grounding_fact_attempts import FactExtractionOperationError
from apps.knowledge.services.indexing_recovery import (
    STALLED_RESET_ERROR_CODE,
    indexing_is_stalled,
    reset_stalled_indexing,
)
from apps.knowledge.tests.admin_grounding_fixtures import admin_actor  # noqa: F401


pytestmark = pytest.mark.django_db(transaction=True)


def _document(admin_actor, *, status='processing', minutes_ago=120, last_run=None):
    return KnowledgeDocument.objects.create(
        title='Stalled document',
        document_type='technical',
        source_file='knowledge/documents/stalled.md',
        original_filename='stalled.md',
        mime_type='text/markdown',
        file_size=32,
        checksum_sha256='c' * 64,
        status=status,
        processing_started_at=timezone.now() - timedelta(minutes=minutes_ago),
        indexing_run_id=uuid4(),
        last_index_run_id=last_run,
        last_indexed_at=timezone.now() if last_run else None,
        created_by=admin_actor,
    )


def test_stalled_run_with_a_previous_index_returns_to_ready(admin_actor):
    run_id = uuid4()
    document = _document(admin_actor, last_run=run_id)

    reset = reset_stalled_indexing(document.pk, actor_id=admin_actor.pk)

    reset.refresh_from_db()
    assert reset.status == 'ready'
    assert reset.error_code == STALLED_RESET_ERROR_CODE
    assert reset.last_index_run_id == run_id
    # The interrupted run id stays for audit; it is not rewritten.
    assert reset.indexing_run_id == document.indexing_run_id
    assert reset.processing_started_at is not None


def test_stalled_run_without_a_previous_index_returns_to_failed(admin_actor):
    document = _document(admin_actor, last_run=None)

    reset_stalled_indexing(document.pk, actor_id=admin_actor.pk)

    document.refresh_from_db()
    assert document.status == 'failed'
    assert document.error_code == STALLED_RESET_ERROR_CODE


def test_a_run_inside_the_expected_window_is_not_reset(admin_actor):
    document = _document(admin_actor, minutes_ago=1, last_run=uuid4())

    stalling = indexing_is_stalled(document)
    assert stalling is False
    with pytest.raises(KnowledgeDocumentError) as caught:
        reset_stalled_indexing(document.pk, actor_id=admin_actor.pk)

    assert caught.value.code == 'indexing_already_in_progress'
    document.refresh_from_db()
    assert document.status == 'processing'


def test_a_non_processing_document_is_not_reset(admin_actor):
    document = _document(admin_actor, status='ready', last_run=uuid4())

    with pytest.raises(KnowledgeDocumentError):
        reset_stalled_indexing(document.pk, actor_id=admin_actor.pk)


def test_a_business_admin_without_staff_flag_is_refused(admin_actor):
    document = _document(admin_actor, last_run=uuid4())
    actor = get_user_model().objects.create_user(
        username='role-only-admin', email='role-only-admin@example.com',
        role='admin', is_staff=False,
    )

    with pytest.raises(FactExtractionOperationError):
        reset_stalled_indexing(document.pk, actor_id=actor.pk)

    document.refresh_from_db()
    assert document.status == 'processing'


def test_document_without_processing_timestamp_counts_as_stalled(admin_actor):
    document = _document(admin_actor, last_run=uuid4())
    # The schema keeps the run id and its start time together, so a legacy row
    # without a heartbeat has neither.
    KnowledgeDocument.objects.filter(pk=document.pk).update(
        indexing_run_id=None, processing_started_at=None,
    )
    document.refresh_from_db()

    assert indexing_is_stalled(document) is True
    reset_stalled_indexing(document.pk, actor_id=admin_actor.pk)
    document.refresh_from_db()
    assert document.status == 'ready'
