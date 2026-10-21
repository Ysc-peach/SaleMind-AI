"""Generation-side row locks must match the reindex order: documents, then facts."""

from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
from apps.sales.services.solution_admission import (
    EnterpriseClaimProvenance,
    GroundingAdmission,
)
from apps.sales.services.solution_persistence import _lock_admission_rows


pytestmark = pytest.mark.django_db


def _document(owner, sequence):
    return KnowledgeDocument.objects.create(
        title=f"Lock order source {sequence}",
        document_type="technical",
        source_file=f"knowledge/documents/lock-{sequence}.md",
        original_filename=f"lock-{sequence}.md",
        mime_type="text/markdown",
        file_size=32,
        checksum_sha256=f"{sequence}" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=uuid4(),
        created_by=owner,
    )


def _fact(document, sequence):
    excerpt = "系统支持私有化部署。"
    return EnterpriseGroundingFact.objects.create(
        subject_key="private_deployment",
        statement=f"{excerpt}{sequence}",
        status="confirmed_supported",
        source_document=document,
        source_chunk_id=900 + sequence,
        source_excerpt=excerpt,
        source_index_run_id=document.last_index_run_id,
        source_content_hash="b" * 64,
        approval_status="approved",
        approved_by=document.created_by,
        approved_at=timezone.now(),
    )


def test_admission_locks_documents_before_facts_and_in_stable_order(make_user):
    owner = make_user()
    first = _document(owner, 1)
    second = _document(owner, 2)
    # Inserted high document id first so an unordered lock set is observable.
    newer_fact = _fact(second, 1)
    older_fact = _fact(first, 2)
    admission = GroundingAdmission(
        claims=(),
        enterprise_decisions=(),
        enterprise_provenance=(
            EnterpriseClaimProvenance(claim=None, subject_key="private_deployment",
                                       fact_id=newer_fact.pk),
            EnterpriseClaimProvenance(claim=None, subject_key="private_deployment",
                                       fact_id=older_fact.pk),
        ),
        allowed_proposal_source_labels=(),
    )

    document_table = KnowledgeDocument._meta.db_table
    fact_table = EnterpriseGroundingFact._meta.db_table
    with CaptureQueriesContext(connection) as captured:
        with transaction.atomic():
            _lock_admission_rows(admission)

    locking = [
        query["sql"] for query in captured.captured_queries if "FOR UPDATE" in query["sql"].upper()
    ]
    document_locks = [index for index, sql in enumerate(locking) if f'FROM "{document_table}"' in sql]
    fact_locks = [index for index, sql in enumerate(locking) if f'FROM "{fact_table}"' in sql]

    assert document_locks and fact_locks
    assert max(document_locks) < min(fact_locks)
    assert all("ORDER BY" in sql.upper() for sql in locking)
