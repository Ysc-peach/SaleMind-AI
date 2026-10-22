"""Admin document UI must not create a new write/permission bypass."""
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.knowledge.models import KnowledgeDocument, GroundingFactExtractionAttempt
from .admin_grounding_fixtures import admin_actor, admin_client, ready_document, attempt_factory
from .embedding_fakes import DeterministicEmbeddingProvider
from .parser_fixtures import build_pdf

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def local_admin_environment(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = tmp_path
    observed = []
    class Embeddings(DeterministicEmbeddingProvider):
        def embed_documents(self, texts):
            observed.append(connection.in_atomic_block)
            return super().embed_documents(texts)
    monkeypatch.setattr('apps.knowledge.services.indexing.get_embedding_provider', Embeddings)
    return observed


def operation_url(name, *args):
    model_admin = admin.site._registry[KnowledgeDocument]
    route = 'knowledge_knowledgedocument_' + name
    assert any(item.name == route for item in model_admin.get_urls()), 'Admin operation route missing'
    return reverse('admin:' + route, args=args)


def document_url(document=None):
    assert KnowledgeDocument in admin.site._registry, 'Knowledge document Admin missing'
    return reverse('admin:knowledge_knowledgedocument_change', args=[document.pk]) if document else reverse('admin:knowledge_knowledgedocument_changelist')


def test_admin_can_view_but_cannot_edit_document(admin_client, ready_document):
    document, _ = ready_document
    response = admin_client.get(document_url(document))
    assert response.status_code == 200
    assert 'Private deployment' in response.content.decode()
    assert 'knowledge/documents/private.md' not in response.content.decode()
    response = admin_client.post(document_url(document), {'title':'Forged', 'status':'failed'})
    assert response.status_code == 403
    document.refresh_from_db()
    assert document.title == 'Private deployment' and document.status == 'ready'


@pytest.mark.parametrize('updates', [
    {'is_active':False}, {'is_staff':False},
    {'role':'sales', 'is_superuser':True}, {'role':'presales', 'is_superuser':True},
])
def test_admin_document_visibility_obeys_business_role(admin_client, admin_actor, ready_document, updates):
    type(admin_actor).objects.filter(pk=admin_actor.pk).update(**updates)
    response = admin_client.get(document_url())
    assert response.status_code in (302, 403)
    assert 'Private deployment' not in response.content.decode()


@pytest.mark.parametrize('status,count,expected', [
    ('running',0,'抽取中'), ('failed',0,'抽取失败'), ('cancelled',0,'已取消'),
    ('succeeded',0,'无候选'), ('succeeded',1,'抽取成功'),
])
def test_admin_displays_distinct_extraction_states(admin_client, attempt_factory, status, count, expected):
    attempt_factory(status=status, proposed_count=count,
                    finished_at=None if status=='running' else timezone.now(),
                    error_code='fact_extraction_failed' if status in ['failed','cancelled'] else '')
    response = admin_client.get(document_url())
    assert response.status_code == 200
    assert expected in response.content.decode()


def test_old_run_success_does_not_masquerade_as_current(admin_client, attempt_factory):
    attempt_factory(index_run_id=uuid4(), status='succeeded', finished_at=timezone.now())
    response = admin_client.get(document_url())
    assert '索引就绪，尚未抽取' in response.content.decode()


def test_document_titles_are_escaped_and_native_mutations_closed(admin_client, ready_document):
    document, _ = ready_document
    document.title = '<script>alert("private")</script>'
    document.save(update_fields=['title'])
    response = admin_client.get(document_url())
    assert b'<script>alert(' not in response.content
    assert '&lt;script&gt;' in response.content.decode()
    model_admin = admin.site._registry[KnowledgeDocument]
    class Request:
        user = document.created_by
    assert model_admin.has_add_permission(Request()) is False
    assert model_admin.has_delete_permission(Request(), document) is False
    assert not model_admin.get_actions(Request())


@pytest.mark.parametrize('name,data', [
    ('guide.txt', b'Private deployment is supported.'),
    ('guide.md', b'# Deployment\n\nPrivate deployment is supported.'),
    ('guide.pdf', build_pdf(['Private deployment is supported.'])),
])
def test_admin_upload_validates_and_indexes_real_file(admin_client, admin_actor, local_admin_environment, name, data):
    url = operation_url('upload')
    response = admin_client.get(url)
    assert response.status_code == 200
    assert not KnowledgeDocument.objects.exists()
    assert not local_admin_environment
    response = admin_client.post(url, {'title':'Uploaded capability', 'document_type':'technical',
        'source_file':SimpleUploadedFile(name, data)}, follow=True)
    assert response.status_code == 200
    document = KnowledgeDocument.objects.get()
    assert document.status == 'ready' and document.created_by_id == admin_actor.pk
    assert document.last_index_run_id is not None and document.chunks.exists()
    assert local_admin_environment == [False]
    assert not GroundingFactExtractionAttempt.objects.exists()


@pytest.mark.parametrize('name,data', [
    ('fake.pdf', b'not a PDF'), ('guide.docx', b'not supported'),
    ('encrypted.pdf', build_pdf(['secret'], password='private')),
    ('binary.txt', b'\x00\xff'),
])
def test_admin_upload_rejects_invalid_document_without_provider(admin_client, local_admin_environment, name, data):
    response = admin_client.post(operation_url('upload'), {'title':'Invalid', 'document_type':'technical',
        'source_file':SimpleUploadedFile(name, data)})
    assert response.status_code == 200
    assert not KnowledgeDocument.objects.exists()
    assert not local_admin_environment


def test_upload_rejects_metadata_forgery(admin_client, local_admin_environment):
    response = admin_client.post(operation_url('upload'), {
        'title':'Forged', 'document_type':'technical', 'status':'ready', 'created_by':'999',
        'source_file':SimpleUploadedFile('guide.md', b'private deployment'),
    })
    assert response.status_code == 200
    assert not KnowledgeDocument.objects.exists()
    assert not local_admin_environment


def test_blank_pdf_keeps_failed_index_record_without_embedding(admin_client, local_admin_environment):
    response = admin_client.post(operation_url('upload'), {'title':'Blank PDF', 'document_type':'technical',
        'source_file':SimpleUploadedFile('blank.pdf', build_pdf([None]))}, follow=True)
    assert response.status_code == 200
    assert KnowledgeDocument.objects.get().status == 'failed'
    assert not local_admin_environment


def test_upload_csrf_and_business_authorization_are_enforced(admin_actor, ready_document, local_admin_environment):
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_actor)
    url = operation_url('upload')
    assert client.post(url, {}).status_code == 403
    type(admin_actor).objects.filter(pk=admin_actor.pk).update(role='sales', is_superuser=True)
    client = Client()
    client.force_login(admin_actor)
    assert client.get(url).status_code == 403
    assert client.post(url, {}).status_code == 403
    assert KnowledgeDocument.objects.count() == 1
    assert not local_admin_environment


