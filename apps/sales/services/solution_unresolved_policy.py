"""Deterministic planning-purpose policy; candidates still require all vetoes."""

from dataclasses import dataclass
from enum import StrEnum

from .requirement_analysis import OpportunityRequirementAnalysis, RequirementDimension, RequirementStatus
from .solution_plan_expressions import (
    PlanClauseKind as K, PlanPrerequisite, parse_plan_expression, explicit_plan_dependencies,
)


PlacementKey = tuple[str, str, str]


class PolicyDecision(StrEnum):
    CANDIDATE = "candidate"
    REJECT = "reject"
    UNCLASSIFIED = "unclassified"


class PolicyReason(StrEnum):
    UNCONFIRMED_ASSERTION = "unconfirmed_assertion"
    UNQUALIFIED_PRECONDITION = "unqualified_precondition"
    EXPRESSION_UNCLASSIFIED = "expression_unclassified"
    INVALID_LINKAGE = "invalid_linkage"


@dataclass(frozen=True)
class UnresolvedPolicyResult:
    decision: PolicyDecision
    reason: PolicyReason | None = None


_ACTION_KINDS = frozenset((K.INQUIRY, K.PLANNED_ARTIFACT, K.VERIFICATION_OUTCOME, K.CONDITIONAL_WORK))
# One routing/purpose table is consumed by both policy and input guidance.
_TARGETS = {
    ("implementation_plan", "implementation_phase", "objective"): ("implementation", "phases[].objective", _ACTION_KINDS),
    ("implementation_plan", "implementation_phase", "tasks"): ("implementation", "phases[].tasks", _ACTION_KINDS),
    ("implementation_plan", "implementation_phase", "deliverables"): ("implementation", "phases[].deliverables", frozenset((K.PLANNED_ARTIFACT, K.VERIFICATION_OUTCOME))),
    ("implementation_plan", "implementation_phase", "timing"): ("implementation", "phases[].timing", frozenset((K.CONDITIONAL_WORK,))),
    ("risks", "risk", "condition"): ("assurance", "risks[].condition", frozenset((K.HYPOTHETICAL_RISK,))),
    ("risks", "risk", "impact"): ("assurance", "risks[].impact", frozenset((K.HYPOTHETICAL_RISK,))),
    ("risks", "risk", "mitigation"): ("assurance", "risks[].mitigation", _ACTION_KINDS),
    ("milestones", "milestone", "outcome"): ("implementation", "milestones[].outcome", frozenset((K.VERIFICATION_OUTCOME, K.PLANNED_ARTIFACT, K.CONDITIONAL_WORK))),
}
_RESULT_DEPENDENCIES = frozenset((
    RequirementDimension.DEPLOYMENT_REQUIREMENT, RequirementDimension.EXISTING_ENVIRONMENT,
    RequirementDimension.USER_SCALE, RequirementDimension.INTEGRATION_REQUIREMENT,
    RequirementDimension.DATA_SECURITY_REQUIREMENT, RequirementDimension.TECHNICAL_CONSTRAINTS,
))


def _reject(reason: PolicyReason) -> UnresolvedPolicyResult:
    return UnresolvedPolicyResult(PolicyDecision.REJECT, reason)


def evaluate_unresolved_v2_policy(
    *, analysis: OpportunityRequirementAnalysis, related_fields: tuple[RequirementDimension, ...],
    text: str, placement: PlacementKey,
) -> UnresolvedPolicyResult | None:
    """None means route to original guards, never permission to save."""
    if not isinstance(placement, tuple) or len(placement) != 3 or placement not in _TARGETS:
        return None
    if (not isinstance(text, str) or not text.strip() or not isinstance(related_fields, tuple)
            or any(not isinstance(field, RequirementDimension) for field in related_fields)
            or len(set(related_fields)) != len(related_fields)
            or not isinstance(analysis, OpportunityRequirementAnalysis)):
        return _reject(PolicyReason.INVALID_LINKAGE)
    clauses = parse_plan_expression(text)
    for hint in explicit_plan_dependencies(text):
        field = RequirementDimension(hint)
        if (getattr(analysis.requirements, hint).status is not RequirementStatus.KNOWN
                and field not in related_fields):
            return _reject(PolicyReason.INVALID_LINKAGE)
    unresolved = frozenset(field for field in related_fields
                           if getattr(analysis.requirements, field.value).status is not RequirementStatus.KNOWN)
    if not unresolved:
        return None
    if not clauses:
        return UnresolvedPolicyResult(PolicyDecision.UNCLASSIFIED, PolicyReason.EXPRESSION_UNCLASSIFIED)
    if any(clause.kind is K.ASSERTION for clause in clauses):
        return _reject(PolicyReason.UNCONFIRMED_ASSERTION)
    # Result dependencies require explicit satisfied conditions, not mere completion.
    result_dependencies = unresolved & _RESULT_DEPENDENCIES
    for clause in clauses:
        if clause.kind is not K.CONDITIONAL_WORK or not result_dependencies:
            continue
        if (clause.prerequisite is not PlanPrerequisite.SATISFIED
                or not result_dependencies.issubset(set(clause.dependencies))):
            return _reject(PolicyReason.UNQUALIFIED_PRECONDITION)
    if any(clause.kind not in _TARGETS[placement][2] for clause in clauses):
        return UnresolvedPolicyResult(PolicyDecision.UNCLASSIFIED, PolicyReason.EXPRESSION_UNCLASSIFIED)
    return UnresolvedPolicyResult(PolicyDecision.CANDIDATE)


@dataclass(frozen=True)
class PlanGuidanceExample:
    target: str
    kind: K
    text: str


@dataclass(frozen=True)
class UnresolvedGenerationGuidance:
    targets: tuple[str, ...]
    action_examples: tuple[str, ...]
    result_counterexamples: tuple[str, ...]
    field_examples: tuple[PlanGuidanceExample, ...]


_PURPOSE_EXAMPLES = {
    K.INQUIRY: "核验部署条件。",
    K.PLANNED_ARTIFACT: "形成容量核验记录。",
    K.CONDITIONAL_WORK: "经核验确认部署条件满足后开展建设。",
    K.HYPOTHETICAL_RISK: "若容量不满足，则试点部署可能受到影响。",
    K.VERIFICATION_OUTCOME: "完成容量核验并记录结果。",
}


def unresolved_v2_generation_guidance(pass_name: str) -> UnresolvedGenerationGuidance | None:
    entries = [item for item in _TARGETS.values() if item[0] == pass_name]
    if not entries:
        return None
    examples = []
    for _, target, allowed in entries:
        kind = next(kind for kind in _PURPOSE_EXAMPLES if kind in allowed)
        examples.append(PlanGuidanceExample(target, kind, _PURPOSE_EXAMPLES[kind]))
    return UnresolvedGenerationGuidance(
        tuple(item[1] for item in entries),
        ("核验部署条件。", "评估服务器容量是否满足本期部署需求。"),
        ("现有环境已满足部署需求。", "现有服务器容量足够。"), tuple(examples),
    )
