"""Stable, safe errors raised while processing knowledge documents."""

from enum import StrEnum


class KnowledgeDocumentErrorCode(StrEnum):
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    FILE_TOO_LARGE = "file_too_large"
    INVALID_FILE = "invalid_file"
    ENCRYPTED_PDF = "encrypted_pdf"
    PDF_PAGE_LIMIT_EXCEEDED = "pdf_page_limit_exceeded"
    NO_EXTRACTABLE_TEXT = "no_extractable_text"
    INVALID_TEXT_ENCODING = "invalid_text_encoding"


_SAFE_ERROR_MESSAGES = {
    KnowledgeDocumentErrorCode.UNSUPPORTED_FILE_TYPE: "The file type is not supported.",
    KnowledgeDocumentErrorCode.FILE_TOO_LARGE: "The file exceeds the allowed size.",
    KnowledgeDocumentErrorCode.INVALID_FILE: "The file is invalid or corrupted.",
    KnowledgeDocumentErrorCode.ENCRYPTED_PDF: "Encrypted PDF files are not supported.",
    KnowledgeDocumentErrorCode.PDF_PAGE_LIMIT_EXCEEDED: (
        "The PDF exceeds the allowed page count."
    ),
    KnowledgeDocumentErrorCode.NO_EXTRACTABLE_TEXT: (
        "The document contains no extractable text."
    ),
    KnowledgeDocumentErrorCode.INVALID_TEXT_ENCODING: (
        "The text file must use UTF-8 encoding."
    ),
}


class KnowledgeDocumentError(Exception):
    """Document failure safe to persist without leaking implementation details."""

    def __init__(self, code: KnowledgeDocumentErrorCode):
        self.code = code.value
        self.safe_message = _SAFE_ERROR_MESSAGES[code]
        super().__init__(self.safe_message)
