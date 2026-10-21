"""Exercise Admin HTTP operations through human approval and deterministic admission."""
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument, EnterpriseGroundingFact, GroundingFactExtractionAttempt
from apps.knowledge.services.grounding_fact_attempts import claim_extraction
from apps.llm.base import LLMGeneration
from .admin_grounding_fixtures import admin_actor, admin_client, ready_document
from .test_admin_knowledge_documents import local_admin_environment, operation_url
from .test_grounding_fact_extraction import payload

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def fact_provider(monkeypatch):
    class Provider:
        def __init__(self):
            self.calls = []
            self.output = None
            self.callback = None
        def generate(self, messages, **kwargs):
            self.calls.append(tuple(messages))
            if self.callback:
                self.callback()
            content = self.output if self.output is not None else payload(KnowledgeChunk.objects.latest('pk').pk)
            return LLMGeneration(content=content)
    provider = Provider()
    monkeypatch.setattr('apps.knowledge.services.grounding_facts.get_llm_provider', lambda:provider)
    return provider


def extract_data(document, **kwargs):
    return {'expected_index_run_id':str(document.last_index_run_id), **kwargs}


def test_extract_get_is_confirmation_only_and_replay_does_not_call_again(admin_client, ready_document, fact_provider):
    document, _ = ready_document
    url = operation_url('extract', document.pk)
    response = admin_client.get(url)
    assert response.status_code == 200
    assert '费用' in response.content.decode() and '人工' in response.content.decode()
    assert not GroundingFactExtractionAttempt.objects.exists() and not fact_provider.calls
    for _ in range(2):
        response = admin_client.post(url, extract_data(document), follow=True)
        assert response.status_code == 200
    assert len(fact_provider.calls) == 1
    fact = EnterpriseGroundingFact.objects.get()
    assert fact.approval_status == 'proposed'
    assert fact.approved_by_id is None and fact.approved_at is None


def test_extract_successful_empty_result_is_not_unknown_or_retried(admin_client, ready_document, fact_provider):
    fact_provider.output = '{"facts":[]}'
    document, _ = ready_document
    url = operation_url('extract', document.pk)
    admin_client.post(url, extract_data(document))
    response = admin_client.post(url, extract_data(document), follow=True)
    assert response.status_code == 200
    assert '无候选' in response.content.decode()
    assert len(fact_provider.calls) == 1
    assert GroundingFactExtractionAttempt.objects.get().status == 'succeeded'


def test_failed_retry_is_confirmed_and_old_post_cannot_create_a_third_attempt(admin_client, ready_document, fact_provider):
    fact_provider.output = 'SECRET invalid provider output'
    document, _ = ready_document
    url = operation_url('extract', document.pk)
    first = admin_client.post(url, extract_data(document))
    assert first.status_code == 200 and b'SECRET' not in first.content
    old = GroundingFactExtractionAttempt.objects.get()
    admin_client.post(url, extract_data(document))
    assert len(fact_provider.calls) == 1
    confirmation = admin_client.get(url)
    assert str(old.pk) in confirmation.content.decode()
    for _ in range(2):
        admin_client.post(url, extract_data(document, retry_after_attempt_id=old.pk))
    assert len(fact_provider.calls) == 2
    assert GroundingFactExtractionAttempt.objects.count() == 2
    assert not EnterpriseGroundingFact.objects.exists()


def test_extract_stale_version_and_csrf_are_rejected_before_calls(admin_client, admin_actor, ready_document, fact_provider):
    document, _ = ready_document
    url = operation_url('extract', document.pk)
    response = admin_client.post(url, {'expected_index_run_id':str(uuid4())})
    assert response.status_code == 200
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_actor)
    assert client.post(url, extract_data(document)).status_code == 403
    assert not fact_provider.calls and not GroundingFactExtractionAttempt.objects.exists()


@pytest.mark.parametrize('role', ['sales', 'presales'])
def test_technical_superuser_cannot_extract_or_cancel(admin_client, admin_actor, ready_document, fact_provider, role):
    document, _ = ready_document
    first = claim_extraction(document.pk, actor_id=admin_actor.pk, expected_index_run_id=document.last_index_run_id)
    type(admin_actor).objects.filter(pk=admin_actor.pk).update(role=role, is_superuser=True)
    for name,args,data in [
        ('extract',(document.pk,),extract_data(document)),
        ('cancel_extraction',(document.pk,first.attempt_id),{'confirm':'on'}),
    ]:
        url = operation_url(name,*args)
        assert admin_client.get(url).status_code == 403
        assert admin_client.post(url,data).status_code == 403
    assert not fact_provider.calls
    assert GroundingFactExtractionAttempt.objects.get().status == 'running'


