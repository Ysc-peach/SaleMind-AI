"""Content-based validation for uploaded knowledge documents."""

from pathlib import Path
from typing import BinaryIO
from unicodedata import category

from django.conf import settings

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)

from .types import DocumentFileType, ValidatedDocumentFile


_PDF_SIGNATURE = b"%PDF-"
_TEXT_TYPES = {
    ".md": (DocumentFileType.MARKDOWN, "text/markdown"),
    ".txt": (DocumentFileType.TEXT, "text/plain"),
}
_ALLOWED_TEXT_CONTROLS = {"\t", "\n", "\r"}


def validate_document_file(
    source: BinaryIO,
    original_filename: str,
) -> ValidatedDocumentFile:
    """Read a bounded stream and determine a supported type from its content."""

    data = _read_bounded_bytes(source)
    display_filename = _display_filename(original_filename)

    if data.startswith(_PDF_SIGNATURE):
        from .pdf import validate_pdf_data

        validate_pdf_data(data)
        return ValidatedDocumentFile(
            data=data,
            file_type=DocumentFileType.PDF,
            original_filename=display_filename,
            mime_type="application/pdf",
        )

    suffix = Path(display_filename).suffix.lower()
    if suffix == ".pdf":
        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.INVALID_FILE)
    if suffix not in _TEXT_TYPES:
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.UNSUPPORTED_FILE_TYPE
        )

    text = _decode_utf8(data)
    if _contains_binary_controls(text):
        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.INVALID_FILE)

    file_type, mime_type = _TEXT_TYPES[suffix]
    return ValidatedDocumentFile(
        data=data,
        file_type=file_type,
        original_filename=display_filename,
        mime_type=mime_type,
    )


def decode_validated_text(document: ValidatedDocumentFile) -> str:
    """Decode text previously accepted by ``validate_document_file``."""

    return _decode_utf8(document.data)


def _read_bounded_bytes(source: BinaryIO) -> bytes:
    try:
        source.seek(0)
        data = source.read(settings.KNOWLEDGE_MAX_FILE_SIZE_BYTES + 1)
    except (AttributeError, OSError, TypeError, ValueError):
        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.INVALID_FILE) from None

    if not isinstance(data, bytes):
        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.INVALID_FILE)
    if len(data) > settings.KNOWLEDGE_MAX_FILE_SIZE_BYTES:
        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.FILE_TOO_LARGE)
    return data


def _decode_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.INVALID_TEXT_ENCODING
        ) from None


def _contains_binary_controls(text: str) -> bool:
    return any(
        category(character) == "Cc" and character not in _ALLOWED_TEXT_CONTROLS
        for character in text
    )


def _display_filename(original_filename: str) -> str:
    return str(original_filename).replace("\\", "/").rsplit("/", maxsplit=1)[-1]
