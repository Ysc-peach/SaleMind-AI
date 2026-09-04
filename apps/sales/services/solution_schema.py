"""Strict statement provenance and citations, not semantic entailment checking."""

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from apps.sales.services.requirement_analysis import (
    OpportunityRequirementAnalysis, RequirementDimension as Dimension, RequirementStatus as Status,
)
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode


SECTION_DEFINITIONS = (
    ("overall_approach", "总体方案"), ("deployment", "部署方案"),
    ("data_security", "数据安全"), ("integration", "系统集成"),
    ("implementation", "实施建议"),
)
SOLUTION_DRAFT_TITLE = "商机需求解决方案内部草稿"


class SolutionSectionKey(StrEnum):
    OVERALL_APPROACH = "overall_approach"
    DEPLOYMENT = "deployment"
    DATA_SECURITY = "data_security"
    INTEGRATION = "integration"
    IMPLEMENTATION = "implementation"


class SolutionStatementType(StrEnum):
    CUSTOMER_FACT = "customer_fact"
    ENTERPRISE_FACT = "enterprise_fact"
    PROPOSAL = "proposal"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class SolutionStatement:
    type: SolutionStatementType
    text: str
    citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SolutionSection:
    key: str
    title: str
    statements: tuple[SolutionStatement, ...]


@dataclass(frozen=True, slots=True)
class SolutionAssumption:
    text: str
    related_fields: tuple[Dimension, ...]


@dataclass(frozen=True, slots=True)
class SolutionUnresolvedItem:
    field: Dimension
    status: Status
    text: str


@dataclass(frozen=True, slots=True)
class SolutionDraft:
    title: str
    executive_summary: tuple[SolutionStatement, ...]
    solution_sections: tuple[SolutionSection, ...]
    assumptions: tuple[SolutionAssumption, ...]


@dataclass(frozen=True, slots=True)
class AtomicSolutionClaim:
    """One independently verifiable proposition produced by the generation LLM."""

    section: SolutionSectionKey
    statement_type: SolutionStatementType
    text: str
    citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AtomicSolutionClaimSet:
    claims: tuple[AtomicSolutionClaim, ...]


def parse_atomic_solution_proposals(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
) -> AtomicSolutionClaimSet:
    """Parse the proposal-only IR; all fact types are program-owned."""

    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError):
        _invalid()
    _object(payload, {"proposals"})
    items = payload["proposals"]
    if not isinstance(items, list) or len(items) > 30:
        _invalid()
    if (
        not isinstance(allowed_source_labels, tuple)
        or len(set(allowed_source_labels)) != len(allowed_source_labels)
        or any(not isinstance(label, str) for label in allowed_source_labels)
    ):
        _invalid()
    labels = frozenset(allowed_source_labels)
    claims = []
    for item in items:
        _object(item, {"section", "text", "citations"})
        section = item["section"]
        if (
            not isinstance(section, str)
            or section not in SolutionSectionKey._value2member_map_
        ):
            _invalid()
        citations = item["citations"]
        if (
            not isinstance(citations, list)
            or not citations
            or len(set(citations)) != len(citations)
            or any(
                not isinstance(label, str) or label not in labels
                for label in citations
            )
        ):
            _invalid()
        claims.append(
            AtomicSolutionClaim(
                section=SolutionSectionKey(section),
                statement_type=SolutionStatementType.PROPOSAL,
                text=_prose(item["text"]),
                citations=tuple(citations),
            )
        )
    return AtomicSolutionClaimSet(tuple(claims))


def parse_atomic_solution_claims(content: str, *, source_count: int) -> AtomicSolutionClaimSet:
    """Parse the deliberately small generation IR without repairing model output."""
    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        _invalid()
    _object(payload, {"claims"})
    items = payload["claims"]
    if not isinstance(items, list) or not 1 <= len(items) <= 60:
        _invalid()
    labels = frozenset(f"S{i}" for i in range(1, source_count + 1))
    claims = []
    for item in items:
        _object(item, {"section", "statement_type", "text", "citations"})
        section = item["section"]
        kind = item["statement_type"]
        if (
            not isinstance(section, str)
            or section not in SolutionSectionKey._value2member_map_
            or not isinstance(kind, str)
            or kind not in SolutionStatementType._value2member_map_
        ):
            _invalid()
        statement_type = SolutionStatementType(kind)
        citations = _citations(item["citations"], labels, statement_type)
        claims.append(AtomicSolutionClaim(
            SolutionSectionKey(section), statement_type, _prose(item["text"]), citations,
        ))
    if any(
        sum(claim.section is section for claim in claims) > 12
        for section in SolutionSectionKey
    ):
        _invalid()
    return AtomicSolutionClaimSet(tuple(claims))


def assemble_solution_draft(
    claim_set: AtomicSolutionClaimSet,
    analysis: OpportunityRequirementAnalysis,
) -> SolutionDraft:
    """Build the stable public draft envelope from verified atomic claims only."""
    if not isinstance(claim_set, AtomicSolutionClaimSet) or not isinstance(
        analysis, OpportunityRequirementAnalysis,
    ):
        _invalid()
    statements_by_section = {key: [] for key in SolutionSectionKey}
    for claim in claim_set.claims:
        statement = SolutionStatement(claim.statement_type, claim.text, claim.citations)
        statements_by_section[claim.section].append(statement)
    sections = tuple(
        SolutionSection(key, title, tuple(statements_by_section[SolutionSectionKey(key)]))
        for key, title in SECTION_DEFINITIONS
    )
    summary = sections[0].statements[:8]
    if not summary:
        summary = tuple(
            section.statements[0] for section in sections if section.statements
        )[:8]
    return SolutionDraft(
        title=SOLUTION_DRAFT_TITLE,
        executive_summary=summary,
        solution_sections=sections,
        assumptions=tuple(
            SolutionAssumption(item.text, (item.field,))
            for item in build_solution_unresolved_items(analysis)
        ),
    )


