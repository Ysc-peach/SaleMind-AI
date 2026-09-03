"""Independent, fail-closed semantic verification for grounded drafts."""

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from apps.llm.base import LLMProvider
from apps.llm.factory import get_llm_provider
from apps.sales.services.requirement_analysis import (
    ClarifyingQuestion,
    OpportunityRequirementAnalysis,
    RequirementConflict,
    RequirementDimension,
    RequirementFieldAnalysis,
)
from apps.sales.services.solution_grounding_prompt import build_solution_grounding_messages
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import (
    AtomicSolutionClaimSet,
    SolutionDraft,
    SolutionStatement,
    SolutionStatementType,
)


class GroundingRelation(StrEnum):
    SUPPORTED = "SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"
    CONTRADICTED = "CONTRADICTED"


class GroundingViolationCode(StrEnum):
    CUSTOMER_FACT_NOT_SUPPORTED = "CUSTOMER_FACT_NOT_SUPPORTED"
    ENTERPRISE_FACT_NOT_SUPPORTED = "ENTERPRISE_FACT_NOT_SUPPORTED"
    UNCONFIRMED_AS_ENTERPRISE_FACT = "UNCONFIRMED_AS_ENTERPRISE_FACT"
    UNCONFIRMED_AS_NEGATIVE = "UNCONFIRMED_AS_NEGATIVE"
    REQUIREMENT_PROMOTED_TO_CAPABILITY = "REQUIREMENT_PROMOTED_TO_CAPABILITY"
    PROPOSAL_NOT_SUPPORTED = "PROPOSAL_NOT_SUPPORTED"
    ENVIRONMENT_INFERENCE = "ENVIRONMENT_INFERENCE"
    MIXED_GROUNDING_STATUS = "MIXED_GROUNDING_STATUS"
    CITATION_SEMANTIC_MISMATCH = "CITATION_SEMANTIC_MISMATCH"
    OTHER_GROUNDING_VIOLATION = "OTHER_GROUNDING_VIOLATION"


@dataclass(frozen=True, slots=True)
class SolutionGroundingViolation:
    code: GroundingViolationCode
    location: str


@dataclass(frozen=True, slots=True)
class GroundingClaimPacket:
    location: str
    statement_type: SolutionStatementType
    text: str
    evidence: tuple[SolutionSource, ...]
    customer_context: "GroundingCustomerContext | OpportunityRequirementAnalysis | None"


@dataclass(frozen=True, slots=True)
class GroundingCustomerRequirement:
    field: RequirementDimension
    analysis: RequirementFieldAnalysis


@dataclass(frozen=True, slots=True)
class GroundingCustomerContext:
    requirements: tuple[GroundingCustomerRequirement, ...]
    conflicts: tuple[RequirementConflict, ...]
    clarifying_questions: tuple[ClarifyingQuestion, ...]


@dataclass(frozen=True, slots=True)
class GroundingClaimResult:
    location: str
    relation: GroundingRelation


@dataclass(frozen=True, slots=True)
class SolutionGroundingVerification:
    passed: bool
    results: tuple[GroundingClaimResult, ...]
    violations: tuple[SolutionGroundingViolation, ...]


class SolutionGroundingErrorCode(StrEnum):
    INVALID_INPUT = "invalid_solution_grounding_input"
    INVALID_RESPONSE = "solution_grounding_invalid_response"
    NOT_GROUNDED = "solution_draft_not_grounded"


class SolutionDraftGroundingError(Exception):
    """Stable failure with optional safe code/location pairs only."""

    def __init__(
        self,
        code: SolutionGroundingErrorCode,
        *,
        violations: tuple[SolutionGroundingViolation, ...] = (),
    ):
        self.code = code.value
        self.safe_message = {
            SolutionGroundingErrorCode.INVALID_INPUT: "The solution grounding input is invalid.",
            SolutionGroundingErrorCode.INVALID_RESPONSE: "The solution grounding response is invalid.",
            SolutionGroundingErrorCode.NOT_GROUNDED: "The solution draft did not pass grounding verification.",
        }[code]
        self.violations = violations
        super().__init__(self.safe_message)


def verify_solution_draft_grounding(
    *,
    analysis: OpportunityRequirementAnalysis,
    draft: SolutionDraft,
    sources: tuple[SolutionSource, ...],
    llm_provider: LLMProvider | None = None,
) -> SolutionGroundingVerification:
    """Compatibility boundary for callers that already hold a final draft."""
    packets = build_grounding_claim_packets(analysis, draft, sources)
    return _verify_packets(packets, llm_provider)


