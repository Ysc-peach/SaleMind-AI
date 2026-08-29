"""Shared value objects for knowledge document parsing."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedSegment:
    content: str
    page_number: int | None
    section_title: str | None
    source_reference: str
    metadata: dict[str, Any]


class DocumentFileType(StrEnum):
    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class ValidatedDocumentFile:
    data: bytes
    file_type: DocumentFileType
    original_filename: str
    mime_type: str
