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
    INVALID_CHUNK_CONFIGURATION = "invalid_chunk_configuration"
    CHUNK_LIMIT_EXCEEDED = "chunk_limit_exceeded"
    UNSUPPORTED_EMBEDDING_PROVIDER = "unsupported_embedding_provider"
    EMBEDDING_NOT_CONFIGURED = "embedding_not_configured"
    EMBEDDING_PROVIDER_ERROR = "embedding_provider_error"
    EMBEDDING_INVALID_RESPONSE = "embedding_invalid_response"
    EMBEDDING_DIMENSION_MISMATCH = "embedding_dimension_mismatch"
    EMBEDDING_EMPTY_INPUT = "embedding_empty_input"


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
    KnowledgeDocumentErrorCode.INVALID_CHUNK_CONFIGURATION: (
        "The chunking configuration is invalid."
    ),
    KnowledgeDocumentErrorCode.CHUNK_LIMIT_EXCEEDED: (
        "The document exceeds the allowed chunk count."
    ),
    KnowledgeDocumentErrorCode.UNSUPPORTED_EMBEDDING_PROVIDER: (
        "The embedding provider is not supported."
    ),
    KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED: (
        "The embedding provider is not configured."
    ),
    KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR: (
        "The embedding provider request failed."
    ),
    KnowledgeDocumentErrorCode.EMBEDDING_INVALID_RESPONSE: (
        "The embedding provider returned an invalid response."
    ),
    KnowledgeDocumentErrorCode.EMBEDDING_DIMENSION_MISMATCH: (
        "The embedding vector dimensions do not match the configuration."
    ),
    KnowledgeDocumentErrorCode.EMBEDDING_EMPTY_INPUT: (
        "Embedding input must contain non-empty text."
    ),
}


class KnowledgeDocumentError(Exception):
    """Document failure safe to persist without leaking implementation details."""

    def __init__(self, code: KnowledgeDocumentErrorCode):
        self.code = code.value
        self.safe_message = _SAFE_ERROR_MESSAGES[code]
        super().__init__(self.safe_message)
