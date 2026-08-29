"""Plain UTF-8 text parser."""

import re

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)

from .types import ParsedSegment, ValidatedDocumentFile
from .validation import decode_validated_text


def parse_text(document: ValidatedDocumentFile) -> list[ParsedSegment]:
    content = _normalize_plain_text(decode_validated_text(document))
    if not content:
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.NO_EXTRACTABLE_TEXT
        )

    return [
        ParsedSegment(
            content=content,
            page_number=None,
            section_title=None,
            source_reference=f"《{document.original_filename}》",
            metadata={"file_type": "text"},
        )
    ]


def _normalize_plain_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", normalized).strip()
