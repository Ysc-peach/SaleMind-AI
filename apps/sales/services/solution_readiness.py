"""Pure, deterministic readiness rules over validated requirement analyses."""

from dataclasses import dataclass
from enum import StrEnum

from apps.sales.services.requirement_analysis import (
    OpportunityRequirementAnalysis, RequirementDimension as Dimension,
    RequirementStatus as Status,
)


class SolutionReadinessStatus(StrEnum):
    READY = "ready"
    READY_WITH_GAPS = "ready_with_gaps"
    NEEDS_SALES_CLARIFICATION = "needs_sales_clarification"
    NEEDS_PRESALES_INVOLVEMENT = "needs_presales_involvement"


@dataclass(frozen=True, slots=True)
class SolutionReadiness:
    status: SolutionReadinessStatus
    blocking_fields: tuple[Dimension, ...]
    gap_fields: tuple[Dimension, ...]
    reasons: tuple[str, ...]


TECHNICAL_CONFLICT_FIELDS = frozenset({
    Dimension.DEPLOYMENT_REQUIREMENT, Dimension.DATA_SECURITY_REQUIREMENT,
    Dimension.EXISTING_ENVIRONMENT, Dimension.INTEGRATION_REQUIREMENT,
    Dimension.TECHNICAL_CONSTRAINTS,
})
# Commercial uncertainty remains in the customer facts, but alone does not
# prevent a technically complete draft. Commercial conflicts still block.
SOLUTION_GAP_FIELDS = frozenset(Dimension) - {Dimension.BUDGET, Dimension.TIMELINE}
_LABELS = dict(zip(Dimension, (
    "业务目标", "使用场景", "使用人数", "部署要求", "数据安全要求",
    "现有环境", "集成要求", "时间要求", "预算", "技术约束",
), strict=True))


def check_solution_readiness(analysis: OpportunityRequirementAnalysis) -> SolutionReadiness:
    """No I/O; ordering always follows the original ten-dimension schema."""
    states = {name: getattr(analysis.requirements, name).status for name in Dimension}
    conflicts = {name for name, status in states.items() if status is Status.CONFLICT}
    vague = {Status.UNKNOWN, Status.UNCLEAR}
    goal, scenario = states[Dimension.BUSINESS_GOAL], states[Dimension.USE_SCENARIO]
    missing_direction = (
        goal is Status.UNKNOWN and scenario in vague
        or goal in vague and scenario is Status.UNKNOWN
    )
    blockers = conflicts | ({Dimension.BUSINESS_GOAL, Dimension.USE_SCENARIO} if missing_direction else set())
    gaps = {name for name in SOLUTION_GAP_FIELDS if states[name] in vague} - blockers
    if conflicts & TECHNICAL_CONFLICT_FIELDS:
        status = SolutionReadinessStatus.NEEDS_PRESALES_INVOLVEMENT
    elif blockers:
        status = SolutionReadinessStatus.NEEDS_SALES_CLARIFICATION
    elif gaps:
        status = SolutionReadinessStatus.READY_WITH_GAPS
    else:
        status = SolutionReadinessStatus.READY
    explanations = {Status.UNKNOWN: "信息缺失", Status.UNCLEAR: "尚不明确", Status.CONFLICT: "存在冲突"}
    return SolutionReadiness(
        status=status,
        blocking_fields=tuple(name for name in Dimension if name in blockers),
        gap_fields=tuple(name for name in Dimension if name in gaps),
        reasons=tuple(f"{_LABELS[name]}{explanations[states[name]]}" for name in Dimension if name in blockers | gaps),
    )
