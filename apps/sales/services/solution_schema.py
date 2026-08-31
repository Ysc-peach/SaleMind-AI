"""Strict JSON -> immutable solution draft; never repair or invent sources."""

import json
import re
from dataclasses import dataclass, replace
from typing import NoReturn

from apps.llm.citations import has_unknown_citations, normalize_citations
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode


SECTION_DEFINITIONS = (
    ("overall_approach", "总体方案"), ("deployment", "部署方案"),
    ("data_security", "数据安全"), ("integration", "系统集成"),
    ("implementation", "实施建议"),
)


@dataclass(frozen=True, slots=True)
class SolutionSection:
    key: str
    title: str
    content: str


@dataclass(frozen=True, slots=True)
class SolutionDraft:
    title: str
    executive_summary: str
    solution_sections: tuple[SolutionSection, ...]
    assumptions: tuple[str, ...]
    unresolved_items: tuple[str, ...]


def parse_solution_draft(content: str, *, source_count: int) -> SolutionDraft:
    """Validate shape first, then normalize and validate citations everywhere."""
    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise SolutionDraftError(SolutionDraftErrorCode.INVALID_RESPONSE) from None
    _object(payload, {"title", "executive_summary", "solution_sections", "assumptions", "unresolved_items"})
    sections = payload["solution_sections"]
    if not isinstance(sections, list) or len(sections) != 5:
        _invalid()
    parsed_sections = []
    for section, (key, title) in zip(sections, SECTION_DEFINITIONS, strict=True):
        _object(section, {"key", "title", "content"})
        if section["key"] != key or section["title"] != title:
            _invalid()
        parsed_sections.append(SolutionSection(key=key, title=title, content=_text(section["content"])))
    draft = SolutionDraft(
        title=_text(payload["title"]), executive_summary=_text(payload["executive_summary"]),
        solution_sections=tuple(parsed_sections), assumptions=_text_list(payload["assumptions"]),
        unresolved_items=_text_list(payload["unresolved_items"]),
    )

    def validated_citations(value: str) -> str:
        normalized = normalize_citations(value, source_count=source_count)
        if has_unknown_citations(normalized, source_count=source_count):
            _invalid()
        return normalized

    return SolutionDraft(
        title=validated_citations(draft.title), executive_summary=validated_citations(draft.executive_summary),
        solution_sections=tuple(replace(s, content=validated_citations(s.content)) for s in draft.solution_sections),
        assumptions=tuple(validated_citations(s) for s in draft.assumptions),
        unresolved_items=tuple(validated_citations(s) for s in draft.unresolved_items),
    )


def _object(value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid()
    return value.strip()


def _text_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 10:
        _invalid()
    return tuple(_text(item) for item in value)


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
