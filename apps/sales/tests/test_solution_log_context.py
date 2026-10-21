"""Request identifiers are typed and isolated, never raw model content."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from uuid import UUID, uuid4
import pytest


def test_nested_and_exceptional_scope_restores_context():
    from apps.sales.services.solution_log_context import solution_log_scope, current_solution_workflow_id
    first, second = uuid4(), uuid4()
    assert current_solution_workflow_id() is None
    with solution_log_scope(first):
        assert current_solution_workflow_id() == str(first)
        with pytest.raises(RuntimeError):
            with solution_log_scope(second):
                assert current_solution_workflow_id() == str(second)
                raise RuntimeError("scope cleanup")
        assert current_solution_workflow_id() == str(first)
    assert current_solution_workflow_id() is None


def test_parallel_contexts_never_share_a_workflow_identifier():
    from apps.sales.services.solution_log_context import solution_log_scope, current_solution_workflow_id
    ids = [uuid4() for _ in range(6)]
    def observe(identifier):
        with solution_log_scope(identifier):
            context = copy_context()
            return context.run(current_solution_workflow_id)
    with ThreadPoolExecutor(3) as executor:
        assert list(executor.map(observe, ids)) == list(map(str, ids))
    assert current_solution_workflow_id() is None


@pytest.mark.parametrize("value", ["raw customer text", str(uuid4()), None, 3])
def test_raw_strings_cannot_be_log_identifiers(value):
    from apps.sales.services.solution_log_context import solution_log_scope
    with pytest.raises(TypeError):
        with solution_log_scope(value):
            pytest.fail("invalid log identifier admitted")


def test_formal_grounding_logs_uuid_but_no_text_or_container_key(caplog):
    from apps.sales.services.solution_log_context import solution_log_scope
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError
    from apps.sales.tests.test_solution_unresolved_policy_integration import proposals_for
    from apps.sales.tests.test_solution_unresolved_policy import TARGETS
    from apps.sales.tests.test_solution_clarification_action_guard import partial_analysis
    from apps.sales.tests.test_solution_proposal_admissibility_v2 import _verify, _AdmissibilityVerifier
    identifier = uuid4()
    with solution_log_scope(identifier), pytest.raises(SolutionDraftGroundingError):
        _verify(proposals_for(TARGETS[3][0], "核验完成后开展建设"), _AdmissibilityVerifier(), analysis=partial_analysis())
    assert str(identifier) in caplog.text
    assert "核验完成后开展建设" not in caplog.text
    assert "application_boundary" not in caplog.text
