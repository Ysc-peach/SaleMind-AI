"""Deterministic readiness priority and structured retrieval planning."""

from dataclasses import FrozenInstanceError

import pytest

from apps.sales.tests.solution_fakes import typed_analysis


@pytest.mark.parametrize("field", [
    "deployment_requirement", "data_security_requirement", "existing_environment",
    "integration_requirement", "technical_constraints",
])
def test_technical_conflict_requires_presales(field):
    from apps.sales.services.solution_readiness import check_solution_readiness

    result = check_solution_readiness(typed_analysis(**{field: "conflict"}))
    assert result.status == "needs_presales_involvement"
    assert result.blocking_fields == (field,)
    assert result.gap_fields == ()
    assert result.reasons and "冲突" in result.reasons[0]


@pytest.mark.parametrize("field", ["budget", "timeline", "business_goal", "use_scenario", "user_scale"])
def test_nontechnical_conflict_requires_sales(field):
    from apps.sales.services.solution_readiness import check_solution_readiness

    result = check_solution_readiness(typed_analysis(**{field: "conflict"}))
    assert result.status == "needs_sales_clarification"
    assert result.blocking_fields == (field,)


@pytest.mark.parametrize("goal,scenario", [("unknown", "unknown"), ("unknown", "unclear"), ("unclear", "unknown")])
def test_insufficient_business_understanding_blocks(goal, scenario):
    from apps.sales.services.solution_readiness import check_solution_readiness

    result = check_solution_readiness(typed_analysis(business_goal=goal, use_scenario=scenario))
    assert result.status == "needs_sales_clarification"
    assert result.blocking_fields == ("business_goal", "use_scenario")


@pytest.mark.parametrize("field", ["business_goal", "use_scenario", "user_scale", "deployment_requirement",
                                  "data_security_requirement", "existing_environment", "integration_requirement", "technical_constraints"])
@pytest.mark.parametrize("status", ["unknown", "unclear"])
def test_nonblocking_technical_or_business_gap(field, status):
    from apps.sales.services.solution_readiness import check_solution_readiness

    result = check_solution_readiness(typed_analysis(**{field: status}))
    assert result.status == "ready_with_gaps"
    assert result.gap_fields == (field,)
    assert result.blocking_fields == ()
    assert len(result.reasons) == 1


@pytest.mark.parametrize("statuses", [{}, {"budget": "unknown"}, {"timeline": "unknown"},
                                     {"budget": "unclear", "timeline": "unclear"}])
def test_only_commercial_uncertainties_do_not_lower_technical_readiness(statuses):
    from apps.sales.services.solution_readiness import check_solution_readiness

    result = check_solution_readiness(typed_analysis(**statuses))
    assert result.status == "ready"
    assert result.blocking_fields == result.gap_fields == result.reasons == ()


def test_priority_reason_order_determinism_and_immutability():
    from apps.sales.services.solution_readiness import check_solution_readiness

    analysis = typed_analysis(budget="conflict", data_security_requirement="conflict", integration_requirement="unclear")
    result = check_solution_readiness(analysis)
    assert result.status == "needs_presales_involvement"
    assert result.blocking_fields == ("data_security_requirement", "budget")
    assert result.gap_fields == ("integration_requirement",)
    assert result == check_solution_readiness(analysis)
    assert all(isinstance(value, tuple) for value in (result.blocking_fields, result.gap_fields, result.reasons))
    with pytest.raises(FrozenInstanceError):
        result.status = "ready"
