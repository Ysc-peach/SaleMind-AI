"""Persistent claim/retry/cancel behavior, not client button state."""
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from apps.knowledge.models import GroundingFactExtractionAttempt, EnterpriseGroundingFact
from .admin_grounding_fixtures import admin_actor, ready_document, attempt_factory

pytestmark = pytest.mark.django_db(transaction=True)


def operations():
    from importlib.util import find_spec
    assert find_spec('apps.knowledge.services.grounding_fact_attempts'), 'Attempt state service missing'
    from apps.knowledge.services import grounding_fact_attempts
    return grounding_fact_attempts


def claim(actor, document, **kwargs):
    return operations().claim_extraction(document.pk, actor_id=actor.pk,
        expected_index_run_id=document.last_index_run_id, **kwargs)


def test_claim_is_persistent_and_duplicate_is_running(admin_actor, ready_document):
    document, _ = ready_document
    first = claim(admin_actor, document)
    second = claim(admin_actor, document)
    assert first.state == 'claimed'
    assert second.state == 'running'
    assert first.attempt_id == second.attempt_id
    assert GroundingFactExtractionAttempt.objects.count() == 1


@pytest.mark.parametrize('count', [0, 2])
def test_completed_claim_replays_even_when_empty(admin_actor, ready_document, attempt_factory, count):
    previous = attempt_factory(status='succeeded', finished_at=timezone.now(), proposed_count=count)
    result = claim(admin_actor, ready_document[0])
    assert result.state == 'succeeded'
    assert result.proposed_count == count
    assert result.attempt_id == previous.pk
    assert GroundingFactExtractionAttempt.objects.count() == 1


def test_historical_facts_do_not_fabricate_attempt_history(admin_actor, ready_document):
    document, chunk = ready_document
    EnterpriseGroundingFact.objects.create(subject_key='private_deployment', statement='Supported',
        status='confirmed_supported', source_document=document, source_chunk_id=chunk.pk,
        source_excerpt='私有化部署', source_index_run_id=document.last_index_run_id,
        source_content_hash='b'*64)
    result = claim(admin_actor, document)
    assert result.state == 'legacy_facts'
    assert result.proposed_count == 1
    assert not GroundingFactExtractionAttempt.objects.exists()


@pytest.mark.parametrize('status', ['failed', 'cancelled'])
def test_retry_requires_exact_latest_failed_or_cancelled_attempt(admin_actor, ready_document, attempt_factory, status):
    ops = operations()
    document, _ = ready_document
    old = attempt_factory(status=status, finished_at=timezone.now(), error_code='fact_extraction_failed')
    with pytest.raises(ops.FactExtractionOperationError) as caught:
        claim(admin_actor, document)
    assert caught.value.code == 'fact_extraction_retry_required'
    first = claim(admin_actor, document, retry_after_attempt_id=old.pk)
    ops.fail_extraction(first.binding, code='fact_extraction_failed')
    with pytest.raises(ops.FactExtractionOperationError) as caught:
        claim(admin_actor, document, retry_after_attempt_id=old.pk)
    assert caught.value.code == 'fact_extraction_state_conflict'
    assert GroundingFactExtractionAttempt.objects.count() == 2


@pytest.mark.parametrize('updates', [
    {'is_active':False}, {'is_staff':False}, {'role':'sales','is_superuser':True},
    {'role':'presales','is_superuser':True},
])
def test_claim_reloads_actor_and_rejects_non_admin(admin_actor, ready_document, updates):
    ops = operations()
    type(admin_actor).objects.filter(pk=admin_actor.pk).update(**updates)
    with pytest.raises(ops.FactExtractionOperationError) as caught:
        claim(admin_actor, ready_document[0])
    assert caught.value.code == 'fact_extraction_permission_denied'
    assert not GroundingFactExtractionAttempt.objects.exists()


@pytest.mark.parametrize('updates', [
    {'status':'pending'}, {'last_index_run_id':None},
    {'indexing_run_id':uuid4(), 'processing_started_at':timezone.now()},
])
def test_claim_rejects_unready_or_reindexing_document(admin_actor, ready_document, updates):
    ops = operations()
    document, _ = ready_document
    type(document).objects.filter(pk=document.pk).update(**updates)
    with pytest.raises(ops.FactExtractionOperationError):
        claim(admin_actor, document)
    assert not GroundingFactExtractionAttempt.objects.exists()


def test_stale_confirmation_cannot_select_a_new_index(admin_actor, ready_document):
    ops = operations()
    document, _ = ready_document
    type(document).objects.filter(pk=document.pk).update(last_index_run_id=uuid4())
    with pytest.raises(ops.FactExtractionOperationError) as caught:
        claim(admin_actor, document)
    assert caught.value.code == 'fact_extraction_index_changed'


def test_claim_refuses_callers_outer_transaction(admin_actor, ready_document):
    ops = operations()
    with transaction.atomic(), pytest.raises(ops.FactExtractionOperationError) as caught:
        claim(admin_actor, ready_document[0])
    assert caught.value.code == 'fact_extraction_nested_transaction'


def test_cancel_is_idempotent_and_late_failure_does_not_override(admin_actor, ready_document):
    ops = operations()
    document, _ = ready_document
    first = claim(admin_actor, document)
    cancelled = ops.cancel_extraction(document.pk, actor_id=admin_actor.pk, attempt_id=first.attempt_id)
    replay = ops.cancel_extraction(document.pk, actor_id=admin_actor.pk, attempt_id=first.attempt_id)
    ops.fail_extraction(first.binding, code='fact_extraction_failed')
    cancelled.refresh_from_db()
    assert cancelled.status == replay.status == 'cancelled'
    assert cancelled.error_code == 'fact_extraction_cancelled'
    retry = claim(admin_actor, document, retry_after_attempt_id=cancelled.pk)
    assert retry.attempt_id != cancelled.pk


def test_cannot_cancel_other_document_or_success(admin_actor, ready_document, attempt_factory):
    ops = operations()
    done = attempt_factory(status='succeeded', finished_at=timezone.now())
    with pytest.raises(ops.FactExtractionOperationError):
        ops.cancel_extraction(done.document_id, actor_id=admin_actor.pk, attempt_id=done.pk)
    with pytest.raises(ops.FactExtractionOperationError):
        ops.cancel_extraction(done.document_id+999, actor_id=admin_actor.pk, attempt_id=done.pk)
    done.refresh_from_db()
    assert done.status == 'succeeded'
