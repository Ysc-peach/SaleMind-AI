"""Managed extraction cannot publish after cancellation, revocation or index change."""
from dataclasses import replace
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.knowledge.models import EnterpriseGroundingFact, GroundingFactExtractionAttempt
from apps.knowledge.services import grounding_fact_attempts as attempts
from apps.knowledge.services.grounding_facts import extract_grounding_facts, GroundingFactExtractionError
from .admin_grounding_fixtures import admin_actor, ready_document
from .test_grounding_fact_extraction import ExtractionFakeLLM, payload

pytestmark = pytest.mark.django_db(transaction=True)


def binding(actor, document):
    return attempts.claim_extraction(document.pk, actor_id=actor.pk,
        expected_index_run_id=document.last_index_run_id).binding


def test_managed_completion_commits_candidates_and_success_together(admin_actor, ready_document):
    document, chunk = ready_document
    bound = binding(admin_actor, document)
    observed = []
    provider = ExtractionFakeLLM(payload(chunk.pk),
        callback=lambda: observed.append(connection.in_atomic_block))
    facts = extract_grounding_facts(document.pk, llm_provider=provider, managed_attempt=bound)
    run = GroundingFactExtractionAttempt.objects.get(pk=bound.attempt_id)
    assert observed == [False]
    assert run.status == 'succeeded' and run.proposed_count == 1
    assert len(facts) == 1 and facts[0].approval_status == 'proposed'
    assert facts[0].approved_by_id is None and facts[0].approved_at is None


def test_success_write_failure_rolls_back_candidates(admin_actor, ready_document, monkeypatch):
    document, chunk = ready_document
    bound = binding(admin_actor, document)
    def fail(*args, **kwargs):
        raise RuntimeError('private transaction failure')
    monkeypatch.setattr(attempts, 'mark_succeeded_locked', fail)
    with pytest.raises(RuntimeError):
        extract_grounding_facts(document.pk, llm_provider=ExtractionFakeLLM(payload(chunk.pk)),
                               managed_attempt=bound)
    assert not EnterpriseGroundingFact.objects.exists()
    assert GroundingFactExtractionAttempt.objects.get(pk=bound.attempt_id).status == 'running'


@pytest.mark.parametrize('change', ['cancel', 'deactivate', 'role', 'index', 'reindex', 'content'])
def test_late_result_cannot_publish_after_binding_or_source_change(admin_actor, ready_document, change):
    document, chunk = ready_document
    bound = binding(admin_actor, document)
    def alter():
        if change == 'cancel':
            attempts.cancel_extraction(document.pk, actor_id=admin_actor.pk, attempt_id=bound.attempt_id)
        elif change == 'deactivate':
            type(admin_actor).objects.filter(pk=admin_actor.pk).update(is_active=False)
        elif change == 'role':
            type(admin_actor).objects.filter(pk=admin_actor.pk).update(role='sales')
        elif change == 'index':
            type(document).objects.filter(pk=document.pk).update(last_index_run_id=uuid4())
        elif change == 'reindex':
            type(document).objects.filter(pk=document.pk).update(
                indexing_run_id=uuid4(), processing_started_at=timezone.now())
        else:
            type(chunk).objects.filter(pk=chunk.pk).update(content='Changed source')
    provider = ExtractionFakeLLM(payload(chunk.pk), callback=alter)
    with pytest.raises((attempts.FactExtractionOperationError, GroundingFactExtractionError)):
        extract_grounding_facts(document.pk, llm_provider=provider, managed_attempt=bound)
    assert not EnterpriseGroundingFact.objects.exists()
    run = GroundingFactExtractionAttempt.objects.get(pk=bound.attempt_id)
    assert run.status == ('cancelled' if change == 'cancel' else 'running')


def test_mismatched_binding_is_rejected_before_provider(admin_actor, ready_document):
    document, chunk = ready_document
    bound = binding(admin_actor, document)
    provider = ExtractionFakeLLM(payload(chunk.pk))
    with pytest.raises(attempts.FactExtractionOperationError):
        extract_grounding_facts(document.pk, llm_provider=provider,
                               managed_attempt=replace(bound, document_id=document.pk+1))
    assert not provider.calls
    assert not EnterpriseGroundingFact.objects.exists()


def test_managed_call_refuses_outer_transaction(admin_actor, ready_document):
    document, chunk = ready_document
    bound = binding(admin_actor, document)
    provider = ExtractionFakeLLM(payload(chunk.pk))
    with transaction.atomic(), pytest.raises(attempts.FactExtractionOperationError) as caught:
        extract_grounding_facts(document.pk, llm_provider=provider, managed_attempt=bound)
    assert caught.value.code == 'fact_extraction_nested_transaction'
    assert not provider.calls
