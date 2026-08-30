"""Safe HTTP representations of Knowledge domain errors."""

from rest_framework.exceptions import APIException

from apps.knowledge.exceptions import KnowledgeDocumentError


class KnowledgeAPIError(APIException):
    """Expose only a stable domain code and its safe message."""

    status_code = 400
    default_code = "knowledge_error"

    def __init__(
        self,
        error: KnowledgeDocumentError,
        *,
        status_code: int | None = None,
    ):
        if status_code is not None:
            self.status_code = status_code
        super().__init__({"code": error.code, "message": error.safe_message})
