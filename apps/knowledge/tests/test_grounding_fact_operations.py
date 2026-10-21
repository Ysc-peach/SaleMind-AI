"""The Admin use case distinguishes success-empty, retry, and provider failure."""
from importlib.util import find_spec

import pytest

from apps.knowledge.models import EnterpriseGroundingFact, GroundingFactExtractionAttempt
from apps.knowledge.services.grounding_fact_attempts import FactExtractionOperationError, cancel_extraction
from apps.llm.exceptions import LLMProviderError, LLMErrorCode
from .admin_grounding_fixtures import admin_actor, ready_document
from .test_grounding_fact_extraction import ExtractionFakeLLM, payload

pytestmark = pytest.mark.django_db(transaction=True)


def run(actor, document, **kwargs):
    assert find_spec('apps.knowledge.services.grounding_fact_operations'), 'Extraction use case missing'
    from apps.knowledge.services.grounding_fact_operations import run_document_fact_extraction
    return run_document_fact_extraction(document.pk, actor_id=actor.pk,
        expected_index_run_id=document.last_index_run_id, **kwargs)


@pytest.mark.parametrize('empty', [True, False])
def test_success_replay_does_not_construct_provider(admin_actor, ready_document, monkeypatch, empty):
    document, chunk = ready_document
    provider = ExtractionFakeLLM('{"facts":[]}' if empty else payload(chunk.pk))
    first = run(admin_actor, document, llm_provider=provider)
    def forbidden():
        raise AssertionError('Replays must not construct provider')
    monkeypatch.setattr('apps.knowledge.services.grounding_facts.get_llm_provider', forbidden)
    second = run(admin_actor, document)
    assert first.state == second.state == 'succeeded'
    assert first.proposed_count == second.proposed_count == (0 if empty else 1)
    assert len(provider.calls) == 1
    assert GroundingFactExtractionAttempt.objects.count() == 1


def test_failed_run_requires_new_explicit_confirmation(admin_actor, ready_document):
    document, chunk = ready_document
    provider = ExtractionFakeLLM('private invalid output')
    with pytest.raises(FactExtractionOperationError) as caught:
        run(admin_actor, document, llm_provider=provider)
    assert caught.value.code == 'grounding_fact_invalid_response'
    old = GroundingFactExtractionAttempt.objects.get()
    assert old.status == 'failed'
    assert 'private' not in old.error_code
    with pytest.raises(FactExtractionOperationError):
        run(admin_actor, document, llm_provider=provider)
    assert len(provider.calls) == 1
    provider.content = payload(chunk.pk)
    result = run(admin_actor, document, llm_provider=provider, retry_after_attempt_id=old.pk)
    assert result.state == 'succeeded'
    old.refresh_from_db()
    assert old.status == 'failed'
    assert GroundingFactExtractionAttempt.objects.count() == 2


@pytest.mark.parametrize('kind', ['provider', 'unexpected'])
def test_failure_is_safe_and_does_not_damage_index(admin_actor, ready_document, kind):
    document, _ = ready_document
    old_run = document.last_index_run_id
    class Broken:
        def generate(self, *args, **kwargs):
            if kind == 'provider':
                raise LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)
            raise RuntimeError('SECRET PATH private traceback')
    with pytest.raises(FactExtractionOperationError) as caught:
        run(admin_actor, document, llm_provider=Broken())
    assert caught.value.code == ('fact_extraction_provider_failed' if kind == 'provider' else 'fact_extraction_failed')
    assert 'SECRET' not in str(caught.value)
    assert not EnterpriseGroundingFact.objects.exists()
    attempt = GroundingFactExtractionAttempt.objects.get()
    assert attempt.status == 'failed'
    document.refresh_from_db()
    assert document.status == 'ready' and document.last_index_run_id == old_run
    assert document.chunks.count() == 1


def test_cancel_during_provider_keeps_cancelled_not_failed(admin_actor, ready_document):
    document, chunk = ready_document
    def cancel():
        attempt = GroundingFactExtractionAttempt.objects.get()
        cancel_extraction(document.pk, actor_id=admin_actor.pk, attempt_id=attempt.pk)
    with pytest.raises(FactExtractionOperationError) as caught:
        run(admin_actor, document, llm_provider=ExtractionFakeLLM(payload(chunk.pk), callback=cancel))
    assert caught.value.code == 'fact_extraction_cancelled'
    assert GroundingFactExtractionAttempt.objects.get().status == 'cancelled'
    assert not EnterpriseGroundingFact.objects.exists()
