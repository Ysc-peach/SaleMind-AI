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
    INVALID_INDEXING_STATE = "invalid_indexing_state"
    INVALID_REINDEX_STATE = "invalid_reindex_state"
    INDEXING_ALREADY_IN_PROGRESS = "indexing_already_in_progress"
    INDEXING_FAILED = "indexing_failed"
    REINDEX_FAILED = "reindex_failed"
    NO_INDEXABLE_CONTENT = "no_indexable_content"
    INDEXING_RUN_CONFLICT = "indexing_run_conflict"


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
    KnowledgeDocumentErrorCode.INVALID_INDEXING_STATE: (
        "The document is not pending initial indexing."
    ),
    KnowledgeDocumentErrorCode.INVALID_REINDEX_STATE: (
        "The document does not have a ready index to rebuild."
    ),
    KnowledgeDocumentErrorCode.INDEXING_ALREADY_IN_PROGRESS: (
        "The document is already being indexed."
    ),
    KnowledgeDocumentErrorCode.INDEXING_FAILED: (
        "The document could not be indexed."
    ),
    KnowledgeDocumentErrorCode.REINDEX_FAILED: (
        "The document index could not be rebuilt."
    ),
    KnowledgeDocumentErrorCode.NO_INDEXABLE_CONTENT: (
        "The document contains no indexable content."
    ),
    KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT: (
        "The indexing run is no longer current."
    ),
}


class KnowledgeDocumentError(Exception):
    """Document failure safe to persist without leaking implementation details."""

    def __init__(self, code: KnowledgeDocumentErrorCode):
        self.code = code.value
        self.safe_message = _SAFE_ERROR_MESSAGES[code]
        super().__init__(self.safe_message)
