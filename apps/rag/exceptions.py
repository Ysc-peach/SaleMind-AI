"""Stable errors owned by the RAG orchestration layer."""

from enum import StrEnum


class RAGErrorCode(StrEnum):
    INVALID_QUERY = "invalid_rag_query"


_SAFE_ERROR_MESSAGES = {
    RAGErrorCode.INVALID_QUERY: "The RAG query must be a non-empty string.",
}


class RAGServiceError(Exception):
    """A stable error for failures that belong to RAG orchestration itself."""

    def __init__(self, code: RAGErrorCode):
        self.code = code.value
        self.safe_message = _SAFE_ERROR_MESSAGES[code]
        super().__init__(self.safe_message)