def verify_atomic_solution_claims(
    *,
    analysis: OpportunityRequirementAnalysis,
    claims: AtomicSolutionClaimSet,
    sources: tuple[SolutionSource, ...],
    llm_provider: LLMProvider | None = None,
) -> SolutionGroundingVerification:
    """Verify every generated atomic claim in one type-aware batched request."""
    packets = build_atomic_grounding_claim_packets(analysis, claims, sources)
    return _verify_packets(packets, llm_provider)


def _verify_packets(
    packets: tuple[GroundingClaimPacket, ...],
    llm_provider: LLMProvider | None,
) -> SolutionGroundingVerification:
    provider = llm_provider if llm_provider is not None else get_llm_provider()
    generation = provider.generate(
        build_solution_grounding_messages(packets),
    )
    results = _parse_results(generation.content, packets=packets)
    violations = []
    for packet, result in zip(packets, results, strict=True):
        if result.relation is not GroundingRelation.SUPPORTED:
            violations.append(SolutionGroundingViolation(
                _violation_code(packet.statement_type), packet.location,
            ))
    verification = SolutionGroundingVerification(
        passed=not violations,
        results=results,
        violations=tuple(violations),
    )
    if not verification.passed:
        raise SolutionDraftGroundingError(
            SolutionGroundingErrorCode.NOT_GROUNDED,
            violations=verification.violations,
        )
    return verification


def build_atomic_grounding_claim_packets(
    analysis: OpportunityRequirementAnalysis,
    claims: AtomicSolutionClaimSet,
    sources: tuple[SolutionSource, ...],
) -> tuple[GroundingClaimPacket, ...]:
    """Scope authoritative evidence independently for each atomic IR claim."""
    if not isinstance(analysis, OpportunityRequirementAnalysis) or not isinstance(claims, AtomicSolutionClaimSet):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    _validate_sources(sources)
    source_by_label = {source.label: source for source in sources}
    packets = []
    for index, claim in enumerate(claims.claims):
        if any(label not in source_by_label for label in claim.citations):
            raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
        evidence = () if claim.statement_type is SolutionStatementType.CUSTOMER_FACT else tuple(
            source_by_label[label] for label in claim.citations
        )
        customer_context = None
        if claim.statement_type is not SolutionStatementType.ENTERPRISE_FACT:
            customer_context = _customer_context_for_section(analysis, claim.section.value)
        packets.append(GroundingClaimPacket(
            location=f"claims[{index}]",
            statement_type=claim.statement_type,
            text=claim.text,
            evidence=evidence,
            customer_context=customer_context,
        ))
    return tuple(packets)


_CUSTOMER_FIELDS_BY_SECTION = {
    "overall_approach": (
        RequirementDimension.BUSINESS_GOAL,
        RequirementDimension.USE_SCENARIO,
        RequirementDimension.USER_SCALE,
        RequirementDimension.DEPLOYMENT_REQUIREMENT,
        RequirementDimension.DATA_SECURITY_REQUIREMENT,
    ),
    "deployment": (
        RequirementDimension.DEPLOYMENT_REQUIREMENT,
        RequirementDimension.DATA_SECURITY_REQUIREMENT,
        RequirementDimension.EXISTING_ENVIRONMENT,
        RequirementDimension.USER_SCALE,
        RequirementDimension.TECHNICAL_CONSTRAINTS,
    ),
    "data_security": (
        RequirementDimension.DATA_SECURITY_REQUIREMENT,
        RequirementDimension.DEPLOYMENT_REQUIREMENT,
        RequirementDimension.TECHNICAL_CONSTRAINTS,
    ),
    "integration": (
        RequirementDimension.INTEGRATION_REQUIREMENT,
        RequirementDimension.EXISTING_ENVIRONMENT,
        RequirementDimension.USE_SCENARIO,
        RequirementDimension.TECHNICAL_CONSTRAINTS,
    ),
    "implementation": (
        RequirementDimension.TIMELINE,
        RequirementDimension.BUDGET,
        RequirementDimension.EXISTING_ENVIRONMENT,
        RequirementDimension.INTEGRATION_REQUIREMENT,
        RequirementDimension.TECHNICAL_CONSTRAINTS,
    ),
}