def test_cancel_get_does_not_cancel_and_explicit_post_does(admin_client, admin_actor, ready_document, fact_provider):
    document, _ = ready_document
    first = claim_extraction(document.pk, actor_id=admin_actor.pk, expected_index_run_id=document.last_index_run_id)
    url = operation_url('cancel_extraction',document.pk,first.attempt_id)
    assert admin_client.get(url).status_code == 200
    assert GroundingFactExtractionAttempt.objects.get().status == 'running'
    admin_client.post(url,{})
    assert GroundingFactExtractionAttempt.objects.get().status == 'running'
    response = admin_client.post(url,{'confirm':'on'},follow=True)
    assert response.status_code == 200
    assert GroundingFactExtractionAttempt.objects.get().status == 'cancelled'
    assert not fact_provider.calls


def test_actor_revoked_during_model_call_cannot_publish(admin_client, admin_actor, ready_document, fact_provider):
    document, _ = ready_document
    fact_provider.callback = lambda:type(admin_actor).objects.filter(pk=admin_actor.pk).update(role='sales')
    response = admin_client.post(operation_url('extract',document.pk), extract_data(document))
    assert response.status_code == 403
    assert not EnterpriseGroundingFact.objects.exists()
    assert GroundingFactExtractionAttempt.objects.get().status == 'failed'


@pytest.mark.parametrize('action', ['approve_selected_facts', 'reject_selected_facts'])
def test_admin_upload_to_human_approval_admission(admin_client, admin_actor, fact_provider, action):
    from apps.sales.services.solution_admission import build_solution_admission
    from apps.sales.services.solution_retrieval import SolutionSource
    from apps.sales.tests.solution_fakes import typed_analysis
    response = admin_client.post(operation_url('upload'), {
        'title':'真实上传流程资料', 'document_type':'technical',
        'source_file':SimpleUploadedFile('capability.md','SalesMind 明确支持企业私有化部署。'.encode()),
    },follow=True)
    assert response.status_code == 200
    document = KnowledgeDocument.objects.get()
    response = admin_client.post(operation_url('extract',document.pk), extract_data(document), follow=True)
    assert response.status_code == 200
    fact = EnterpriseGroundingFact.objects.get()
    chunk = document.chunks.get()
    source = SolutionSource(chunk_id=chunk.pk, document_id=document.pk,
        document_title=document.title, document_type=document.document_type,
        original_filename=document.original_filename, content=chunk.content,
        page_number=chunk.page_number, section_title=chunk.section_title,
        source_reference=chunk.source_reference, similarity=0.99,label='S1')
    assert build_solution_admission(typed_analysis(),(source,)).allowed_proposal_source_labels == ()
    url = reverse('admin:knowledge_enterprisegroundingfact_changelist')
    response = admin_client.post(url, {'action':action,'_selected_action':[str(fact.pk)]},follow=True)
    assert response.status_code == 200
    fact.refresh_from_db()
    approved = action == 'approve_selected_facts'
    assert fact.approval_status == ('approved' if approved else 'rejected')
    assert build_solution_admission(typed_analysis(),(source,)).allowed_proposal_source_labels == (('S1',) if approved else ())
    if approved:
        assert fact.approved_by_id == admin_actor.pk
    old_run = document.last_index_run_id
    response = admin_client.post(operation_url('reindex',document.pk),
        {'expected_index_run_id':str(old_run)},follow=True)
    assert response.status_code == 200
    document.refresh_from_db()
    fact.refresh_from_db()
    assert document.last_index_run_id != old_run and fact.is_stale
    assert build_solution_admission(typed_analysis(),(source,)).allowed_proposal_source_labels == ()
    admin_client.post(operation_url('extract',document.pk),extract_data(document))
    fresh = EnterpriseGroundingFact.objects.exclude(pk=fact.pk).get()
    assert fresh.approval_status == 'proposed' and fresh.approved_by_id is None
