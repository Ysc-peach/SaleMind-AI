"""Database constraints must protect attempts independently of Admin buttons."""
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from .admin_grounding_fixtures import admin_actor, ready_document, attempt_factory

pytestmark = pytest.mark.django_db


def test_attempt_starts_running_with_no_outcome(attempt_factory):
    attempt = attempt_factory()
    assert attempt.status == 'running'
    assert attempt.finished_at is None
    assert attempt.proposed_count == 0
    assert attempt.error_code == ''
    assert attempt.token


@pytest.mark.parametrize('status', ['running', 'succeeded'])
def test_running_and_success_share_one_slot(attempt_factory, status):
    attempt_factory()
    values = {} if status == 'running' else {'finished_at': timezone.now()}
    with pytest.raises(IntegrityError), transaction.atomic():
        attempt_factory(status=status, **values)


@pytest.mark.parametrize('status', ['failed', 'cancelled'])
def test_terminal_failure_does_not_hold_slot(attempt_factory, status):
    first = attempt_factory(status=status, finished_at=timezone.now(),
                            error_code='fact_extraction_failed')
    second = attempt_factory()
    assert second.pk != first.pk


@pytest.mark.parametrize('overrides', [
    {'status': 'invented'}, {'proposed_count': -1},
    {'status': 'running', 'finished_at': timezone.now()},
    {'status': 'running', 'error_code': 'failure'},
    {'status': 'running', 'proposed_count': 1},
    {'status': 'succeeded'},
    {'status': 'succeeded', 'finished_at': timezone.now(), 'error_code': 'failure'},
    {'status': 'failed', 'finished_at': timezone.now()},
    {'status': 'failed', 'finished_at': timezone.now(), 'error_code': 'failure', 'proposed_count': 1},
    {'status': 'cancelled', 'error_code': 'cancelled'},
    {'status': 'succeeded', 'finished_at': timezone.now()-timedelta(days=1)},
])
def test_invalid_attempt_metadata_is_rejected_by_database(attempt_factory, overrides):
    with pytest.raises(IntegrityError), transaction.atomic():
        attempt_factory(**overrides)


def test_token_cannot_be_reused_on_another_index(attempt_factory):
    first = attempt_factory()
    with pytest.raises(IntegrityError), transaction.atomic():
        attempt_factory(index_run_id=uuid4(), token=first.token)


def test_audit_relations_are_protected(attempt_factory):
    attempt = attempt_factory()
    with pytest.raises(ProtectedError):
        attempt.document.delete()
    with pytest.raises(ProtectedError):
        attempt.requested_by.delete()