def _customer_context_for_section(
    analysis: OpportunityRequirementAnalysis,
    section: str,
) -> GroundingCustomerContext:
    fields = _CUSTOMER_FIELDS_BY_SECTION[section]
    allowed = frozenset(fields)
    return GroundingCustomerContext(
        requirements=tuple(
            GroundingCustomerRequirement(field, getattr(analysis.requirements, field.value))
            for field in fields
        ),
        conflicts=tuple(
            conflict for conflict in analysis.conflicts if any(field in allowed for field in conflict.fields)
        ),
        clarifying_questions=tuple(
            question for question in analysis.clarifying_questions if question.field in allowed
        ),
    )


def build_grounding_claim_packets(
    analysis: OpportunityRequirementAnalysis,
    draft: SolutionDraft,
    sources: tuple[SolutionSource, ...],
) -> tuple[GroundingClaimPacket, ...]:
    """Freeze one scoped verifier packet per structurally valid statement."""
    _validate_input(analysis, draft, sources)
    source_by_label = {source.label: source for source in sources}
    packets = []
    for location, statement in _located_statements(draft):
        if any(label not in source_by_label for label in statement.citations):
            raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
        evidence = () if statement.type is SolutionStatementType.CUSTOMER_FACT else tuple(
            source_by_label[label] for label in statement.citations
        )
        customer_context = (
            None if statement.type is SolutionStatementType.ENTERPRISE_FACT else analysis
        )
        packets.append(GroundingClaimPacket(
            location=location,
            statement_type=statement.type,
            text=statement.text,
            evidence=evidence,
            customer_context=customer_context,
        ))
    return tuple(packets)


def _validate_input(
    analysis: OpportunityRequirementAnalysis,
    draft: SolutionDraft,
    sources: tuple[SolutionSource, ...],
) -> None:
    if not isinstance(analysis, OpportunityRequirementAnalysis) or not isinstance(draft, SolutionDraft):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    _validate_sources(sources)


def _validate_sources(sources: tuple[SolutionSource, ...]) -> None:
    if (
        not isinstance(sources, tuple)
        or not sources
        or any(not isinstance(source, SolutionSource) for source in sources)
        or tuple(source.label for source in sources) != tuple(f"S{i}" for i in range(1, len(sources) + 1))
    ):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)


def _located_statements(draft: SolutionDraft) -> tuple[tuple[str, SolutionStatement], ...]:
    items = [
        (f"executive_summary[{index}]", statement)
        for index, statement in enumerate(draft.executive_summary)
    ]
    items.extend(
        (f"solution_sections.{section.key}.statements[{index}]", statement)
        for section in draft.solution_sections
        for index, statement in enumerate(section.statements)
    )
    return tuple(items)


def _parse_results(
    content: str,
    *,
    packets: tuple[GroundingClaimPacket, ...],
) -> tuple[GroundingClaimResult, ...]:
    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        _invalid_response()
    _object(payload, {"results"})
    items = payload["results"]
    if not isinstance(items, list) or len(items) != len(packets):
        _invalid_response()
    allowed_locations = frozenset(packet.location for packet in packets)
    by_location = {}
    for item in items:
        _object(item, {"location", "relation"})
        location = item["location"]
        relation = item["relation"]
        if (
            not isinstance(location, str)
            or location not in allowed_locations
            or location in by_location
            or not isinstance(relation, str)
            or relation not in GroundingRelation._value2member_map_
        ):
            _invalid_response()
        by_location[location] = GroundingClaimResult(location, GroundingRelation(relation))
    if set(by_location) != allowed_locations:
        _invalid_response()
    return tuple(by_location[packet.location] for packet in packets)


def _violation_code(statement_type: SolutionStatementType) -> GroundingViolationCode:
    return {
        SolutionStatementType.CUSTOMER_FACT: GroundingViolationCode.CUSTOMER_FACT_NOT_SUPPORTED,
        SolutionStatementType.ENTERPRISE_FACT: GroundingViolationCode.ENTERPRISE_FACT_NOT_SUPPORTED,
        SolutionStatementType.PROPOSAL: GroundingViolationCode.PROPOSAL_NOT_SUPPORTED,
        SolutionStatementType.UNRESOLVED: GroundingViolationCode.OTHER_GROUNDING_VIOLATION,
    }[statement_type]


def _object(value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid_response()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid_response()
    return value.strip()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError("Nonstandard JSON constant.")


def _invalid_response() -> NoReturn:
    raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_RESPONSE)
