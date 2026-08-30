"""Safe HTTP errors for the RAG Answer API."""

from rest_framework.exceptions import APIException


class RAGRequestValidationError(APIException):
    """Return one stable validation envelope without reflecting input data."""

    status_code = 400
    default_code = "invalid_request"

    def __init__(self):
        super().__init__(
            {
                "code": "invalid_request",
                "message": "The RAG answer request is invalid.",
            }
        )


class RAGDomainAPIError(APIException):
    """Expose only a domain error's stable code and safe message."""

    default_code = "rag_error"

    def __init__(self, error, *, status_code: int):
        self.status_code = status_code
        super().__init__({"code": error.code, "message": error.safe_message})
