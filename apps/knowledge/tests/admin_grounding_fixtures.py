"""Local fixtures for Admin ingestion; never use real providers or storage."""
from uuid import uuid4
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument


@pytest.fixture
def admin_actor(django_user_model):
    return django_user_model.objects.create_user(
        username='knowledge-admin', email='knowledge-admin@example.com',
        password=None, role='admin', is_staff=True,
    )


@pytest.fixture
def admin_client(client, admin_actor):
    client.force_login(admin_actor)
    return client


@pytest.fixture
def ready_document(admin_actor):
    document = KnowledgeDocument.objects.create(
        title='Private deployment', document_type='technical',
        source_file='knowledge/documents/private.md', original_filename='private.md',
        mime_type='text/markdown', file_size=128, checksum_sha256='b'*64,
        status='ready', chunk_count=1, embedding_provider='fake',
        embedding_model='fake-model', embedding_dimensions=1024,
        last_indexed_at=timezone.now(), last_index_run_id=uuid4(), created_by=admin_actor,
    )
    chunk = KnowledgeChunk.objects.create(
        document=document, chunk_index=0, content='SalesMind 明确支持企业私有化部署。',
        embedding=[0.0]*1024, source_reference='Private deployment', char_count=24,
    )
    return document, chunk


@pytest.fixture
def attempt_factory(admin_actor, ready_document):
    def create(**overrides):
        from apps.knowledge import models
        model = getattr(models, 'GroundingFactExtractionAttempt', None)
        assert model is not None, 'Persisted extraction attempts are missing'
        document, _ = ready_document
        return model.objects.create(**{
            'document': document, 'requested_by': admin_actor,
            'index_run_id': document.last_index_run_id,
            'started_at': timezone.now()-timedelta(minutes=1), **overrides,
        })
    return create
