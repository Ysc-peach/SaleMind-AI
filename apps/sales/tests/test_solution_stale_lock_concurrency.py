"""The staleness read holds its source rows; a concurrent reindex must wait.

The approval path derives reasons after locking provenance sources in
document -> fact order. If that lock disappears, a reindex can commit between
the provenance read and the chunk read, and the false verdict is written into
the monotonic ``stale_reasons`` union. This test asserts the lock, not a timing
window, so it stays deterministic.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from django.db import (
    OperationalError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone

from apps.knowledge.models import KnowledgeDocument
from apps.sales.services.solution_review import approve_solution_draft
from apps.sales.tests.test_solution_persistence_service import (  # noqa: F401
    generated_artifact,
    persistence_context,
)
from apps.sales.tests.test_solution_stale_revalidation_atomicity import (
    _pending_case,
)


pytestmark = pytest.mark.django_db(transaction=True)


def worker(function):
    close_old_connections()
    try:
        return function()
    finally:
        connections.close_all()


def _update_document(document_id, *, timeout_ms):
    """Try to touch the document row from a separate connection.

    Returns ``blocked`` when another transaction holds the row lock past
    ``timeout_ms``, ``updated`` when the write went through.
    """

    def run():
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                KnowledgeDocument.objects.filter(pk=document_id).update(
                    updated_at=timezone.now(),
                )
            return "updated"
        except OperationalError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(worker, run).result(20)


def test_concurrent_document_update_waits_for_the_staleness_lock(
    monkeypatch, make_user, persistence_context, generated_artifact,
):
    case = _pending_case(monkeypatch, make_user, persistence_context, generated_artifact)
    from apps.sales.services import solution_persistence

    entered, release = Event(), Event()
    real_evaluate = solution_persistence.evaluate_solution_draft_stale_reasons

    def paused_evaluate(record):
        entered.set()
        assert release.wait(10), "approval was not released"
        return real_evaluate(record)

    monkeypatch.setattr(
        solution_persistence, "evaluate_solution_draft_stale_reasons", paused_evaluate,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            worker,
            lambda: approve_solution_draft(case.solution, actor=case.reviewer),
        )
        try:
            assert entered.wait(10), "approval never reached the staleness read"
            assert _update_document(case.document.pk, timeout_ms=300) == "blocked"
        finally:
            release.set()
        future.result(20)

    assert _update_document(case.document.pk, timeout_ms=3000) == "updated"
