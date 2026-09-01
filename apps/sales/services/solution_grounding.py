"""Independent, fail-closed semantic verification for grounded drafts."""

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from apps.llm.base import LLMProvider
from apps.llm.factory import get_llm_provider
from apps.sales.services.requirement_analysis import OpportunityRequirementAnalysis
from apps.sales.services.solution_grounding_prompt import build_solution_grounding_messages
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import SolutionDraft


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
class SolutionGroundingVerification:
    passed: bool
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
    """Judge one structurally valid draft once; never retrieve, rewrite, or retry."""
    _validate_input(analysis, draft, sources)
    locations = _statement_locations(draft)
    provider = llm_provider if llm_provider is not None else get_llm_provider()
    generation = provider.generate(
        build_solution_grounding_messages(analysis, draft, sources, locations),
    )
    verification = _parse_verification(generation.content, allowed_locations=frozenset(locations))
    if not verification.passed:
        raise SolutionDraftGroundingError(
            SolutionGroundingErrorCode.NOT_GROUNDED,
            violations=verification.violations,
        )
    return verification


def _validate_input(
    analysis: OpportunityRequirementAnalysis,
    draft: SolutionDraft,
    sources: tuple[SolutionSource, ...],
) -> None:
    if not isinstance(analysis, OpportunityRequirementAnalysis) or not isinstance(draft, SolutionDraft):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    if (
        not isinstance(sources, tuple)
        or not sources
        or any(not isinstance(source, SolutionSource) for source in sources)
        or tuple(source.label for source in sources) != tuple(f"S{i}" for i in range(1, len(sources) + 1))
    ):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)


def _statement_locations(draft: SolutionDraft) -> tuple[str, ...]:
    locations = [f"executive_summary[{index}]" for index, _ in enumerate(draft.executive_summary)]
    locations.extend(
        f"solution_sections.{section.key}.statements[{index}]"
        for section in draft.solution_sections
        for index, _ in enumerate(section.statements)
    )
    return tuple(locations)


def _parse_verification(
    content: str,
    *,
    allowed_locations: frozenset[str],
) -> SolutionGroundingVerification:
    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        _invalid_response()
    _object(payload, {"passed", "violations"})
    passed, items = payload["passed"], payload["violations"]
    if not isinstance(passed, bool) or not isinstance(items, list):
        _invalid_response()
    violations = []
    seen = set()
    for item in items:
        _object(item, {"code", "location"})
        code, location = item["code"], item["location"]
        if (
            not isinstance(code, str)
            or code not in GroundingViolationCode._value2member_map_
            or not isinstance(location, str)
            or location not in allowed_locations
            or (code, location) in seen
        ):
            _invalid_response()
        seen.add((code, location))
        violations.append(SolutionGroundingViolation(GroundingViolationCode(code), location))
    if passed != (not violations):
        _invalid_response()
    return SolutionGroundingVerification(passed=passed, violations=tuple(violations))


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
