"""Stable JSON mapping for the in-memory SolutionDraft domain object."""

import pytest

from apps.sales.services.requirement_analysis import RequirementDimension, RequirementStatus
from apps.sales.services.solution_schema import (
    SolutionAssumption,
    SolutionDraft,
    SolutionSection,
    SolutionStatement,
    SolutionStatementType,
)


@pytest.fixture
def domain_draft():
    enterprise = SolutionStatement(
        SolutionStatementType.ENTERPRISE_FACT,
        "SalesMind 支持私有化部署。",
        ("S1",),
    )
    proposal = SolutionStatement(
        SolutionStatementType.PROPOSAL,
        "建议采用私有化部署方案。",
        ("S1",),
    )
    return SolutionDraft(
        title="商机需求解决方案内部草稿",
        executive_summary=(enterprise,),
        solution_sections=(
            SolutionSection("overall_approach", "总体方案", (proposal,)),
            SolutionSection("deployment", "部署方案", (enterprise,)),
            SolutionSection("data_security", "数据安全", ()),
            SolutionSection("integration", "系统集成", ()),
            SolutionSection("implementation", "实施建议", ()),
        ),
        assumptions=(
            SolutionAssumption(
                "预算信息缺失，待确认。",
                (RequirementDimension.BUDGET,),
            ),
        ),
    )


def test_solution_draft_json_round_trip_preserves_domain_value(domain_draft):
    from apps.sales.services.solution_persistence import (
        solution_draft_from_payload,
        solution_draft_to_payload,
    )

    payload = solution_draft_to_payload(domain_draft)

    assert payload == {
        "title": "商机需求解决方案内部草稿",
        "executive_summary": [
            {
                "type": "enterprise_fact",
                "text": "SalesMind 支持私有化部署。",
                "citations": ["S1"],
            }
        ],
        "solution_sections": [
            {
                "key": "overall_approach",
                "title": "总体方案",
                "statements": [
                    {
                        "type": "proposal",
                        "text": "建议采用私有化部署方案。",
                        "citations": ["S1"],
                    }
                ],
            },
            {
                "key": "deployment",
                "title": "部署方案",
                "statements": [
                    {
                        "type": "enterprise_fact",
                        "text": "SalesMind 支持私有化部署。",
                        "citations": ["S1"],
                    }
                ],
            },
            {"key": "data_security", "title": "数据安全", "statements": []},
            {"key": "integration", "title": "系统集成", "statements": []},
            {"key": "implementation", "title": "实施建议", "statements": []},
        ],
        "assumptions": [
            {"text": "预算信息缺失，待确认。", "related_fields": ["budget"]}
        ],
    }
    assert solution_draft_from_payload(payload) == domain_draft


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(extra=True),
        lambda payload: payload["executive_summary"][0].update(extra=True),
        lambda payload: payload["solution_sections"].pop(),
        lambda payload: payload["solution_sections"][0].update(key="unknown"),
        lambda payload: payload["assumptions"][0].update(related_fields=["unknown"]),
        lambda payload: payload["executive_summary"].extend(
            [payload["executive_summary"][0].copy() for _ in range(8)]
        ),
    ],
)
def test_solution_draft_from_payload_rejects_noncanonical_payload(domain_draft, mutate):
    from apps.sales.services.solution_persistence import (
        SolutionPersistenceError,
        solution_draft_from_payload,
        solution_draft_to_payload,
    )

    payload = solution_draft_to_payload(domain_draft)
    mutate(payload)

    with pytest.raises(SolutionPersistenceError):
        solution_draft_from_payload(payload)


def test_solution_draft_to_payload_rejects_wrong_domain_type():
    from apps.sales.services.solution_persistence import (
        SolutionPersistenceError,
        solution_draft_to_payload,
    )

    with pytest.raises(SolutionPersistenceError):
        solution_draft_to_payload({"title": "not a domain object"})
