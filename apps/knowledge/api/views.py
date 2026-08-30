"""Views for Admin-only Knowledge Document management."""

from rest_framework import mixins, status, viewsets
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.knowledge.models import KnowledgeDocument
from apps.knowledge.services import indexing

from .errors import KnowledgeAPIError
from .pagination import KnowledgeDocumentPagination
from .permissions import IsBusinessAdmin
from .serializers import (
    KnowledgeDocumentCreateSerializer,
    KnowledgeDocumentReadSerializer,
)


_REINDEX_CONFLICT_CODES = {
    KnowledgeDocumentErrorCode.INVALID_REINDEX_STATE.value,
    KnowledgeDocumentErrorCode.INDEXING_ALREADY_IN_PROGRESS.value,
    KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT.value,
}
_INITIAL_INDEX_CONFLICT_CODES = {
    KnowledgeDocumentErrorCode.INVALID_INDEXING_STATE.value,
    KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT.value,
}


class KnowledgeDocumentViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create and read Knowledge Documents without mutation or deletion."""

    queryset = KnowledgeDocument.objects.order_by("-updated_at", "-id")
    permission_classes = (IsBusinessAdmin,)
    parser_classes = (MultiPartParser, FormParser)
    pagination_class = KnowledgeDocumentPagination
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        if getattr(self, "action", None) == "create":
            return KnowledgeDocumentCreateSerializer
        return KnowledgeDocumentReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save(created_by=request.user)

        try:
            indexing.index_document(document.pk)
        except KnowledgeDocumentError as error:
            document.refresh_from_db()
            if document.status != KnowledgeDocument.Status.FAILED:
                error_status = (
                    status.HTTP_409_CONFLICT
                    if error.code in _INITIAL_INDEX_CONFLICT_CODES
                    else status.HTTP_422_UNPROCESSABLE_ENTITY
                )
                raise KnowledgeAPIError(error, status_code=error_status) from None

        document.refresh_from_db()
        output = KnowledgeDocumentReadSerializer(
            document,
            context=self.get_serializer_context(),
        )
        return Response(output.data, status=status.HTTP_201_CREATED)

    def reindex(self, request, *args, **kwargs):
        document = self.get_object()
        try:
            document = indexing.reindex_document(document.pk)
        except KnowledgeDocumentError as error:
            error_status = (
                status.HTTP_409_CONFLICT
                if error.code in _REINDEX_CONFLICT_CODES
                else status.HTTP_422_UNPROCESSABLE_ENTITY
            )
            raise KnowledgeAPIError(error, status_code=error_status) from None

        output = KnowledgeDocumentReadSerializer(
            document,
            context=self.get_serializer_context(),
        )
        return Response(output.data, status=status.HTTP_200_OK)