def test_indexing_failure_keeps_failed_document_and_safe_message(admin_client, monkeypatch):
    class Broken(DeterministicEmbeddingProvider):
        def embed_documents(self, texts):
            raise RuntimeError('SECRET server traceback')
    monkeypatch.setattr('apps.knowledge.services.indexing.get_embedding_provider', Broken)
    response = admin_client.post(operation_url('upload'), {'title':'Failed indexing', 'document_type':'technical',
        'source_file':SimpleUploadedFile('guide.md', b'private deployment')}, follow=True)
    assert response.status_code == 200
    assert KnowledgeDocument.objects.get().status == 'failed'
    assert b'SECRET' not in response.content


def test_storage_failure_does_not_echo_private_error(admin_client, monkeypatch):
    storage = KnowledgeDocument._meta.get_field('source_file').storage
    def fail(*args, **kwargs):
        raise OSError('SECRET private path')
    monkeypatch.setattr(storage, 'save', fail)
    response = admin_client.post(operation_url('upload'), {'title':'Broken storage', 'document_type':'technical',
        'source_file':SimpleUploadedFile('guide.md', b'private deployment')})
    assert response.status_code == 200
    assert b'SECRET' not in response.content
    assert not KnowledgeDocument.objects.exists()


def _stalled_document(admin_actor, *, minutes_ago=120, last_run=None):
    return KnowledgeDocument.objects.create(
        title='Stalled indexing', document_type='technical',
        source_file='knowledge/documents/stalled.md', original_filename='stalled.md',
        mime_type='text/markdown', file_size=32, checksum_sha256='d'*64,
        status='processing', indexing_run_id=uuid4(), last_index_run_id=last_run,
        last_indexed_at=timezone.now() if last_run else None,
        processing_started_at=timezone.now() - timedelta(minutes=minutes_ago),
        created_by=admin_actor,
    )