def parse_solution_draft(
    content: str, *, source_count: int, analysis: OpportunityRequirementAnalysis,
) -> SolutionDraft:
    """Reject malformed output; source labels come only from the merged evidence.

    Analysis is the already validated historical input, used to constrain
    assumptions. No natural-language repair or free-text citation normalization.
    """
    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise SolutionDraftError(SolutionDraftErrorCode.INVALID_RESPONSE) from None
    _object(payload, {"title", "executive_summary", "solution_sections", "assumptions"})
    labels = frozenset(f"S{i}" for i in range(1, source_count + 1))
    sections = payload["solution_sections"]
    if not isinstance(sections, list) or len(sections) != 5:
        _invalid()
    parsed_sections = []
    for section, (key, title) in zip(sections, SECTION_DEFINITIONS, strict=True):
        _object(section, {"key", "title", "statements"})
        if section["key"] != key or section["title"] != title:
            _invalid()
        parsed_sections.append(SolutionSection(
            key=key, title=title, statements=_statements(section["statements"], labels, maximum=12),
        ))
    return SolutionDraft(
        title=_prose(payload["title"]),
        executive_summary=_statements(payload["executive_summary"], labels, maximum=8),
        solution_sections=tuple(parsed_sections), assumptions=_assumptions(payload["assumptions"], analysis),
    )


def _statements(value: object, labels: frozenset[str], *, maximum: int) -> tuple[SolutionStatement, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        _invalid()
    result = []
    for item in value:
        _object(item, {"type", "text", "citations"})
        if not isinstance(item["type"], str) or item["type"] not in SolutionStatementType._value2member_map_:
            _invalid()
        kind = SolutionStatementType(item["type"])
        citations = _citations(item["citations"], labels, kind)
        result.append(SolutionStatement(kind, _prose(item["text"]), citations))
    return tuple(result)


def _citations(
    value: object,
    labels: frozenset[str],
    kind: SolutionStatementType,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(label, str) or label not in labels for label in value)
        or len(set(value)) != len(value)
    ):
        _invalid()
    if kind is SolutionStatementType.CUSTOMER_FACT and value:
        _invalid()
    if kind in {SolutionStatementType.ENTERPRISE_FACT, SolutionStatementType.PROPOSAL} and not value:
        _invalid()
    return tuple(value)


def _assumptions(value: object, analysis: OpportunityRequirementAnalysis) -> tuple[SolutionAssumption, ...]:
    if not isinstance(value, list) or len(value) > 10:
        _invalid()
    result = []
    for item in value:
        _object(item, {"text", "related_fields"})
        fields = item["related_fields"]
        if (not isinstance(fields, list) or not fields
                or any(not isinstance(name, str) or name not in Dimension._value2member_map_ for name in fields)
                or len(set(fields)) != len(fields)):
            _invalid()
        dimensions = tuple(Dimension(name) for name in fields)
        if any(getattr(analysis.requirements, name).status is Status.KNOWN for name in dimensions):
            _invalid()
        result.append(SolutionAssumption(_prose(item["text"]), dimensions))
    return tuple(result)


def render_solution_statement(statement: SolutionStatement) -> str:
    """Render a validated domain statement; preserve authoritative label order."""
    return statement.text + "".join(f"[{label}]" for label in statement.citations)


def build_solution_unresolved_items(analysis: OpportunityRequirementAnalysis) -> tuple[SolutionUnresolvedItem, ...]:
    """All nonknown fields, including commercial gaps, independent of the LLM."""
    labels = dict(zip(Dimension, (
        "业务目标", "使用场景", "使用人数", "部署要求", "数据安全要求", "现有环境",
        "集成要求", "时间要求", "预算", "技术约束",
    ), strict=True))
    descriptions = {Status.UNKNOWN: "信息缺失，待确认", Status.UNCLEAR: "尚未明确，待确认",
                    Status.CONFLICT: "存在冲突，待确认"}
    result = []
    for name in Dimension:
        status = getattr(analysis.requirements, name).status
        if status is Status.KNOWN:
            continue
        questions = tuple(q.question for q in analysis.clarifying_questions if q.field == name)
        text = f"{labels[name]}{descriptions[status]}。"
        if questions:
            text += " ".join(questions)
        result.append(SolutionUnresolvedItem(name, status, text))
    return tuple(result)


def _object(value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid()
    return value.strip()


# A small lexical guard, not NLP: reject standalone S-number tokens (including
# bracketed/grouped variants) without converting digits or leading zeroes.
_SOURCE_TOKEN = re.compile(r"(?<![A-Za-z0-9_])S[0-9]+(?![A-Za-z0-9_])")


def _prose(value: object) -> str:
    text = _text(value)
    if _SOURCE_TOKEN.search(text):
        _invalid()
    return text


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError("Nonstandard JSON constant.")


def _invalid() -> NoReturn:
    raise SolutionDraftError(SolutionDraftErrorCode.INVALID_RESPONSE)
