"""Independent PostgreSQL connections prove locks and tokens, not button disabling."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from threading import Barrier, Event

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, connections

from apps.knowledge.models import EnterpriseGroundingFact, GroundingFactExtractionAttempt
from apps.knowledge.services.grounding_fact_attempts import cancel_extraction, FactExtractionOperationError
from apps.knowledge.services.grounding_fact_operations import run_document_fact_extraction
from apps.knowledge.services.indexing import reindex_document
from apps.knowledge.exceptions import KnowledgeDocumentError, KnowledgeDocumentErrorCode
from .admin_grounding_fixtures import admin_actor, ready_document
from .embedding_fakes import DeterministicEmbeddingProvider
from .test_grounding_fact_extraction import ExtractionFakeLLM, payload

pytestmark = pytest.mark.django_db(transaction=True)


def worker(function):
    close_old_connections()
    try:
        return function()
    finally:
        connections.close_all()


def test_parallel_claims_make_one_model_request(admin_actor, ready_document):
    document, chunk = ready_document
    barrier, started, release = Barrier(2), Event(), Event()
    def block():
        started.set()
        assert release.wait(10), 'Controlled provider was not released'
    provider = ExtractionFakeLLM(payload(chunk.pk), callback=block)
    def invoke():
        barrier.wait(10)
        return run_document_fact_extraction(document.pk, actor_id=admin_actor.pk,
            expected_index_run_id=document.last_index_run_id, llm_provider=provider)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, invoke) for _ in range(2)]
        try:
            assert started.wait(10)
            finished, _ = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
            assert len(finished) == 1
            assert next(iter(finished)).result().state == 'running'
        finally:
            release.set()
        assert sorted(future.result(10).state for future in futures) == ['running','succeeded']
    assert len(provider.calls) == 1
    assert GroundingFactExtractionAttempt.objects.count() == 1
    assert EnterpriseGroundingFact.objects.count() == 1


def test_database_slot_rejects_direct_parallel_inserts(admin_actor, ready_document):
    document, _ = ready_document
    barrier = Barrier(2)
    def insert():
        barrier.wait(10)
        try:
            GroundingFactExtractionAttempt.objects.create(document_id=document.pk,
                requested_by_id=admin_actor.pk, index_run_id=document.last_index_run_id)
            return 'created'
        except IntegrityError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, insert) for _ in range(2)]
        assert sorted(future.result(10) for future in futures) == ['conflict','created']
    assert GroundingFactExtractionAttempt.objects.count() == 1


@pytest.mark.parametrize('change', ['cancel_and_retry', 'reindex', 'failed_reindex'])
def test_slow_old_result_cannot_publish_after_cancel_or_reindex(admin_actor, ready_document, settings, tmp_path, change):
    document, chunk = ready_document
    settings.MEDIA_ROOT = tmp_path
    document.source_file.save('capability.md',SimpleUploadedFile('capability.md',chunk.content.encode()))
    started, release = Event(), Event()
    def block():
        started.set()
        assert release.wait(10), 'Controlled provider was not released'
    slow = ExtractionFakeLLM(payload(chunk.pk), callback=block)
    def invoke():
        try:
            run_document_fact_extraction(document.pk, actor_id=admin_actor.pk,
                expected_index_run_id=document.last_index_run_id, llm_provider=slow)
        except FactExtractionOperationError as error:
            return error.code
        return 'unexpected_success'
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker, invoke)
        try:
            assert started.wait(10)
            old = GroundingFactExtractionAttempt.objects.get()
            if change == 'cancel_and_retry':
                cancel_extraction(document.pk, actor_id=admin_actor.pk, attempt_id=old.pk)
                result = run_document_fact_extraction(document.pk, actor_id=admin_actor.pk,
                    expected_index_run_id=document.last_index_run_id,
                    retry_after_attempt_id=old.pk, llm_provider=ExtractionFakeLLM(payload(chunk.pk)))
                assert result.state == 'succeeded'
            elif change == 'reindex':
                reindex_document(document.pk, provider=DeterministicEmbeddingProvider())
            else:
                class BrokenEmbedding(DeterministicEmbeddingProvider):
                    def embed_documents(self, texts):
                        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR)
                original_run = document.last_index_run_id
                with pytest.raises(KnowledgeDocumentError):
                    reindex_document(document.pk, provider=BrokenEmbedding())
                document.refresh_from_db()
                assert document.status == 'ready' and document.last_index_run_id == original_run
                assert document.indexing_run_id is None
        finally:
            release.set()
        code = future.result(10)
    assert code == ('fact_extraction_cancelled' if change=='cancel_and_retry' else 'fact_extraction_index_changed')
    old.refresh_from_db()
    assert old.status == ('cancelled' if change=='cancel_and_retry' else 'failed')
    assert EnterpriseGroundingFact.objects.count() == (1 if change=='cancel_and_retry' else 0)
    if change == 'failed_reindex':
        with pytest.raises(FactExtractionOperationError) as caught:
            run_document_fact_extraction(document.pk,actor_id=admin_actor.pk,
                expected_index_run_id=document.last_index_run_id,
                llm_provider=ExtractionFakeLLM(payload(chunk.pk)))
        assert caught.value.code == 'fact_extraction_retry_required'
        result = run_document_fact_extraction(document.pk,actor_id=admin_actor.pk,
            expected_index_run_id=document.last_index_run_id,retry_after_attempt_id=old.pk,
            llm_provider=ExtractionFakeLLM(payload(chunk.pk)))
        assert result.state == 'succeeded'
