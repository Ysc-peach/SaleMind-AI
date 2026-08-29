"""Page-preserving PDF parser backed by pypdf."""

import re
from io import BytesIO

from django.conf import settings
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)

from .types import ParsedSegment, ValidatedDocumentFile


def validate_pdf_data(data: bytes) -> None:
    """Confirm a signed PDF can be opened within the supported V1 limits."""

    _load_pdf_reader(data)


def parse_pdf(document: ValidatedDocumentFile) -> list[ParsedSegment]:
    reader = _load_pdf_reader(document.data)
    segments = []

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            content = _normalize_pdf_text(page.extract_text() or "")
        except (OSError, TypeError, ValueError, PyPdfError):
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.INVALID_FILE
            ) from None

        if not content:
            continue
        segments.append(
            ParsedSegment(
                content=content,
                page_number=page_number,
                section_title=None,
                source_reference=(
                    f"《{document.original_filename}》第 {page_number} 页"
                ),
                metadata={"file_type": "pdf", "page_number": page_number},
            )
        )

    if not segments:
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.NO_EXTRACTABLE_TEXT
        )
    return segments


def _load_pdf_reader(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.ENCRYPTED_PDF
            )
        page_count = len(reader.pages)
    except KnowledgeDocumentError:
        raise
    except (OSError, TypeError, ValueError, PyPdfError):
        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.INVALID_FILE) from None

    if page_count > settings.KNOWLEDGE_MAX_PDF_PAGES:
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.PDF_PAGE_LIMIT_EXCEEDED
        )
    return reader


def _normalize_pdf_text(text: str) -> str:
    normalized_lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        normalized_line = re.sub(r"[^\S\n]+", " ", line).strip()
        if normalized_line:
            normalized_lines.append(normalized_line)
    return "\n".join(normalized_lines)