def test_reset_stalled_indexing_requires_an_explicit_confirmation(admin_client, admin_actor):
    document = _stalled_document(admin_actor, last_run=uuid4())
    url = operation_url('reset_stalled_indexing', document.pk)
    response = admin_client.get(url)
    assert response.status_code == 200
    assert '不会补跑索引' in response.content.decode()
    response = admin_client.post(url, {})
    assert response.status_code == 200
    document.refresh_from_db()
    assert document.status == 'processing'


def test_reset_stalled_indexing_keeps_the_run_id_and_does_not_reindex(admin_client, admin_actor):
    run_id = uuid4()
    document = _stalled_document(admin_actor, last_run=run_id)
    interrupted = document.indexing_run_id
    response = admin_client.post(
        operation_url('reset_stalled_indexing', document.pk), {'confirm':'on'}, follow=True)
    assert response.status_code == 200
    document.refresh_from_db()
    assert document.status == 'ready' and document.error_code == 'indexing_stalled_reset'
    assert document.indexing_run_id == interrupted and document.last_index_run_id == run_id
    assert not document.chunks.exists()
    assert '未补跑索引' in response.content.decode()


def test_reset_stalled_indexing_refuses_a_run_inside_the_window(admin_client, admin_actor):
    document = _stalled_document(admin_actor, minutes_ago=1, last_run=uuid4())
    response = admin_client.post(
        operation_url('reset_stalled_indexing', document.pk), {'confirm':'on'})
    assert response.status_code == 200
    assert '未超时不予重置' in response.content.decode()
    document.refresh_from_db()
    assert document.status == 'processing'


def test_reindex_confirmation_cannot_silently_use_a_new_run(admin_client, ready_document, local_admin_environment):
    document, _ = ready_document
    url = operation_url('reindex', document.pk)
    assert admin_client.get(url).status_code == 200
    old = document.last_index_run_id
    type(document).objects.filter(pk=document.pk).update(last_index_run_id=uuid4())
    response = admin_client.post(url, {'expected_index_run_id':str(old)})
    assert response.status_code == 200
    assert not local_admin_environment
    assert document.chunks.count() == 1


def test_reindex_service_checks_confirmation_under_lock(ready_document):
    from apps.knowledge.services.indexing import reindex_document
    from apps.knowledge.exceptions import KnowledgeDocumentError
    document, _ = ready_document
    with pytest.raises(KnowledgeDocumentError) as caught:
        reindex_document(document.pk, expected_index_run_id=uuid4())
    assert caught.value.code == 'indexing_run_conflict'


def test_admin_only_displays_whitelisted_failure_information(admin_client, ready_document, attempt_factory):
    document, _ = ready_document
    document.status = 'failed'
    document.error_code = 'indexing_failed'
    document.error_message = 'SECRET path and traceback'
    document.save(update_fields=['status','error_code','error_message'])
    attempt_factory(status='failed',finished_at=timezone.now(),error_code='SECRET-UNTRUSTED')
    response = admin_client.get(document_url(document))
    assert response.status_code == 200
    assert b'SECRET' not in response.content
    assert b'indexing_failed' in response.content


@pytest.mark.parametrize('updates', [{'is_active':False}, {'role':'sales'}])
def test_actor_revoked_during_upload_receives_no_document_data(admin_client,admin_actor,monkeypatch,updates):
    class RevokingEmbedding(DeterministicEmbeddingProvider):
        def embed_documents(self,texts):
            type(admin_actor).objects.filter(pk=admin_actor.pk).update(**updates)
            return super().embed_documents(texts)
    monkeypatch.setattr('apps.knowledge.services.indexing.get_embedding_provider',RevokingEmbedding)
    response = admin_client.post(operation_url('upload'),{
        'title':'Private uploaded capability','document_type':'technical',
        'source_file':SimpleUploadedFile('capability.md',b'private deployment'),
    })
    assert response.status_code == 403
    assert b'Private uploaded capability' not in response.content
    assert KnowledgeDocument.objects.get().status == 'ready'
