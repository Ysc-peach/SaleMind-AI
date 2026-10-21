"""Database conflicts inside workflow generation fail closed instead of escaping as 500."""

import pytest

from apps.sales.models import SolutionDraftRecord
from apps.sales.tests.test_solution_review_workflow import (  # noqa: F401
    _compiled,
    _config,
    _initial,
    workflow_context,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("wrapped_psycopg_error", [False, True])
def test_database_conflict_during_workflow_generation_fails_closed(
    workflow_context,
    monkeypatch,
    wrapped_psycopg_error,
):
    from django.db import OperationalError

    from apps.sales.services import solution_review_workflow

    def reject(*args, **kwargs):
        error = OperationalError("deadlock detected")
        if wrapped_psycopg_error:
            # Django wraps driver errors and keeps the original as __cause__;
            # psycopg's own class is not a django.db exception subclass.
            from psycopg.errors import DeadlockDetected

            error.__cause__ = DeadlockDetected("deadlock detected")
        raise error

    monkeypatch.setattr(solution_review_workflow, "generate_and_persist_solution_draft", reject)
    result = _compiled().invoke(_initial(workflow_context), _config())

    assert result["workflow_outcome"] == "failed"
    assert result["error_code"] == "solution_generation_failed"
    assert SolutionDraftRecord.objects.count() == 0
