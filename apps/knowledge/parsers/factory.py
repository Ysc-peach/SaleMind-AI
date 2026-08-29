"""Parser selection based on a validated document type."""

from collections.abc import Callable
from typing import BinaryIO

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)

from .types import DocumentFileType, ParsedSegment, ValidatedDocumentFile
from .validation import validate_document_file


Parser = Callable[[ValidatedDocumentFile], list[ParsedSegment]]


def get_parser(file_type: DocumentFileType) -> Parser:
    if file_type is DocumentFileType.TEXT:
        from .text import parse_text

        return parse_text
    if file_type is DocumentFileType.MARKDOWN:
        from .markdown import parse_markdown

        return parse_markdown

    if file_type is DocumentFileType.PDF:
        from .pdf import parse_pdf

        return parse_pdf

    raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.UNSUPPORTED_FILE_TYPE)


def parse_document(source: BinaryIO, original_filename: str) -> list[ParsedSegment]:
    document = validate_document_file(source, original_filename)
    return get_parser(document.file_type)(document)
