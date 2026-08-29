"""Pure, traceable chunk preparation for parsed knowledge segments."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from django.conf import settings

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.knowledge.parsers import ParsedSegment


_BOUNDARY_GROUPS = (
    ("\n\n",),
    ("\n",),
    ("。", "？", "！"),
    (".", "?", "!"),
    (" ",),
)
_MIN_EFFECTIVE_NON_WHITESPACE = 40


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk ready for later embedding and persistence."""

    chunk_index: int
    content: str
    page_number: int | None
    section_title: str | None
    source_reference: str
    metadata: dict[str, Any]
    char_count: int


def chunk_segments(
    segments: Iterable[ParsedSegment],
    *,
    chunk_size: int | None = None,
    overlap: int | None = None,
    max_chunks: int | None = None,
) -> list[ChunkDraft]:
    """Convert parsed segments into traceable drafts without side effects."""

    resolved_chunk_size = (
        settings.KNOWLEDGE_CHUNK_SIZE if chunk_size is None else chunk_size
    )
    resolved_overlap = (
        settings.KNOWLEDGE_CHUNK_OVERLAP if overlap is None else overlap
    )
    resolved_max_chunks = (
        settings.KNOWLEDGE_MAX_CHUNKS if max_chunks is None else max_chunks
    )
    _validate_configuration(
        chunk_size=resolved_chunk_size,
        overlap=resolved_overlap,
        max_chunks=resolved_max_chunks,
    )

    chunks: list[ChunkDraft] = []
    for segment in segments:
        content = segment.content.strip()
        if not content:
            continue
        for chunk_content in _split_segment(
            content,
            chunk_size=resolved_chunk_size,
            overlap=resolved_overlap,
        ):
            chunks.append(
                ChunkDraft(
                    chunk_index=len(chunks),
                    content=chunk_content,
                    page_number=segment.page_number,
                    section_title=segment.section_title,
                    source_reference=segment.source_reference,
                    metadata=deepcopy(segment.metadata),
                    char_count=len(chunk_content),
                )
            )
            if len(chunks) > resolved_max_chunks:
                raise KnowledgeDocumentError(
                    KnowledgeDocumentErrorCode.CHUNK_LIMIT_EXCEEDED
                )
    return chunks


def _split_segment(content: str, *, chunk_size: int, overlap: int) -> list[str]:
    ranges: list[tuple[int, int]] = []
    start = 0

    while start < len(content):
        end = _find_chunk_end(content, start=start, chunk_size=chunk_size)
        chunk_content = content[start:end].strip()
        if chunk_content:
            ranges.append((start, end))
        if end >= len(content):
            break
        next_start = _find_overlap_start(
            content,
            chunk_start=start,
            chunk_end=end,
            overlap=overlap,
        )
        start = next_start if next_start > start else end

    _merge_short_tail(content, ranges=ranges, chunk_size=chunk_size)
    return [content[start:end].strip() for start, end in ranges]


def _validate_configuration(*, chunk_size: int, overlap: int, max_chunks: int) -> None:
    values_are_integers = all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (chunk_size, overlap, max_chunks)
    )
    if (
        not values_are_integers
        or chunk_size <= 0
        or overlap < 0
        or overlap >= chunk_size
        or max_chunks <= 0
    ):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.INVALID_CHUNK_CONFIGURATION
        )


def _merge_short_tail(
    content: str,
    *,
    ranges: list[tuple[int, int]],
    chunk_size: int,
) -> None:
    if len(ranges) < 2:
        return

    previous_start, previous_end = ranges[-2]
    _, tail_end = ranges[-1]
    effective_minimum = min(
        _MIN_EFFECTIVE_NON_WHITESPACE,
        max(1, chunk_size // 4),
    )
    new_tail = content[previous_end:tail_end]
    if _non_whitespace_count(new_tail) >= effective_minimum:
        return

    merged_content = content[previous_start:tail_end].strip()
    if len(merged_content) <= chunk_size + effective_minimum:
        ranges[-2:] = [(previous_start, tail_end)]


def _non_whitespace_count(content: str) -> int:
    return sum(not character.isspace() for character in content)


def _find_chunk_end(content: str, *, start: int, chunk_size: int) -> int:
    maximum_end = min(start + chunk_size, len(content))
    if maximum_end == len(content):
        return maximum_end

    minimum_natural_end = start + max(1, chunk_size // 2)
    for boundaries in _BOUNDARY_GROUPS:
        candidates = [
            position + len(boundary)
            for boundary in boundaries
            if (
                position := content.rfind(
                    boundary,
                    minimum_natural_end,
                    maximum_end,
                )
            )
            >= 0
        ]
        if candidates:
            return max(candidates)
    return maximum_end


def _find_overlap_start(
    content: str,
    *,
    chunk_start: int,
    chunk_end: int,
    overlap: int,
) -> int:
    if overlap == 0:
        return chunk_end

    target = max(chunk_start + 1, chunk_end - overlap)
    search_start = max(chunk_start + 1, target - overlap)
    for boundaries in _BOUNDARY_GROUPS:
        candidates: list[int] = []
        for boundary in boundaries:
            position = content.find(boundary, search_start, chunk_end)
            while position >= 0:
                candidate = position + len(boundary)
                if candidate < chunk_end:
                    candidates.append(candidate)
                position = content.find(boundary, position + len(boundary), chunk_end)
        if candidates:
            return min(
                candidates,
                key=lambda candidate: (abs(candidate - target), candidate),
            )
    return target
